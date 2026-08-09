import { useEffect, useMemo, useRef, useState } from "react";
import type {
  CombatActorRole,
  CombatHealingMetricView,
  CombatMetricView,
  EncounterTimelinePointView,
  EncounterView,
  EngineHealth,
  EngineSnapshotEvent,
  WeeklyProgressView,
} from "./protocol";

type EncounterFilter = "all" | "boss" | "kills" | "live";
type EncounterSort = "newest" | "dps" | "damage" | "duration";
type DetailTab = "actors" | "abilities" | "targets" | "healing" | "timeline";
type DetailSort = "damage" | "dps" | "share" | "hits" | "average" | "maximum";
type AnalysisScope = "selected" | "combined";
type ActorFilter = "all" | CombatActorRole;

interface AnalysisRow {
  name: string;
  role: string;
  total: number;
  dps: number;
  share: number;
  hits: number;
  average: number;
  maximum: number;
  overheal: number;
}

interface CombatArchiveProps {
  event: EngineSnapshotEvent;
  health: EngineHealth;
  weekly?: WeeklyProgressView;
  onHud: () => void;
  onSeed: () => void;
  onMinimize: () => void;
  onClose: () => void;
}

const fallbackBosses = [
  "Master Yael", "Phinigel Autropos", "Lord Nagafen",
  "Lady Vox", "Innoruuk", "Cazic-Thule",
];

const actorLabels: Record<CombatActorRole, string> = {
  self: "SELF", charmed: "CHARMED", summoned: "SUMMONED",
  group: "GROUP", observed: "OBSERVED",
};

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}

function compactNumber(value: number): string {
  const magnitude = Math.abs(value);
  if (magnitude >= 1_000_000) return `${(value / 1_000_000).toFixed(magnitude >= 10_000_000 ? 1 : 2)}m`;
  if (magnitude >= 1_000) return `${(value / 1_000).toFixed(magnitude >= 100_000 ? 0 : 1)}k`;
  return Math.round(value).toLocaleString();
}

function clock(value: number): string {
  const seconds = Math.max(0, Math.floor(value));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = String(seconds % 60).padStart(2, "0");
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, "0")}:${remainder}` : `${minutes}:${remainder}`;
}

function encounterStamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "—" : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function normalizeName(value: string): string {
  return value.toLocaleLowerCase().replace(/[’'`_-]+/g, " ").replace(/\s+/g, " ").trim();
}

function metricTotals(rows: readonly CombatMetricView[]): CombatMetricView[] {
  const totals = new Map<string, CombatMetricView>();
  for (const row of rows) {
    const current = totals.get(row.name) ?? { name: row.name, total: 0, hits: 0, maximum: 0 };
    totals.set(row.name, {
      name: row.name,
      total: current.total + row.total,
      hits: current.hits + row.hits,
      maximum: Math.max(current.maximum, row.maximum),
    });
  }
  return [...totals.values()].sort((left, right) => right.total - left.total || left.name.localeCompare(right.name));
}

function healingTotals(rows: readonly CombatHealingMetricView[]): CombatHealingMetricView[] {
  const totals = new Map<string, CombatHealingMetricView>();
  for (const row of rows) {
    const current = totals.get(row.name) ?? { name: row.name, total: 0, hits: 0, maximum: 0, overheal: 0 };
    totals.set(row.name, {
      name: row.name,
      total: current.total + row.total,
      hits: current.hits + row.hits,
      maximum: Math.max(current.maximum, row.maximum),
      overheal: current.overheal + row.overheal,
    });
  }
  return [...totals.values()].sort((left, right) => right.total - left.total || left.name.localeCompare(right.name));
}

