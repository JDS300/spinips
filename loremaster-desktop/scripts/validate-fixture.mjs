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
console.log(`Loremaster desktop fixture: PASS | ${fixture.events.length} snapshots`);
