"""Durable, replay-safe local history for the Loremaster desktop engine.

The journal deliberately stores only structured gameplay evidence.  Chat text
and raw log lines never cross this boundary.  Stable hashes make replaying a
warm log window or reopening a rotated log idempotent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Mapping


SCHEMA_VERSION = 4
DEFAULT_QUERY_LIMIT = 60
MAX_QUERY_LIMIT = 250


@dataclass(frozen=True)
class JournalWrite:
    record_id: str
    inserted: bool


def utc_timestamp(value: datetime | str | None) -> str:
    """Return one sortable UTC timestamp suitable for SQLite and JSON."""
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            parsed = datetime.now(timezone.utc)
    else:
        parsed = value or datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone(timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def normalize_item_key(value: str) -> str:
    """Normalize an EQ item name to the shared base item-page identity."""
    text = str(value or "").replace("_", " ")
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n\"'[]<>")
    # Legends upgrade ranks share one source/stat page with the base item.
    text = re.sub(r"\s+\+\d+\s*$", "", text)
    return text[:120].strip().casefold()


def evidence_hash(*parts: object) -> str:
    """Hash structured evidence without retaining private/raw log content."""
    encoded = "\x1f".join(str(part or "").strip() for part in parts)
    return hashlib.sha256(encoded.encode("utf-8", errors="replace")).hexdigest()


def encounter_identity(*, character: str, server: str,
                       started_at: datetime | str, name: str) -> str:
    digest = evidence_hash(
        "encounter", character.casefold(), server.casefold(),
        utc_timestamp(started_at), name.casefold())
    return f"enc-{digest[:24]}"


class AdventureJournal:
    """Small SQLite repository optimized for append and bounded recent reads."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._connection: sqlite3.Connection | None = None
        self.degraded = False
        self.last_error = ""
        self.quarantined_path: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._open()
        except RuntimeError:
            # A valid database from a newer Loremaster must remain untouched.
            self._close_connection()
            raise
        except sqlite3.DatabaseError as error:
            self._close_connection()
            if self._is_corruption_error(error) and self.path.is_file():
                try:
                    self.quarantined_path = self._quarantine_corrupt_database()
                    self._open()
                    return
                except RuntimeError:
                    self._close_connection()
                    raise
                except (OSError, sqlite3.Error) as recovery_error:
                    self._degrade(recovery_error)
                    return
            self._degrade(error)
        except OSError as error:
            self._degrade(error)

    @property
    def available(self) -> bool:
        return self._connection is not None and not self.degraded

    def _open(self) -> None:
        connection = sqlite3.connect(
            self.path, timeout=5.0, isolation_level=None)
        self._connection = connection
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA foreign_keys = ON")
            # WAL keeps four-Hz renderer reads from waiting behind an append.
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            self._migrate()
        except Exception:
            self._close_connection()
            raise

    @staticmethod
    def _is_corruption_error(error: sqlite3.DatabaseError) -> bool:
        code = getattr(error, "sqlite_errorcode", None)
        if code in {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB}:
            return True
        message = str(error).casefold()
        return ("database disk image is malformed" in message
                or "file is not a database" in message)

    def _quarantine_corrupt_database(self) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        candidate = self.path.with_name(
            f"{self.path.name}.corrupt-{stamp}")
        suffix = 1
        while candidate.exists():
            candidate = self.path.with_name(
                f"{self.path.name}.corrupt-{stamp}-{suffix}")
            suffix += 1
        self.path.rename(candidate)
        for sidecar_suffix in ("-wal", "-shm"):
            sidecar = self.path.with_name(self.path.name + sidecar_suffix)
            if sidecar.exists():
                sidecar.rename(candidate.with_name(
                    candidate.name + sidecar_suffix))
        return candidate

    def _close_connection(self) -> None:
        connection, self._connection = self._connection, None
        if connection is not None:
            try:
                connection.close()
            except sqlite3.Error:
                pass

    def _degrade(self, error: BaseException) -> None:
        self._close_connection()
        self.degraded = True
        self.last_error = f"{type(error).__name__}: {error}"

    def close(self) -> None:
        self._close_connection()

    def _migrate(self) -> None:
        version = int(self._connection.execute(
            "PRAGMA user_version").fetchone()[0])
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"Adventure journal schema {version} is newer than supported "
                f"schema {SCHEMA_VERSION}")
        if version < 1:
            with self._connection:
                self._connection.executescript("""
                    CREATE TABLE IF NOT EXISTS loot_events (
                        event_id TEXT PRIMARY KEY,
                        occurred_at TEXT NOT NULL,
                        character TEXT NOT NULL DEFAULT '',
                        server TEXT NOT NULL DEFAULT '',
                        item_key TEXT NOT NULL,
                        item TEXT NOT NULL,
                        quantity INTEGER NOT NULL CHECK (quantity > 0),
                        looter TEXT NOT NULL DEFAULT '',
                        source TEXT NOT NULL DEFAULT '',
                        zone TEXT NOT NULL DEFAULT '',
                        encounter_id TEXT NOT NULL DEFAULT '',
                        acquisition_type TEXT NOT NULL DEFAULT 'loot',
                        raid_tier INTEGER CHECK (raid_tier BETWEEN 0 AND 4),
                        raid_mode TEXT NOT NULL DEFAULT '',
                        evidence_hash TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_loot_recent
                        ON loot_events(occurred_at DESC, event_id DESC);
                    CREATE INDEX IF NOT EXISTS idx_loot_character_recent
                        ON loot_events(character, occurred_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_loot_item_recent
                        ON loot_events(item_key, occurred_at DESC);

                    CREATE TABLE IF NOT EXISTS encounters (
                        encounter_id TEXT PRIMARY KEY,
                        started_at TEXT NOT NULL,
                        ended_at TEXT NOT NULL,
                        character TEXT NOT NULL DEFAULT '',
                        server TEXT NOT NULL DEFAULT '',
                        name TEXT NOT NULL,
                        zone TEXT NOT NULL DEFAULT '',
                        raid_tier INTEGER CHECK (raid_tier BETWEEN 0 AND 4),
                        raid_mode TEXT NOT NULL DEFAULT '',
                        seconds REAL NOT NULL DEFAULT 0,
                        damage INTEGER NOT NULL DEFAULT 0,
                        dps INTEGER NOT NULL DEFAULT 0,
                        kills INTEGER NOT NULL DEFAULT 0,
                        details_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_encounters_recent
                        ON encounters(ended_at DESC, encounter_id DESC);
                    CREATE INDEX IF NOT EXISTS idx_encounters_character_recent
                        ON encounters(character, ended_at DESC);
                    PRAGMA user_version = 1;
                """)
            version = 1
        if version < 2:
            with self._connection:
                self._connection.executescript("""
                    CREATE TABLE IF NOT EXISTS item_cache (
                        item_key TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        url TEXT NOT NULL DEFAULT '',
                        stats_json TEXT NOT NULL DEFAULT '{}',
                        notes TEXT NOT NULL DEFAULT '',
                        sections_json TEXT NOT NULL DEFAULT '{}',
                        source TEXT NOT NULL DEFAULT '',
                        fetched_at TEXT NOT NULL,
                        fresh_until TEXT NOT NULL DEFAULT ''
                    );
                    CREATE INDEX IF NOT EXISTS idx_item_cache_freshness
                        ON item_cache(fresh_until DESC);
                    PRAGMA user_version = 2;
                """)
            version = 2
        if version < 3:
            with self._connection:
                columns = {row[1] for row in self._connection.execute(
                    "PRAGMA table_info(item_cache)")}
                if "notes_json" not in columns:
                    self._connection.execute(
                        "ALTER TABLE item_cache ADD COLUMN notes_json TEXT "
                        "NOT NULL DEFAULT '[]'")
                    # Preserve an older single-note cache entry during the
                    # forward migration without relying on SQLite JSON1.
                    rows = self._connection.execute(
                        "SELECT item_key, notes FROM item_cache "
                        "WHERE notes <> ''").fetchall()
                    self._connection.executemany(
                        "UPDATE item_cache SET notes_json = ? "
                        "WHERE item_key = ?",
                        ((json.dumps([row["notes"]], ensure_ascii=False),
                          row["item_key"]) for row in rows))
                self._connection.execute("PRAGMA user_version = 3")
            version = 3
        if version < 4:
            with self._connection:
                self._connection.executescript("""
                    CREATE INDEX IF NOT EXISTS idx_loot_character_zone_recent
                        ON loot_events(character, zone, occurred_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_loot_character_tier_recent
                        ON loot_events(character, raid_tier, occurred_at DESC);
                    PRAGMA user_version = 4;
                """)

    @staticmethod
    def _limit(value: int | None) -> int:
        try:
            requested = int(value or DEFAULT_QUERY_LIMIT)
        except (TypeError, ValueError):
            requested = DEFAULT_QUERY_LIMIT
        return max(1, min(MAX_QUERY_LIMIT, requested))

    def record_loot(self, *, occurred_at: datetime | str, item: str,
                    quantity: int = 1, looter: str = "", source: str = "",
                    zone: str = "", character: str = "", server: str = "",
                    encounter_id: str = "", acquisition_type: str = "loot",
                    raid_tier: int | None = None, raid_mode: str = "",
                    evidence: str = "", event_id: str = "") -> JournalWrite:
        title = re.sub(r"\s+", " ", str(item or "")).strip()[:240]
        key = normalize_item_key(title)
        if not key:
            raise ValueError("loot item must not be empty")
        occurred = utc_timestamp(occurred_at)
        quantity = max(1, int(quantity or 1))
        proof = evidence_hash(
            occurred, evidence or acquisition_type, character.casefold(),
            server.casefold(), looter.casefold(), title, quantity, source)
        stable_id = event_id.strip() or f"loot-{proof[:24]}"
        tier = int(raid_tier) if raid_tier in range(5) else None
        now = utc_timestamp(datetime.now(timezone.utc))
        connection = self._connection
        if connection is None:
            return JournalWrite(stable_id, False)
        try:
            with connection:
                cursor = connection.execute("""
                    INSERT OR IGNORE INTO loot_events (
                        event_id, occurred_at, character, server, item_key,
                        item, quantity, looter, source, zone, encounter_id,
                        acquisition_type, raid_tier, raid_mode, evidence_hash,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    stable_id, occurred, str(character), str(server), key,
                    title, quantity, str(looter), str(source), str(zone),
                    str(encounter_id), str(acquisition_type or "loot"), tier,
                    str(raid_mode), proof, now))
        except sqlite3.Error as error:
            self._degrade(error)
            return JournalWrite(stable_id, False)
        return JournalWrite(stable_id, cursor.rowcount == 1)

    def record_encounter(self, *, started_at: datetime | str,
                         ended_at: datetime | str, name: str,
                         character: str = "", server: str = "",
                         zone: str = "", raid_tier: int | None = None,
                         raid_mode: str = "", seconds: float = 0.0,
                         damage: int = 0, dps: int = 0, kills: int = 0,
                         details: Mapping[str, Any] | None = None,
                         encounter_id: str = "") -> JournalWrite:
        started = utc_timestamp(started_at)
        ended = utc_timestamp(ended_at)
        stable_id = encounter_id.strip() or encounter_identity(
            character=str(character), server=str(server),
            started_at=started, name=str(name or "fight"))
        tier = int(raid_tier) if raid_tier in range(5) else None
        encoded = json.dumps(
            dict(details or {}), ensure_ascii=False, separators=(",", ":"),
            sort_keys=True)
        connection = self._connection
        if connection is None:
            return JournalWrite(stable_id, False)
        try:
            with connection:
                cursor = connection.execute("""
                    INSERT OR IGNORE INTO encounters (
                        encounter_id, started_at, ended_at, character, server,
                        name, zone, raid_tier, raid_mode, seconds, damage, dps,
                        kills, details_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    stable_id, started, ended, str(character), str(server),
                    str(name or "fight"), str(zone), tier, str(raid_mode),
                    max(0.0, float(seconds or 0.0)),
                    max(0, int(damage or 0)), max(0, int(dps or 0)),
                    max(0, int(kills or 0)), encoded,
                    utc_timestamp(datetime.now(timezone.utc))))
        except sqlite3.Error as error:
            self._degrade(error)
            return JournalWrite(stable_id, False)
        return JournalWrite(stable_id, cursor.rowcount == 1)

    def put_item_cache(self, *, title: str, url: str = "",
                       stats: Any = None, notes: Any = None,
                       sections: Any = None,
                       source: str = "", fetched_at: datetime | str | None = None,
                       fresh_until: datetime | str | None = None) -> str:
        key = normalize_item_key(title)
        if not key:
            raise ValueError("cached item title must not be empty")
        fetched = utc_timestamp(fetched_at)
        fresh = utc_timestamp(fresh_until) if fresh_until else ""
        if isinstance(notes, (list, tuple)):
            note_rows = [str(row) for row in notes]
        elif notes:
            note_rows = [str(notes)]
        else:
            note_rows = []
        stats_value = stats if isinstance(stats, (dict, list, tuple)) else {}
        sections_value = sections if isinstance(
            sections, (dict, list, tuple)) else {}
        connection = self._connection
        if connection is None:
            return key
        try:
            with connection:
                connection.execute("""
                    INSERT INTO item_cache (
                        item_key, title, url, stats_json, notes, sections_json,
                        source, fetched_at, fresh_until, notes_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(item_key) DO UPDATE SET
                        title=excluded.title, url=excluded.url,
                        stats_json=excluded.stats_json, notes=excluded.notes,
                        sections_json=excluded.sections_json,
                        source=excluded.source, fetched_at=excluded.fetched_at,
                        fresh_until=excluded.fresh_until,
                        notes_json=excluded.notes_json
                """, (
                    key, str(title).strip(), str(url), json.dumps(
                        stats_value, ensure_ascii=False, sort_keys=True),
                    "\n".join(note_rows), json.dumps(
                        sections_value, ensure_ascii=False, sort_keys=True),
                    str(source), fetched, fresh, json.dumps(
                        note_rows, ensure_ascii=False)))
        except sqlite3.Error as error:
            self._degrade(error)
        return key

    @staticmethod
    def _item_info(row: sqlite3.Row) -> dict[str, Any] | None:
        if row["cache_title"] is None:
            return None
        try:
            stats = json.loads(row["cache_stats"] or "{}")
        except (TypeError, ValueError):
            stats = {}
        try:
            sections = json.loads(row["cache_sections"] or "{}")
        except (TypeError, ValueError):
            sections = {}
        try:
            notes = json.loads(row["cache_notes_json"] or "[]")
        except (TypeError, ValueError):
            notes = []
        if not isinstance(notes, list):
            notes = []
        if not notes and row["cache_notes"]:
            notes = [row["cache_notes"]]
        return {
            "title": row["cache_title"], "url": row["cache_url"] or "",
            "stats": stats if isinstance(stats, (dict, list)) else {},
            "notes": notes,
            "sections": sections if isinstance(sections, dict) else {},
            "source": row["cache_source"] or "",
            "fetched_at": row["cache_fetched_at"] or "",
            "fresh_until": row["cache_fresh_until"] or "",
        }

    def get_item_cache(self, item: str) -> dict[str, Any] | None:
        key = normalize_item_key(item)
        connection = self._connection
        if connection is None:
            return None
        try:
            row = connection.execute("""
                SELECT title AS cache_title, url AS cache_url,
                       stats_json AS cache_stats, notes AS cache_notes,
                       notes_json AS cache_notes_json,
                       sections_json AS cache_sections, source AS cache_source,
                       fetched_at AS cache_fetched_at,
                       fresh_until AS cache_fresh_until
                  FROM item_cache WHERE item_key = ?
            """, (key,)).fetchone()
        except sqlite3.Error as error:
            self._degrade(error)
            return None
        return self._item_info(row) if row is not None else None

    def recent_loot(self, *, limit: int = DEFAULT_QUERY_LIMIT,
                    character: str = "") -> list[dict[str, Any]]:
        count = self._limit(limit)
        where = "WHERE l.character = ?" if character else ""
        args: tuple[Any, ...] = (str(character), count) if character else (count,)
        connection = self._connection
        if connection is None:
            return []
        try:
            rows = connection.execute(f"""
                SELECT l.*,
                       c.title AS cache_title, c.url AS cache_url,
                       c.stats_json AS cache_stats, c.notes AS cache_notes,
                       c.notes_json AS cache_notes_json,
                       c.sections_json AS cache_sections,
                       c.source AS cache_source,
                       c.fetched_at AS cache_fetched_at,
                       c.fresh_until AS cache_fresh_until
                  FROM loot_events l
                  LEFT JOIN item_cache c ON c.item_key = l.item_key
                  {where}
                 ORDER BY l.occurred_at DESC, l.event_id DESC
                 LIMIT ?
            """, args).fetchall()
        except sqlite3.Error as error:
            self._degrade(error)
            return []
        return [self._loot_row(row) for row in rows]

    def _loot_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "event_id": row["event_id"],
            "occurred_at": row["occurred_at"],
            "item": row["item"], "item_key": row["item_key"],
            "quantity": row["quantity"], "looter": row["looter"],
            "source": row["source"], "zone": row["zone"],
            "character": row["character"], "server": row["server"],
            "encounter_id": row["encounter_id"],
            "acquisition_type": row["acquisition_type"],
            "raid_tier": row["raid_tier"], "raid_mode": row["raid_mode"],
            "item_info": self._item_info(row),
        }

    def query_loot(self, *, query: str = "", zone: str = "",
                   raid_tier: int | str | None = "all", scope: str = "all",
                   character: str = "", offset: int = 0,
                   limit: int = 100) -> dict[str, Any]:
        """Search the durable ledger without pushing unbounded rows at 4 Hz."""
        connection = self._connection
        safe_offset = max(0, min(1_000_000, int(offset or 0)))
        safe_limit = self._limit(limit)
        if connection is None:
            return {"rows": [], "total": 0, "offset": safe_offset,
                    "has_more": False}
        clauses: list[str] = []
        parameters: list[Any] = []
        if character:
            clauses.append("l.character = ?")
            parameters.append(str(character))
        folded_scope = str(scope or "all").casefold()
        if folded_scope in {"mine", "others"}:
            mine_clause = "(LOWER(l.looter) = 'you' OR LOWER(l.looter) = LOWER(l.character))"
            clauses.append(mine_clause if folded_scope == "mine"
                           else f"NOT {mine_clause}")
        elif folded_scope == "known":
            clauses.append("c.item_key IS NOT NULL")
        cleaned_zone = str(zone or "").strip()
        if cleaned_zone and cleaned_zone.casefold() != "all":
            clauses.append("l.zone = ?")
            parameters.append(cleaned_zone)
        if raid_tier == "open":
            clauses.append("l.raid_tier IS NULL")
        elif isinstance(raid_tier, int) and raid_tier in range(5):
            clauses.append("l.raid_tier = ?")
            parameters.append(raid_tier)
        cleaned_query = re.sub(r"\s+", " ", str(query or "")).strip()[:160]
        if cleaned_query:
            escaped = (cleaned_query.replace("\\", "\\\\")
                       .replace("%", "\\%").replace("_", "\\_"))
            clauses.append("(" + " OR ".join(
                f"LOWER({column}) LIKE LOWER(?) ESCAPE '\\'"
                for column in ("l.item", "l.looter", "l.source", "l.zone")) + ")")
            parameters.extend([f"%{escaped}%"] * 4)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        try:
            total = int(connection.execute(f"""
                SELECT COUNT(*) FROM loot_events l
                LEFT JOIN item_cache c ON c.item_key = l.item_key
                {where}
            """, tuple(parameters)).fetchone()[0])
            rows = connection.execute(f"""
                SELECT l.*,
                       c.title AS cache_title, c.url AS cache_url,
                       c.stats_json AS cache_stats, c.notes AS cache_notes,
                       c.notes_json AS cache_notes_json,
                       c.sections_json AS cache_sections,
                       c.source AS cache_source,
                       c.fetched_at AS cache_fetched_at,
                       c.fresh_until AS cache_fresh_until
                  FROM loot_events l
                  LEFT JOIN item_cache c ON c.item_key = l.item_key
                  {where}
                 ORDER BY l.occurred_at DESC, l.event_id DESC
                 LIMIT ? OFFSET ?
            """, (*parameters, safe_limit, safe_offset)).fetchall()
        except sqlite3.Error as error:
            self._degrade(error)
            return {"rows": [], "total": 0, "offset": safe_offset,
                    "has_more": False}
        return {
            "rows": [self._loot_row(row) for row in rows],
            "total": total,
            "offset": safe_offset,
            "has_more": safe_offset + len(rows) < total,
        }

    def recent_encounters(self, *, limit: int = DEFAULT_QUERY_LIMIT,
                          character: str = "") -> list[dict[str, Any]]:
        count = self._limit(limit)
        where = "WHERE character = ?" if character else ""
        args: tuple[Any, ...] = (str(character), count) if character else (count,)
        connection = self._connection
        if connection is None:
            return []
        try:
            rows = connection.execute(f"""
                SELECT encounter_id, started_at, ended_at, character, server,
                       name, zone, raid_tier, raid_mode, seconds, damage, dps,
                       kills
                  FROM encounters {where}
                 ORDER BY ended_at DESC, encounter_id DESC
                 LIMIT ?
            """, args).fetchall()
        except sqlite3.Error as error:
            self._degrade(error)
            return []
        return [dict(row) for row in rows]

    def counts(self) -> dict[str, int]:
        connection = self._connection
        if connection is None:
            return {"loot": 0, "encounters": 0}
        try:
            return {
                "loot": int(connection.execute(
                    "SELECT COUNT(*) FROM loot_events").fetchone()[0]),
                "encounters": int(connection.execute(
                    "SELECT COUNT(*) FROM encounters").fetchone()[0]),
            }
        except sqlite3.Error as error:
            self._degrade(error)
            return {"loot": 0, "encounters": 0}

    def loot_summary(self, *, character: str = "") -> dict[str, int]:
        where = "WHERE character = ?" if character else ""
        args: tuple[Any, ...] = (str(character),) if character else ()
        connection = self._connection
        if connection is None:
            return {"events": 0, "quantity": 0, "unique_items": 0}
        try:
            row = connection.execute(f"""
                SELECT COUNT(*) AS events,
                       COALESCE(SUM(quantity), 0) AS quantity,
                       COUNT(DISTINCT item_key) AS unique_items
                  FROM loot_events {where}
            """, args).fetchone()
        except sqlite3.Error as error:
            self._degrade(error)
            return {"events": 0, "quantity": 0, "unique_items": 0}
        return {
            "events": int(row["events"] or 0),
            "quantity": int(row["quantity"] or 0),
            "unique_items": int(row["unique_items"] or 0),
        }


__all__ = [
    "AdventureJournal", "JournalWrite", "SCHEMA_VERSION", "encounter_identity",
    "evidence_hash", "normalize_item_key", "utc_timestamp",
]