function combineEncounters(encounters: readonly EncounterView[]): EncounterView {
  const seconds = encounters.reduce((sum, row) => sum + row.seconds, 0);
  const starts = encounters.map((row) => row.startedAt).filter(Boolean).sort();
  const ends = encounters.map((row) => row.endedAt).filter(Boolean).sort();
  const actors = new Map<string, EncounterView["actors"][number]>();
  for (const encounter of encounters) {
    for (const actor of encounter.actors) {
      const key = `${actor.role}:${actor.name}`;
      const current = actors.get(key);
      const damage = (current?.encounterDamage ?? 0) + actor.encounterDamage;
      const hits = (current?.encounterHits ?? 0) + actor.encounterHits;
      actors.set(key, {
        ...actor,
        encounterDamage: damage,
        encounterDps: seconds > 0 ? Math.round(damage / seconds) : 0,
        encounterHits: hits,
        encounterMaximum: Math.max(current?.encounterMaximum ?? 0, actor.encounterMaximum),
        sessionDamage: damage,
        sessionDps: seconds > 0 ? Math.round(damage / seconds) : 0,
        sessionHits: hits,
        sessionMaximum: Math.max(current?.sessionMaximum ?? 0, actor.sessionMaximum),
      });
    }
  }
  const damage = encounters.reduce((sum, row) => sum + row.damage, 0);
  return {
    encounterId: `combined-${encounters.map((row) => row.encounterId).join("-")}`,
    name: encounters.length === 1 ? encounters[0].name : `${encounters.length} ENCOUNTERS COMBINED`,
    active: encounters.some((row) => row.active),
    startedAt: starts[0] ?? "",
    endedAt: ends.at(-1) ?? "",
    seconds,
    damage,
    dps: seconds > 0 ? Math.round(damage / seconds) : 0,
    personalDamage: encounters.reduce((sum, row) => sum + row.personalDamage, 0),
    charmedPetDamage: encounters.reduce((sum, row) => sum + row.charmedPetDamage, 0),
    summonedPetDamage: encounters.reduce((sum, row) => sum + row.summonedPetDamage, 0),
    damageTaken: encounters.reduce((sum, row) => sum + row.damageTaken, 0),
    healingDone: encounters.reduce((sum, row) => sum + row.healingDone, 0),
    healsReceived: encounters.reduce((sum, row) => sum + row.healsReceived, 0),
    kills: encounters.reduce((sum, row) => sum + row.kills, 0),
    crits: encounters.reduce((sum, row) => sum + row.crits, 0),
    misses: encounters.reduce((sum, row) => sum + row.misses, 0),
    sources: metricTotals(encounters.flatMap((row) => row.sources)),
    targets: metricTotals(encounters.flatMap((row) => row.targets)),
    actors: [...actors.values()].sort((left, right) => right.encounterDamage - left.encounterDamage),
    healingSources: healingTotals(encounters.flatMap((row) => row.healingSources)),
    timeline: [],
  };
}

function rowsFor(tab: DetailTab, encounter: EncounterView, actorFilter: ActorFilter): AnalysisRow[] {
  const denominator = tab === "healing" ? encounter.healingDone : encounter.damage;
  const seconds = Math.max(1, encounter.seconds);
  if (tab === "actors") return encounter.actors
    .filter((row) => actorFilter === "all" || row.role === actorFilter)
    .map((row) => ({
      name: row.name, role: actorLabels[row.role], total: row.encounterDamage,
      dps: row.encounterDamage / seconds,
      share: denominator > 0 ? row.encounterDamage / denominator * 100 : 0,
      hits: row.encounterHits,
      average: row.encounterHits > 0 ? row.encounterDamage / row.encounterHits : 0,
      maximum: row.encounterMaximum, overheal: 0,
    }));
  if (tab === "healing") return encounter.healingSources.map((row) => ({
    name: row.name, role: "HEAL", total: row.total, dps: row.total / seconds,
    share: denominator > 0 ? row.total / denominator * 100 : 0,
    hits: row.hits, average: row.hits > 0 ? row.total / row.hits : 0,
    maximum: row.maximum, overheal: row.overheal,
  }));
  const metrics = tab === "targets" ? encounter.targets : encounter.sources;
  return metrics.map((row) => ({
    name: row.name, role: tab === "targets" ? "TARGET" : "ABILITY",
    total: row.total, dps: row.total / seconds,
    share: denominator > 0 ? row.total / denominator * 100 : 0,
    hits: row.hits, average: row.hits > 0 ? row.total / row.hits : 0,
    maximum: row.maximum, overheal: 0,
  }));
}

