import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import type { EngineHealth, EngineSnapshotEvent, GearGoalView, GearPlanView, ItemLookupView, LootEventView, LootItemInfoView, LootQueryResult } from "./protocol";

type LootScope = "all" | "mine" | "others" | "known";
type LookupStatus = "idle" | "loading" | "ready" | "not-found" | "offline" | "error";

interface LootChronicleProps {
  event: EngineSnapshotEvent;
  health: EngineHealth;
  gearPlan?: GearPlanView;
  initialEventId?: string | null;
  onAnalyze: () => void;
  onHud: () => void;
  onSeed: () => void;
  onMinimize: () => void;
  onClose: () => void;
}

function normalize(value: string): string {
  return String(value ?? "").toLocaleLowerCase().replace(/[\u2019'`_-]+/g, " ").replace(/\s+/g, " ").trim();
}

function itemWikiUrl(item: string): string {
  const baseItem = item.replace(/\s+\+\d+\s*$/, "").trim();
  return `https://eqlwiki.com/${encodeURIComponent(baseItem.replace(/\s+/g, "_"))}`;
}

function compactNumber(value: number): string {
  const magnitude = Math.abs(value);
  if (magnitude >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}m`;
  if (magnitude >= 1_000) return `${(value / 1_000).toFixed(magnitude >= 100_000 ? 0 : 1)}k`;
  return Math.round(value).toLocaleString();
}

function eventStamp(value: string): { day: string; time: string; full: string } {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return { day: "LOG", time: "-", full: "Log time unavailable" };
  return {
    day: date.toLocaleDateString([], { month: "short", day: "numeric" }).toUpperCase(),
    time: date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    full: date.toLocaleString(),
  };
}

function tierLabel(row: LootEventView): string {
  const tier = Number.isInteger(row.raidTier) ? `D${row.raidTier}` : "OPEN WORLD";
  return row.raidMode ? `${tier} / ${row.raidMode.toUpperCase()}` : tier;
}

function isCharacterLoot(row: LootEventView): boolean {
  const looter = normalize(row.looter);
  return looter === "you" || Boolean(looter && looter === normalize(row.character));
}

function acquisitionEvidence(row: LootEventView): string {
  const who = row.looter || "A player";
  const source = row.source ? ` from ${row.source}` : "";
  if (row.acquisitionType === "auto-sold") return `${who} looted and automatically sold ${row.item}${source}.`;
  if (row.acquisitionType === "merged") return `${who} created ${row.item} by merging two items.`;
  if (row.acquisitionType === "inventory-placement") return `${row.item} was placed in ${who}'s inventory.`;
  if (row.acquisitionType.startsWith("stored-")) {
    const destination = row.acquisitionType.slice("stored-".length).replaceAll("-", " ");
    return `${who} looted ${row.item}${source} and stored it in ${destination}.`;
  }
  return `${who} looted ${row.item}${source}.`;
}

function ItemIntelligence({ row, info, lookupStatus, gearGoal }: {
  row: LootEventView;
  info?: LootItemInfoView;
  lookupStatus: LookupStatus;
  gearGoal?: GearGoalView;
}) {
  // Ranked items (+1, +2, and so on) share the base item's wiki page. Always
  // derive the external URL from the observed name so a cached ranked URL can
  // never send the user to a non-existent page.
  const url = itemWikiUrl(row.item);
  const sections = info ? Object.entries(info.sections ?? {}).filter(([, values]) => values?.length > 0) : [];
  const emptyTitle = lookupStatus === "loading" ? "Consulting the local knowledge service"
    : lookupStatus === "offline" ? "Offline / exact page still available"
      : lookupStatus === "not-found" ? "No exact item page was found"
        : lookupStatus === "error" ? "Knowledge service unavailable" : "Knowledge card not cached yet";
  return <aside className={`loot-intelligence ${info ? "enriched" : "pending"}`} aria-label={`${row.item} item intelligence`}>
    <header>
      <span className="loot-rune" aria-hidden="true">&#9671;</span>
      <div><small>{info ? "ITEM INTELLIGENCE" : "EQL WIKI READY"}</small><h2>{info?.title || row.item}</h2></div>
      {row.quantity > 1 && <b>&times;{row.quantity}</b>}
    </header>
    <div className="loot-item-context"><span>{row.zone || "UNKNOWN ZONE"}</span><i /><span>{tierLabel(row)}</span></div>

    {gearGoal && <section className={`loot-goal-match ${gearGoal.ownership}`}>
      <span>&#9733;</span><div><small>GEAR PLAN MATCH / {gearGoal.slot.toUpperCase()}</small><b>{gearGoal.ownership === "missing" ? isCharacterLoot(row) && row.acquisitionType !== "auto-sold" ? "BUILD GOAL ACQUIRED" : "BUILD GOAL DROP OBSERVED" : gearGoal.ownership === "bag" ? "BAG UPGRADE READY" : "GOAL ALREADY OWNED"}</b><p>{gearGoal.source || gearGoal.zone || "EQ Legends Tools character build"}</p></div>
    </section>}

    {info?.stats?.length ? <section className="loot-stat-block"><small>ITEM PROFILE</small><div>{info.stats.slice(0, 18).map((stat, index) => <span key={`${stat}-${index}`}>{stat}</span>)}</div></section>
      : <section className={`loot-wiki-empty ${lookupStatus}`}><span>{lookupStatus === "loading" ? "..." : "~"}</span><b>{emptyTitle}</b><p>{lookupStatus === "loading" ? "The ledger remains responsive while item knowledge is resolved outside the renderer." : "Open the exact EQL Wiki page or revisit later; observed loot evidence remains available offline."}</p></section>}

    {sections.slice(0, 8).map(([title, values]) => <section className="loot-knowledge-section" key={title}><small>{title.replaceAll("_", " ").toUpperCase()}</small>{values.slice(0, 8).map((value, index) => <p key={`${title}-${value}-${index}`}><i />{value}</p>)}</section>)}
    {info?.notes?.length ? <section className="loot-notes"><small>NOTES</small>{info.notes.slice(0, 6).map((note, index) => <p key={`${note}-${index}`}>{note}</p>)}</section> : null}
    <section className="loot-provenance"><small>OBSERVED EVIDENCE</small><p>{acquisitionEvidence(row)}</p><span>{eventStamp(row.occurredAt).full}{row.source ? ` / ${row.source}` : ""}</span></section>
    <footer><button type="button" onClick={() => void window.loremasterDesktop?.openExternal(url)}>OPEN EQL WIKI &#8599;</button><span>{info?.freshness ? `CACHE / ${info.freshness}` : "EXACT ITEM PAGE"}</span></footer>
  </aside>;
}

export function LootChronicle({ event, health, gearPlan, initialEventId, onAnalyze, onHud, onSeed, onMinimize, onClose }: LootChronicleProps) {
  const events = event.snapshot.loot ?? [];
  const [scope, setScope] = useState<LootScope>("all");
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query);
  const [zone, setZone] = useState("all");
  const [difficulty, setDifficulty] = useState("all");
  const [durable, setDurable] = useState<LootQueryResult | null>(null);
  const [queryBusy, setQueryBusy] = useState(false);
  const [queryError, setQueryError] = useState(false);
  const [selectedId, setSelectedId] = useState(initialEventId || events[0]?.eventId || "");
  const appliedInitialEvent = useRef(false);
  const itemCache = useRef(new Map<string, ItemLookupView>());
  const [lookup, setLookup] = useState<{ key: string; status: LookupStatus; value?: ItemLookupView }>({ key: "", status: "idle" });
  const character = normalize(event.snapshot.character.name);
  const snapshotSignature = events.length ? `${events.length}:${events[0]?.eventId}:${events.at(-1)?.eventId}` : "empty";
  const zones = useMemo(() => [...new Set(events.map((row) => row.zone).filter(Boolean))].sort(), [events]);
  const snapshotFiltered = useMemo(() => {
    const needle = normalize(deferredQuery);
    return [...events].filter((row) => {
      const mine = isCharacterLoot(row) || normalize(row.looter) === character;
      if (scope === "mine" && !mine) return false;
      if (scope === "others" && mine) return false;
      if (scope === "known" && !row.itemInfo && itemCache.current.get(row.itemKey || normalize(row.item))?.status !== "ready") return false;
      if (zone !== "all" && row.zone !== zone) return false;
      if (difficulty !== "all" && String(row.raidTier ?? "open") !== difficulty) return false;
      return !needle || normalize(`${row.item} ${row.looter} ${row.source} ${row.zone} ${row.raidMode}`).includes(needle);
    }).sort((left, right) => new Date(right.occurredAt).valueOf() - new Date(left.occurredAt).valueOf());
  }, [events, scope, zone, difficulty, deferredQuery, character, lookup.key, lookup.status]);

  useEffect(() => {
    const queryLoot = window.loremasterDesktop?.queryLoot;
    if (!queryLoot) { setDurable(null); return undefined; }
    let active = true;
    setDurable(null);
    setQueryBusy(true);
    setQueryError(false);
    const timer = window.setTimeout(() => {
      void queryLoot({
        query: deferredQuery.trim(), zone, scope,
        raidTier: difficulty === "all" ? "all" : difficulty === "open" ? "open" : Number(difficulty),
        offset: 0, limit: 100,
      }).then((result) => {
        if (!active) return;
        // The worker may be restarting while the live snapshot already has
        // matching rows. Keep those visible instead of replacing useful local
        // evidence with a transient empty response.
        setDurable(result.total === 0 && snapshotFiltered.length > 0 ? null : result);
        setQueryBusy(false);
      }).catch(() => {
        if (!active) return;
        setDurable(null);
        setQueryBusy(false);
        setQueryError(true);
      });
    }, 220);
    return () => { active = false; window.clearTimeout(timer); };
  }, [deferredQuery, zone, difficulty, scope, snapshotSignature, snapshotFiltered.length]);

  const filtered = durable ? [...durable.rows] : snapshotFiltered;

  useEffect(() => {
    if (!appliedInitialEvent.current && initialEventId && events.some((row) => row.eventId === initialEventId)) {
      appliedInitialEvent.current = true;
      setSelectedId(initialEventId);
    }
  }, [events, initialEventId]);

  useEffect(() => {
    if (filtered.length > 0 && !filtered.some((row) => row.eventId === selectedId)) setSelectedId(filtered[0].eventId);
  }, [filtered, selectedId]);
  const selected = filtered.find((row) => row.eventId === selectedId) ?? filtered[0];
  const visible = durable ? filtered : filtered.slice(0, 600);
  const quantity = filtered.reduce((total, row) => total + Math.max(1, row.quantity || 1), 0);
  const unique = new Set(filtered.map((row) => row.itemKey || normalize(row.item))).size;
  const playerCount = new Set(filtered.map((row) => normalize(row.looter)).filter(Boolean)).size;

  useEffect(() => {
    const item = selected?.item?.trim();
    if (!item || selected?.itemInfo) {
      setLookup({ key: normalize(item ?? ""), status: selected?.itemInfo ? "ready" : "idle" });
      return undefined;
    }
    const key = selected.itemKey || normalize(item);
    const cached = itemCache.current.get(key);
    if (cached) { setLookup({ key, status: cached.status, value: cached }); return undefined; }
    const lookupItem = window.loremasterDesktop?.lookupItem;
    if (!lookupItem) { setLookup({ key, status: "idle" }); return undefined; }
    let active = true;
    setLookup({ key, status: "loading" });
    const timer = window.setTimeout(() => {
      void lookupItem(item).then((result) => {
        if (!active || !result) return;
        if (result.status === "ready" || result.status === "not-found") itemCache.current.set(key, result);
        setLookup({ key, status: result.status, value: result });
      }).catch(() => { if (active) setLookup({ key, status: "error" }); });
    }, 140);
    return () => { active = false; window.clearTimeout(timer); };
  }, [selected?.eventId, selected?.item, selected?.itemKey, selected?.itemInfo]);

  const selectedKey = selected?.itemKey || normalize(selected?.item ?? "");
  const resolvedInfo = selected?.itemInfo ?? (lookup.key === selectedKey && lookup.value?.status === "ready" ? lookup.value : undefined);
  const selectedGearGoal = selected ? gearPlan?.goals.find((goal) => normalize(goal.itemName) === normalize(selected.item)) : undefined;
  const loadMore = async () => {
    const queryLoot = window.loremasterDesktop?.queryLoot;
    if (!durable?.hasMore || !queryLoot || queryBusy) return;
    setQueryBusy(true);
    setQueryError(false);
    try {
      const result = await queryLoot({
        query: deferredQuery.trim(), zone, scope,
        raidTier: difficulty === "all" ? "all" : difficulty === "open" ? "open" : Number(difficulty),
        offset: durable.rows.length, limit: 100,
      });
      setDurable((current) => current ? {
        rows: [...current.rows, ...result.rows], total: result.total,
        offset: 0, hasMore: result.hasMore,
      } : result);
    } catch {
      setQueryError(true);
    } finally {
      setQueryBusy(false);
    }
  };

  return <main className="loot-shell">
    <header className="loot-masthead"><img src="./loremaster-cog.png" alt="" /><div><small>LOREMASTER / ADVENTURE MEMORY</small><h1>SPOILS CHRONICLE</h1></div><span className={`loot-health ${health.state}`}><i /> {health.state.toUpperCase()} / {event.snapshot.character.name}</span><nav aria-label="Chronicle window controls"><button type="button" onClick={onAnalyze}>ANALYZE</button><button type="button" onClick={onHud}>HUD</button><button type="button" onClick={onSeed}>SEED</button><button type="button" onClick={onMinimize} aria-label="Minimize Loremaster">-</button><button type="button" onClick={onClose} aria-label="Close Loremaster">&times;</button></nav></header>
    <section className="loot-kpis" aria-label="Loot summary"><article className="primary"><small>OBSERVED LOOT</small><b>{compactNumber(event.snapshot.lootTotalCount ?? quantity)}</b><span>{event.snapshot.lootEventCount ?? events.length} durable events</span></article><article><small>UNIQUE ITEMS</small><b>{compactNumber(event.snapshot.lootUniqueCount ?? unique)}</b><span>across the local chronicle</span></article><article><small>VISIBLE NOW</small><b>{compactNumber(quantity)}</b><span>{filtered.length} matching recent events</span></article><article><small>LOOTERS</small><b>{playerCount}</b><span>in the current bounded view</span></article></section>
    <section className="loot-workspace"><aside className="loot-ledger"><header><div><small>LOOT LEDGER</small><b>{durable ? `${visible.length} / ${durable.total}` : `${filtered.length} / ${events.length}`} EVENTS</b></div><span role="status" aria-live="polite">{queryBusy ? "SEARCHING LOCAL JOURNAL" : queryError ? "RECENT VIEW / JOURNAL UNAVAILABLE" : "LOCAL / REPLAY SAFE"}</span></header><div className="loot-filter-pills" role="group" aria-label="Loot ownership filter">{(["all", "mine", "others", "known"] as LootScope[]).map((value) => <button type="button" key={value} className={scope === value ? "active" : ""} aria-pressed={scope === value} onClick={() => setScope(value)}>{value.toUpperCase()}</button>)}</div><div className="loot-filters"><input aria-label="Search loot" placeholder="Search items, sources, zones..." value={query} onChange={(change) => setQuery(change.target.value)} /><select aria-label="Filter loot zone" value={zone} onChange={(change) => setZone(change.target.value)}><option value="all">ALL ZONES</option>{zones.map((value) => <option key={value} value={value}>{value.toUpperCase()}</option>)}</select><select aria-label="Filter loot difficulty" value={difficulty} onChange={(change) => setDifficulty(change.target.value)}><option value="all">ALL TIERS</option><option value="open">OPEN WORLD</option>{[0, 1, 2, 3, 4].map((value) => <option key={value} value={value}>D{value}</option>)}</select></div>
      <div className="loot-event-list" role="list" aria-label="Observed loot events">{visible.map((row) => { const stamp = eventStamp(row.occurredAt); const isSelected = selected?.eventId === row.eventId; return <div role="listitem" key={row.eventId}><button type="button" aria-pressed={isSelected} aria-label={`${row.item}, ${row.quantity} observed, ${row.looter || "unknown looter"}, ${row.zone || "unknown zone"}`} className={isSelected ? "selected" : ""} onClick={() => setSelectedId(row.eventId)} onFocus={() => setSelectedId(row.eventId)}><span className="loot-date"><small>{stamp.day}</small><b>{stamp.time}</b></span><span className="loot-event-copy"><small>{row.looter || "UNKNOWN LOOTER"}{row.source ? ` / ${row.source}` : ""}</small><b>{row.item}</b><em>{row.zone || "UNKNOWN ZONE"} / {tierLabel(row)}</em></span><strong aria-hidden="true">{row.quantity > 1 ? <>&times;{row.quantity}</> : row.itemInfo ? <>&#9670;</> : <>&#9671;</>}</strong></button></div>; })}
      {durable?.hasMore && <button type="button" className="loot-load-more" disabled={queryBusy} onClick={() => void loadMore()}>{queryBusy ? "LOADING..." : `LOAD MORE / ${Math.max(0, durable.total - durable.rows.length).toLocaleString()} REMAIN`}</button>}{!durable && filtered.length > visible.length && <p className="loot-list-limit">Showing the newest {visible.length.toLocaleString()} matching events. Refine filters to inspect older entries.</p>}{filtered.length === 0 && <div className="loot-empty" role="status"><span aria-hidden="true">&#9671;</span><b>{events.length === 0 ? "THE LEDGER IS READY" : "NO MATCHING SPOILS"}</b><p>{events.length === 0 ? "Loot lines observed in your EverQuest log will become a durable, searchable chronicle here." : "Change the search or filters to reveal more of the chronicle."}</p></div>}</div></aside>
      {selected ? <ItemIntelligence row={selected} info={resolvedInfo} gearGoal={selectedGearGoal} lookupStatus={lookup.key === selectedKey ? lookup.status : "idle"} /> : <aside className="loot-intelligence empty"><span aria-hidden="true">&#9671;</span><b>SELECT AN ITEM</b><p>Click or focus a loot event to inspect its evidence and item knowledge.</p></aside>}</section>
    <footer className="loot-disclaimer"><i /> OBSERVED LOOT ONLY / Loremaster records loot announced in your local EverQuest log; unopened or filtered corpse contents cannot be inferred.</footer>
  </main>;
}
