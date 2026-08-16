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


// --- regression: the alert must never cover the seed window -----------------
// A clamped rectangle always "fits" the work area, so checking fit after
// clamping is a tautology: auto then picks "above" no matter how little room
// is there, and near a screen edge that lands on top of the seed. The seed is
// the only way to reach analyze/settings and to drag the app, so covering it
// makes the application unusable.
const SEED = { width: 128, height: 74 };
const REAL_ALERT = { width: 420, height: 112 };

function placeSeed(main, overrides = {}) {
  return placeAlertWindow({
    anchor: "auto",
    main,
    alert: REAL_ALERT,
    control: null,
    workArea: WORK,
    gap: 10,
    ...overrides,
  });
}

function testNeverCoversSeedAnywhereOnScreen() {
  const xs = [WORK.x, 400, WORK.x + WORK.width - SEED.width];
  const ys = [WORK.y, 300, WORK.y + WORK.height - SEED.height];
  let checked = 0;
  for (const x of xs) {
    for (const y of ys) {
      const main = { x, y, ...SEED };
      for (const anchor of ["auto", ...ALERT_SIDES]) {
        const r = placeSeed(main, { anchor });
        const rect = { x: r.x, y: r.y, ...REAL_ALERT };
        assert.equal(
          intersects(rect, main), false,
          `alert covered the seed at (${x},${y}) with anchor ${anchor}`,
        );
        checked += 1;
      }
    }
  }
  console.log(`  never covers the seed (${checked} positions): PASS`);
}

function testSeedAtTopDoesNotChooseAbove() {
  const main = { x: 900, y: WORK.y, ...SEED };
  const r = placeSeed(main);
  assert.notEqual(r.side, "above", "no room above a seed pinned to the top edge");
  const rect = { x: r.x, y: r.y, ...REAL_ALERT };
  assert.equal(intersects(rect, main), false);
  console.log("  seed at the top edge -> auto avoids 'above': PASS");
}

function testSeedAtBottomDoesNotChooseBelow() {
  const main = { x: 900, y: WORK.y + WORK.height - SEED.height, ...SEED };
  const r = placeSeed(main);
  assert.notEqual(r.side, "below", "no room below a seed pinned to the bottom edge");
  const rect = { x: r.x, y: r.y, ...REAL_ALERT };
  assert.equal(intersects(rect, main), false);
  console.log("  seed at the bottom edge -> auto avoids 'below': PASS");
}

function testAvoidsSeedAndPanelTogether() {
  const main = { x: 900, y: WORK.y, ...SEED };
  const control = { x: main.x + main.width + 6, y: main.y, width: 300, height: 90 };
  const r = placeSeed(main, { control });
  const rect = { x: r.x, y: r.y, ...REAL_ALERT };
  assert.equal(intersects(rect, main), false, "covered the seed");
  assert.equal(intersects(rect, control), false, "covered the control panel");
  console.log("  avoids the seed and the panel at once: PASS");
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
  testSeedAtTopDoesNotChooseAbove();
  testSeedAtBottomDoesNotChooseBelow();
  testAvoidsSeedAndPanelTogether();
  testNeverCoversSeedAnywhereOnScreen();
  console.log("alert placement: ALL PASS");
}

main();
