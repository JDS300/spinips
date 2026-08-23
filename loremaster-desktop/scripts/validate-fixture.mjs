import { readFile } from "node:fs/promises";

const url = new URL("../fixtures/control-replay.json", import.meta.url);
const fixture = JSON.parse(await readFile(url, "utf8"));
if (fixture.schemaVersion !== 1) throw new Error("fixture schema must be version 1");
if (!Array.isArray(fixture.events) || fixture.events.length < 5) {
  throw new Error("fixture needs at least five replay states");
}
let previous = -1;
for (const event of fixture.events) {
  if (event.protocolVersion !== 1 || event.eventType !== "engine.snapshot") {
    throw new Error(`invalid event envelope at sequence ${event.sequence}`);
  }
  if (event.sequence <= previous) throw new Error("sequence must increase");
  if (!Array.isArray(event.snapshot?.controls)) throw new Error("controls must be an array");
  previous = event.sequence;
}
const earlySafeControl = fixture.events.some((event) => event.snapshot.controls.some((control) =>
  control.state === "active" && control.urgency === "safe" && control.safeRemainingSeconds > 20));
if (!earlySafeControl) {
  throw new Error("fixture must prove seeded controls exist before the warning window");
}
const activeKinds = new Set(fixture.events.flatMap((event) => event.snapshot.controls
  .filter((control) => control.state === "active")
  .map((control) => control.kind)));
if (!activeKinds.has("mez") || !activeKinds.has("lull")) {
  throw new Error("fixture must include active mez and lull controls");
}
// The debuff deck is optional on the wire, but where a fixture carries one it
// must be well formed, or the fixture cannot prove the deck renders.
const decks = fixture.events.map((event) => event.snapshot.debuffs).filter(Boolean);
if (decks.length === 0) throw new Error("fixture must exercise the debuff deck");
for (const deck of decks) {
  if (!Array.isArray(deck.groups) || typeof deck.overflow !== "number") {
    throw new Error("debuff deck needs a groups array and a numeric overflow");
  }
  for (const group of deck.groups) {
    if (typeof group.target !== "string" || !group.target) {
      throw new Error("every debuff group needs a target name");
    }
    if (!Array.isArray(group.rows) || group.rows.length === 0) {
      throw new Error(`debuff group ${group.target} needs rows`);
    }
    for (const row of group.rows) {
      if (typeof row.spell !== "string" || typeof row.remainingSeconds !== "number") {
        throw new Error(`malformed debuff row in ${group.target}`);
      }
      if (!["dot", "slow", "resist"].includes(row.kind)) {
        throw new Error(`unknown debuff kind ${row.kind}`);
      }
      if (!["exact", "conservative"].includes(row.durationConfidence)) {
        throw new Error(`unknown duration confidence ${row.durationConfidence}`);
      }
    }
  }
}
const debuffKinds = new Set(decks.flatMap((deck) => deck.groups.flatMap((group) =>
  group.rows.map((row) => row.kind))));
for (const kind of ["dot", "slow", "resist"]) {
  if (!debuffKinds.has(kind)) throw new Error(`fixture must include a ${kind} row`);
}
// A DoT is tick-confirmed and a slow is computed; the deck marks them
// differently, so the fixture has to contain both to prove that rendering.
const confidences = new Set(decks.flatMap((deck) => deck.groups.flatMap((group) =>
  group.rows.map((row) => row.durationConfidence))));
if (confidences.size < 2) {
  throw new Error("fixture must include both a confirmed and an estimated row");
}

console.log(`Loremaster desktop fixture: PASS | ${fixture.events.length} snapshots`);