function TimelineChart({ points, seconds }: { points: readonly EncounterTimelinePointView[]; seconds: number }) {
  const [hovered, setHovered] = useState<EncounterTimelinePointView | null>(null);
  const plotRef = useRef<HTMLDivElement>(null);
  if (points.length === 0) return <div className="archive-empty-chart"><b>NO TIMELINE FOR THIS SCOPE</b><span>Select one encounter to inspect its two-second combat trace.</span></div>;
  const width = 920;
  const height = 220;
  const ceiling = Math.max(1, ...points.flatMap((point) => [point.outgoing, point.incoming, point.healing]));
  const duration = Math.max(1, seconds, points.at(-1)?.second ?? 1);
  const line = (key: "outgoing" | "incoming" | "healing") => points.map((point) => {
    const x = point.second / duration * width;
    const y = height - (point[key] / ceiling * (height - 18)) - 8;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const hoverX = hovered ? hovered.second / duration * width : 0;
  const inspect = (clientX: number) => {
    const bounds = plotRef.current?.getBoundingClientRect();
    if (!bounds || bounds.width <= 0) return;
    const second = clamp((clientX - bounds.left) / bounds.width, 0, 1) * duration;
    setHovered(points.reduce((nearest, point) => (
      Math.abs(point.second - second) < Math.abs(nearest.second - second) ? point : nearest
    ), points[0]));
  };
  return <section className="archive-timeline">
    <header><span><i className="out" /> OUTGOING</span><span><i className="inc" /> INCOMING</span><span><i className="heal" /> HEALING</span><b>HOVER FOR PLAY-BY-PLAY · PEAK {compactNumber(ceiling)}</b></header>
    <div className="archive-timeline-plot" ref={plotRef}
      onPointerMove={(event) => inspect(event.clientX)} onPointerLeave={() => setHovered(null)}>
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="Encounter outgoing, incoming and healing timeline">
        {[0.25, 0.5, 0.75].map((position) => <line key={position} x1="0" x2={width} y1={height * position} y2={height * position} className="grid" />)}
        <polyline points={line("incoming")} className="incoming" />
        <polyline points={line("healing")} className="healing" />
        <polyline points={line("outgoing")} className="outgoing" />
        {hovered && <line className="cursor" x1={hoverX} x2={hoverX} y1="0" y2={height} />}
      </svg>
      {hovered && <output className="archive-timeline-tooltip" style={{ left: `${clamp(hovered.second / duration * 100, 8, 92)}%` }}>
        <b>{clock(hovered.second)}</b>
        <span><i className="out" /> OUT <strong>{hovered.outgoing.toLocaleString()}</strong></span>
        <span><i className="inc" /> IN <strong>{hovered.incoming.toLocaleString()}</strong></span>
        <span><i className="heal" /> HEAL <strong>{hovered.healing.toLocaleString()}</strong></span>
        {hovered.kills > 0 && <em>{hovered.kills} KILL{hovered.kills === 1 ? "" : "S"}</em>}
      </output>}
    </div>
    <footer><span>0:00</span><span>{clock(duration / 2)}</span><span>{clock(duration)}</span></footer>
  </section>;
}

export function CombatArchive({ event, health, weekly, onHud, onSeed, onMinimize, onClose }: CombatArchiveProps) {
  const encounters = event.snapshot.encounters ?? [];
  const [filter, setFilter] = useState<EncounterFilter>("all");
  const [sort, setSort] = useState<EncounterSort>("newest");
  const [query, setQuery] = useState("");
  const [detailQuery, setDetailQuery] = useState("");
  const [selectedId, setSelectedId] = useState(encounters.at(-1)?.encounterId ?? "");
  const [scope, setScope] = useState<AnalysisScope>("selected");
  const [tab, setTab] = useState<DetailTab>("actors");
  const [detailSort, setDetailSort] = useState<DetailSort>("damage");
  const [actorFilter, setActorFilter] = useState<ActorFilter>("all");
  const bossNames = useMemo(() => (weekly?.raids.map((row) => row.target) ?? fallbackBosses).map(normalizeName), [weekly]);
  const isBoss = (encounter: EncounterView) => bossNames.some((name) => normalizeName(encounter.name).includes(name));
  const filtered = useMemo(() => {
    const needle = normalizeName(query);
    const rows = encounters.filter((encounter) => {
      if (needle && !normalizeName(encounter.name).includes(needle)) return false;
      if (filter === "boss" && !isBoss(encounter)) return false;
      if (filter === "kills" && encounter.kills <= 0) return false;
      if (filter === "live" && !encounter.active) return false;
      return true;
    });
    return [...rows].sort((left, right) => {
      if (sort === "dps") return right.dps - left.dps;
      if (sort === "damage") return right.damage - left.damage;
      if (sort === "duration") return right.seconds - left.seconds;
      return new Date(right.startedAt).valueOf() - new Date(left.startedAt).valueOf();
    });
  }, [encounters, filter, query, sort, bossNames]);

  useEffect(() => {
    if (filtered.length > 0 && !filtered.some((row) => row.encounterId === selectedId)) {
      setSelectedId(filtered[0].encounterId);
    }
  }, [filtered, selectedId]);

  const selected = filtered.find((row) => row.encounterId === selectedId) ?? filtered[0];
  const analyzed = scope === "combined" && filtered.length > 0 ? combineEncounters(filtered) : selected;
  const tableRows = useMemo(() => {
    if (!analyzed || tab === "timeline") return [];
    const needle = normalizeName(detailQuery);
    const rows = rowsFor(tab, analyzed, actorFilter).filter((row) => !needle || normalizeName(row.name).includes(needle));
    const value = (row: AnalysisRow) => detailSort === "damage" ? row.total : row[detailSort];
    return rows.sort((left, right) => value(right) - value(left) || left.name.localeCompare(right.name));
  }, [analyzed, tab, detailQuery, detailSort, actorFilter]);

  if (!analyzed) return <main className="archive-shell archive-empty">
    <header className="archive-masthead"><img src="./loremaster-cog.png" alt="" /><div><small>LOREMASTER · COMBAT ARCHIVE</small><h1>WAITING FOR ENCOUNTERS</h1></div><button onClick={onHud}>RETURN TO HUD</button></header>
    <section><b>No parsed fights yet.</b><span>Keep logging enabled; finished and active encounters will appear here automatically.</span></section>
  </main>;

  const totalHits = analyzed.sources.reduce((sum, row) => sum + row.hits, 0);
  const accuracy = totalHits + analyzed.misses > 0 ? totalHits / (totalHits + analyzed.misses) * 100 : 0;
  const critRate = totalHits > 0 ? analyzed.crits / totalHits * 100 : 0;
  const petDamage = analyzed.charmedPetDamage + analyzed.summonedPetDamage;
  const petShare = analyzed.damage > 0 ? petDamage / analyzed.damage * 100 : 0;
  const selfShare = analyzed.damage > 0 ? analyzed.personalDamage / analyzed.damage * 100 : 0;
  const charmedShare = analyzed.damage > 0 ? analyzed.charmedPetDamage / analyzed.damage * 100 : 0;
  const summonedShare = analyzed.damage > 0 ? analyzed.summonedPetDamage / analyzed.damage * 100 : 0;
  const maxHistoryDps = Math.max(1, ...filtered.map((row) => row.dps));
  const maxRowTotal = Math.max(1, ...tableRows.map((row) => row.total));
  const strongest = analyzed.sources[0];
  const primaryTarget = analyzed.targets[0];
  const pressure = analyzed.damageTaken / Math.max(1, analyzed.seconds);

  return <main className="archive-shell">
    <header className="archive-masthead">
      <img src="./loremaster-cog.png" alt="" />
      <div><small>LOREMASTER · COMBAT ARCHIVE</small><h1>FULL BREAKDOWN</h1></div>
      <span className={`archive-health ${health.state}`}><i /> {health.state.toUpperCase()} · {event.snapshot.character.name}</span>
      <nav><button onClick={onHud}>HUD</button><button onClick={onSeed}>SEED</button><button onClick={onMinimize}>—</button><button onClick={onClose}>×</button></nav>
    </header>

    <section className="archive-layout">
      <aside className="archive-fights">
        <header><div><small>ENCOUNTER INDEX</small><b>{filtered.length} / {encounters.length} SHOWN</b></div><span>{event.snapshot.character.zone || "UNKNOWN ZONE"}</span></header>
        <div className="archive-filter-pills">
          {(["all", "boss", "kills", "live"] as EncounterFilter[]).map((value) => <button className={filter === value ? "active" : ""} key={value} onClick={() => setFilter(value)}>{value === "boss" ? "BOSSES" : value.toUpperCase()}</button>)}
        </div>
        <div className="archive-search"><input aria-label="Search encounters" placeholder="Search fights…" value={query} onChange={(change) => setQuery(change.target.value)} /><select aria-label="Sort encounters" value={sort} onChange={(change) => setSort(change.target.value as EncounterSort)}><option value="newest">NEWEST</option><option value="dps">HIGHEST DPS</option><option value="damage">MOST DAMAGE</option><option value="duration">LONGEST</option></select></div>
        <div className="archive-fight-list">
          {filtered.map((encounter) => <button className={`${selected?.encounterId === encounter.encounterId ? "selected" : ""} ${encounter.active ? "live" : ""}`} key={encounter.encounterId} onClick={() => { setSelectedId(encounter.encounterId); setScope("selected"); }}>
            <span><small>{encounterStamp(encounter.startedAt)}{isBoss(encounter) ? " · BOSS" : encounter.kills > 0 ? " · CLEAR" : ""}</small><b>{encounter.name}</b></span>
            <strong>{compactNumber(encounter.dps)}<small>DPS</small></strong>
            <footer><span>{compactNumber(encounter.damage)} dmg</span><span>{clock(encounter.seconds)}</span></footer>
          </button>)}
          {filtered.length === 0 && <p>No encounters match these filters.</p>}
        </div>
      </aside>

      <section className="archive-report">
        <header className="archive-report-head">
          <div><small>{scope === "combined" ? "FILTERED SET" : analyzed.active ? "LIVE ENCOUNTER" : "SELECTED ENCOUNTER"}</small><h2>{analyzed.name}</h2><p>{scope === "combined" ? `${filtered.length} fights · active filters applied` : `${encounterStamp(analyzed.startedAt)} · ${isBoss(analyzed) ? "tracked raid boss" : analyzed.kills > 0 ? `${analyzed.kills} confirmed kill${analyzed.kills === 1 ? "" : "s"}` : "combat ended without a logged kill"}`}</p></div>
          <div className="archive-scope"><button className={scope === "selected" ? "active" : ""} onClick={() => setScope("selected")}>ONE FIGHT</button><button className={scope === "combined" ? "active" : ""} disabled={filtered.length < 2} onClick={() => setScope("combined")}>COMBINE FILTERED</button></div>
        </header>

        <div className="archive-kpis">
          <article className="primary"><small>DPS</small><b>{compactNumber(analyzed.dps)}</b><span>{scope === "combined" ? "weighted active time" : "encounter output"}</span></article>
          <article><small>DAMAGE</small><b>{compactNumber(analyzed.damage)}</b><span>{analyzed.kills} kill{analyzed.kills === 1 ? "" : "s"}</span></article>
          <article><small>DURATION</small><b>{clock(analyzed.seconds)}</b><span>{scope === "combined" ? `${filtered.length} encounters` : analyzed.active ? "still active" : "final"}</span></article>
          <article><small>INCOMING</small><b>{compactNumber(analyzed.damageTaken)}</b><span>{compactNumber(pressure)}/s</span></article>
          <article><small>HEALING</small><b>{compactNumber(analyzed.healingDone)}</b><span>{compactNumber(analyzed.healsReceived)} received</span></article>
          <article><small>ACCURACY</small><b>{accuracy.toFixed(1)}%</b><span>{critRate.toFixed(1)}% crit · {analyzed.misses} miss</span></article>
        </div>

        <section className="archive-contribution">
          <header><span><small>ATTRIBUTION</small><b>SELF + PET CONTRIBUTION</b></span><strong>{petShare.toFixed(1)}% PET SHARE</strong></header>
          <div className="archive-share-track" aria-label={`Self ${selfShare.toFixed(1)} percent, charmed pet ${charmedShare.toFixed(1)} percent, summoned pet ${summonedShare.toFixed(1)} percent`}><i className="self" style={{ width: `${selfShare}%` }} /><i className="charmed" style={{ width: `${charmedShare}%` }} /><i className="summoned" style={{ width: `${summonedShare}%` }} /></div>
          <footer><span><i className="self" /> SELF <b>{compactNumber(analyzed.personalDamage)}</b></span><span><i className="charmed" /> CHARMED <b>{compactNumber(analyzed.charmedPetDamage)}</b></span><span><i className="summoned" /> SUMMONED <b>{compactNumber(analyzed.summonedPetDamage)}</b></span></footer>
        </section>

        <section className="archive-history">
          <header><span><small>FIGHT PULSE</small><b>DPS ACROSS CURRENT FILTER</b></span><strong>PEAK {compactNumber(maxHistoryDps)}</strong></header>
          <div>{filtered.slice(0, 36).reverse().map((encounter) => <button key={encounter.encounterId} title={`${encounter.name} · ${compactNumber(encounter.dps)} DPS`} className={encounter.encounterId === selected?.encounterId ? "selected" : ""} style={{ height: `${Math.max(6, encounter.dps / maxHistoryDps * 100)}%` }} onClick={() => { setSelectedId(encounter.encounterId); setScope("selected"); }} />)}</div>
        </section>

        <nav className="archive-tabs">
          {(["actors", "abilities", "targets", "healing", "timeline"] as DetailTab[]).map((value) => <button className={tab === value ? "active" : ""} key={value} onClick={() => setTab(value)}>{value.toUpperCase()}<small>{value === "actors" ? analyzed.actors.length : value === "abilities" ? analyzed.sources.length : value === "targets" ? analyzed.targets.length : value === "healing" ? analyzed.healingSources.length : analyzed.timeline.length}</small></button>)}
        </nav>

        {tab === "timeline" ? <TimelineChart points={analyzed.timeline} seconds={analyzed.seconds} /> : <section className="archive-detail-grid">
          <div className="archive-table-wrap">
            <header className="archive-table-tools"><input aria-label="Search breakdown rows" placeholder={`Search ${tab}…`} value={detailQuery} onChange={(change) => setDetailQuery(change.target.value)} />{tab === "actors" && <select aria-label="Actor role" value={actorFilter} onChange={(change) => setActorFilter(change.target.value as ActorFilter)}><option value="all">ALL ROLES</option><option value="self">SELF</option><option value="charmed">CHARMED</option><option value="summoned">SUMMONED</option><option value="group">GROUP</option><option value="observed">OBSERVED</option></select>}<span>{tableRows.length} ROWS</span></header>
            <div className="archive-table">
              <header><span>NAME / ROLE</span>{(["damage", "dps", "share", "hits", "average", "maximum"] as DetailSort[]).map((value) => <button className={detailSort === value ? "active" : ""} key={value} onClick={() => setDetailSort(value)}>{tab === "healing" && value === "damage" ? "HEAL" : tab === "healing" && value === "dps" ? "HPS" : value === "maximum" ? "MAX" : value === "average" ? "AVG" : value.toUpperCase()}</button>)}</header>
              {tableRows.slice(0, 50).map((row) => <article key={`${row.role}-${row.name}`}>
                <i style={{ transform: `scaleX(${row.total / maxRowTotal})` }} />
                <span><b>{row.name}</b><small>{row.role}{row.overheal > 0 ? ` · ${compactNumber(row.overheal)} OVER` : ""}</small></span>
                <strong>{compactNumber(row.total)}</strong><strong>{compactNumber(row.dps)}</strong><strong>{row.share.toFixed(1)}%</strong><strong>{row.hits || "—"}</strong><strong>{row.hits ? compactNumber(row.average) : "—"}</strong><strong>{row.maximum ? compactNumber(row.maximum) : "—"}</strong>
              </article>)}
              {tableRows.length === 0 && <p>No evidence rows are available for this category.</p>}
            </div>
          </div>
          <aside className="archive-insights">
            <header><small>ENCOUNTER READOUT</small><b>AT A GLANCE</b></header>
            <article><small>TOP ABILITY</small><b>{strongest?.name || "—"}</b><span>{strongest ? `${compactNumber(strongest.total)} · ${(strongest.total / Math.max(1, analyzed.damage) * 100).toFixed(1)}%` : "No ability evidence"}</span></article>
            <article><small>PRIMARY TARGET</small><b>{primaryTarget?.name || "—"}</b><span>{primaryTarget ? `${compactNumber(primaryTarget.total)} attributed` : "No target evidence"}</span></article>
            <article><small>PET IMPACT</small><b>{petShare.toFixed(1)}%</b><span>{compactNumber(petDamage)} combined damage</span></article>
            <article><small>PRESSURE</small><b>{compactNumber(pressure)}/s</b><span>{analyzed.damageTaken > analyzed.healsReceived ? "damage exceeded received healing" : "received healing covered logged damage"}</span></article>
            <footer>Only evidence visible in your local EverQuest log is shown. Observed actors never inflate personal DPS.</footer>
          </aside>
        </section>}
      </section>
    </section>
  </main>;
}
