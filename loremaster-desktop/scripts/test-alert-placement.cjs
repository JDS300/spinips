const assert = require("node:assert/strict");

const {
  ALERT_SIDES,
  intersects,
  placeAlertWindow,
} = require("../dist-electron/alert-placement.js");

const WORK = { x: 0, y: 0, width: 1920, height: 1080 };
const MAIN = { x: 800, y: 500, width: 320, height: 120 };
const ALERT = { width: 360, height: 140 };
const GAP = 10;

function place(overrides = {}) {
  return placeAlertWindow({
    anchor: "auto",
    main: MAIN,
    alert: ALERT,
    control: null,
    workArea: WORK,
    gap: GAP,
    ...overrides,
  });
}

function rectOf(result) {
  return { x: result.x, y: result.y, ...ALERT };
}

// A control panel placed hard against each side of the main window, matching
// what syncControlWindow produces for that side.
function controlOn(side, size = { width: 300, height: 90 }) {
  if (side === "above") {
    return { x: MAIN.x, y: MAIN.y - size.height - 6, ...size };
  }
  if (side === "below") {
    return { x: MAIN.x, y: MAIN.y + MAIN.height + 6, ...size };
  }
  if (side === "left") {
    return { x: MAIN.x - size.width - 6, y: MAIN.y, ...size };
  }
  return { x: MAIN.x + MAIN.width + 6, y: MAIN.y, ...size };
}

function testStaysOnScreen() {
  for (const side of ALERT_SIDES) {
    for (const control of [null, ...ALERT_SIDES.map(controlOn)]) {
      const r = rectOf(place({ anchor: side, control }));
      assert.ok(r.x >= WORK.x && r.y >= WORK.y, `${side} escaped top/left`);
      assert.ok(r.x + r.width <= WORK.x + WORK.width, `${side} escaped right`);
      assert.ok(r.y + r.height <= WORK.y + WORK.height, `${side} escaped bottom`);
    }
  }
  console.log("  always inside the work area: PASS");
}

function testNoControlKeepsHistoricPreference() {
  // With room everywhere and no panel, auto has always preferred above.
  const result = place();
  assert.equal(result.side, "above");
  assert.equal(result.y, MAIN.y - ALERT.height - GAP);
  console.log("  no panel -> unchanged 'above' preference: PASS");
}

function testControlAboveStillClears() {
  // The one case the old code handled: alerts sit above the panel, not on it.
  const control = controlOn("above");
  const result = place({ control });
  const r = rectOf(result);
  assert.equal(intersects(r, control), false);
  assert.ok(r.y + r.height <= control.y, "alert must sit above the panel");
  console.log("  panel above -> alert clears it (regression guard): PASS");
}

function testAutoAvoidsPanelOnEverySide() {
  for (const side of ALERT_SIDES) {
    const control = controlOn(side);
    const result = place({ control });
    const r = rectOf(result);
    assert.equal(
      intersects(r, control), false,
      `auto placed the alert on top of a panel sitting ${side}`,
    );
  }
  console.log("  auto avoids the panel on all four sides: PASS");
}

function testExplicitAnchorIsNudgedClear() {
  // The user pinned alerts to a side; honour the side but clear the panel.
  for (const side of ALERT_SIDES) {
    const control = controlOn(side);
    const result = place({ anchor: side, control });
    const r = rectOf(result);
    assert.equal(result.side, side, "explicit anchor must be preserved");
    assert.equal(
      intersects(r, control), false,
      `explicit '${side}' still overlapped the panel`,
    );
  }
  console.log("  explicit anchor kept, nudged clear of the panel: PASS");
}

function testHiddenPanelChangesNothing() {
  const withPanel = place({ control: null });
  const same = place({ control: null });
  assert.deepEqual(withPanel, same);
  console.log("  hidden panel is a no-op: PASS");
}

function testTallPanelFallsBackWithoutOverlap() {
  // A panel that leaves no clear room on its own side must not trap the alert
  // underneath it -- auto has to pick a different side.
  const control = { x: MAIN.x - 40, y: 0, width: 420, height: MAIN.y + MAIN.height };
  const r = rectOf(place({ control }));
  assert.equal(intersects(r, control), false);
  console.log("  no room above -> auto picks a clear side: PASS");
}

function testIntersectsHelper() {
  const a = { x: 0, y: 0, width: 10, height: 10 };
  assert.equal(intersects(a, { x: 10, y: 0, width: 10, height: 10 }), false);
  assert.equal(intersects(a, { x: 9, y: 9, width: 10, height: 10 }), true);
  assert.equal(intersects(a, null), false);
  console.log("  intersects helper: PASS");
}

function main() {
  console.log("alert placement:");
  testIntersectsHelper();
  testNoControlKeepsHistoricPreference();
  testHiddenPanelChangesNothing();
  testControlAboveStillClears();
  testAutoAvoidsPanelOnEverySide();
  testExplicitAnchorIsNudgedClear();
  testTallPanelFallsBackWithoutOverlap();
  testStaysOnScreen();
  console.log("alert placement: ALL PASS");
}

main();
