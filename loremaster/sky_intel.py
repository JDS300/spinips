"""Offline Plane of Sky quest intelligence for Loremaster.

The bundled data is a versioned snapshot of the public EQ Legends Tools quest
table.  Runtime lookups are local: importing an ``inventory.txt`` file never
uploads character, server, or inventory data anywhere.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


DATA_FILE = "plane_of_sky_quests.json"
SOURCE_URL = "https://eqlegendstools.com/plane-of-sky-quests/"
MAP_MARKER_PREFIX = "Loremaster_Target_"
SKY_ISLAND_COORDS = {
    "1.5": (-1115.0021, -265.3858, -16.6764),
    "2": (663.4380, 299.0294, -338.6892),
    "3": (-273.7129, -827.8096, -73.0363),
    "4": (1064.2145, -857.3463, 172.9789),
    "5": (-931.6675, 610.4481, 450.5818),
    "6": (-155.0940, 930.9081, 788.1929),
    "7": (786.1703, 1476.0962, 1009.1132),
    "8": (1600.8938, 90.2137, 1221.7688),
}


def normalize_item_name(value: str) -> str:
    """Match EQ inventory rows, loot lines, and quest-table item names."""
    text = str(value or "").replace("’", "'").replace("‘", "'")
    text = re.sub(r"\s*\([^)]*\)\s*$", "", text)
    text = re.sub(r"\s+\+\d+\s*$", "", text)
    return re.sub(r"\s+", " ", text).strip().casefold()


def inventory_names_from_text(text: str) -> list[str]:
    """Read the tab-separated file produced by ``/outputfile inventory``.

    Legends currently emits a header with a Name column.  The second-column
    fallback preserves compatibility with older EQ output formats.
    """
    names: list[str] = []
    name_column = -1
    for line in str(text or "").splitlines():
        if not line.strip():
            continue
        columns = line.split("\t")
        if name_column < 0:
            lowered = [column.strip().casefold() for column in columns]
            if "name" in lowered:
                name_column = lowered.index("name")
                continue
        index = name_column if name_column >= 0 else 1
        raw = columns[index] if len(columns) > index else ""
        name = raw.strip()
        if name and name.casefold() != "empty":
            names.append(name)
    return names


def source_island(source: str) -> str | None:
    text = str(source or "").casefold()
    words = {"two": "2", "three": "3", "four": "4", "five": "5",
             "six": "6", "seven": "7", "eight": "8"}
    match = re.search(r"\bisle\s*(1\.5|[2-8]|two|three|four|five|six|seven|eight)\b",
                      text)
    if not match:
        return None
    return words.get(match.group(1), match.group(1))


def map_marker_line(reward: str, source: str) -> str | None:
    island = source_island(source)
    if island not in SKY_ISLAND_COORDS:
        return None
    x, y, z = SKY_ISLAND_COORDS[island]
    safe_reward = re.sub(r"[^A-Za-z0-9]+", "_", reward).strip("_")[:48]
    return (f"P {x:.4f}, {y:.4f}, {z:.4f},  80, 220, 255,  3,  "
            f"{MAP_MARKER_PREFIX}{safe_reward}_Isle_{island}")


def write_map_marker(maps_dir: str | Path, reward: str, source: str) -> Path:
    """Write one user-requested target on the dedicated Sky layer safely."""
    marker = map_marker_line(reward, source)
    if marker is None:
        raise ValueError("The selected source has no single Plane of Sky island")
    path = Path(maps_dir) / "airplane_3.txt"
    existing = path.read_text(encoding="utf-8", errors="replace").splitlines() \
        if path.exists() else []
    lines = [line for line in existing if MAP_MARKER_PREFIX not in line]
    lines.append(marker)
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_suffix(path.suffix + ".tmp")
    staged.write_text("\n".join(lines) + "\n", encoding="utf-8")
    staged.replace(path)
    return path


@dataclass(frozen=True)
class SkyQuestRow:
    class_name: str
    npc: str
    reward: str
    quest_item: str
    source: str


@dataclass(frozen=True)
class SkyRewardPlan:
    class_name: str
    npc: str
    reward: str
    required: tuple[SkyQuestRow, ...]
    owned: tuple[SkyQuestRow, ...]
    missing: tuple[SkyQuestRow, ...]

    @property
    def complete(self) -> bool:
        return not self.missing

    @property
    def sources(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(row.source for row in self.missing))


class SkyQuestCatalog:
    def __init__(self, rows: list[SkyQuestRow], metadata: dict | None = None):
        self.rows = tuple(rows)
        self.metadata = dict(metadata or {})
        self._items: dict[str, list[SkyQuestRow]] = defaultdict(list)
        self._rewards: dict[tuple[str, str, str], list[SkyQuestRow]] = defaultdict(list)
        for row in self.rows:
            self._items[normalize_item_name(row.quest_item)].append(row)
            self._rewards[(row.class_name, row.npc, row.reward)].append(row)

    @classmethod
    def load(cls, path: str | Path) -> "SkyQuestCatalog":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        rows = [SkyQuestRow(
            class_name=str(row["className"]).strip(),
            npc=str(row["npc"]).strip(),
            reward=str(row["reward"]).strip(),
            quest_item=str(row["questItem"]).strip(),
            source=str(row["source"]).strip(),
        ) for row in payload.get("rows", [])]
        return cls(rows, payload.get("metadata"))

    def item_matches(self, item_name: str) -> tuple[SkyQuestRow, ...]:
        return tuple(self._items.get(normalize_item_name(item_name), ()))

    def search_rewards(self, query: str = "", class_name: str = "") -> list[tuple[str, str, str]]:
        needle = normalize_item_name(query)
        cls = class_name.strip().casefold()
        matches = []
        for key, rows in self._rewards.items():
            row = rows[0]
            if cls and row.class_name.casefold() != cls:
                continue
            haystack = " ".join((row.reward, row.npc, *(r.quest_item for r in rows),
                                 *(r.source for r in rows))).casefold()
            if needle and needle not in haystack:
                continue
            matches.append(key)
        return sorted(matches, key=lambda key: (key[0], key[2], key[1]))

    def plan(self, key: tuple[str, str, str], owned_items=()) -> SkyRewardPlan:
        required = tuple(self._rewards.get(tuple(key), ()))
        counts = Counter(normalize_item_name(name) for name in owned_items)
        owned: list[SkyQuestRow] = []
        missing: list[SkyQuestRow] = []
        for row in required:
            item_key = normalize_item_name(row.quest_item)
            if counts[item_key] > 0:
                owned.append(row)
                counts[item_key] -= 1
            else:
                missing.append(row)
        class_name, npc, reward = key
        return SkyRewardPlan(class_name, npc, reward, required,
                             tuple(owned), tuple(missing))


def load_bundled_catalog(base_dir: str | Path) -> SkyQuestCatalog:
    return SkyQuestCatalog.load(Path(base_dir) / "assets" / DATA_FILE)
