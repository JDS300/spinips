"use strict";

const assert = require("node:assert/strict");
const {
  buildGearPlan,
  catalogFromEqToolsData,
  parseEqToolsBuild,
  parseInventory,
} = require("../dist-electron/gear-plan.js");

const build = parseEqToolsBuild(JSON.stringify({
  version: 1,
  source: "EQ Legends Tools Character Sheet",
  name: "Spin",
  classes: ["Paladin", "Monk", "Enchanter"],
  equipped: {
    HEAD: "item:ethereal-mist-helm",
    SHOULDERS: "item:refugee-shroud",
  },
}));

const inventory = parseInventory([
  "Location\tName\tID\tCount\tSlots",
  "Head\tEthereal Mist Helm\t1\t1\tHEAD",
  "General1-Slot2\tRefugee Shroud +3\t2\t1\tSHOULDERS",
].join("\n"));

const catalog = catalogFromEqToolsData({
  gear: [
    { name: "Ethereal Mist Helm", source: "Drops From: Plane of Fear: various mobs", dropsFrom: [{ location: "Plane of Fear", npc: "various mobs" }] },
    { name: "Refugee Shroud", source: "Drops From: Blackburrow: Refugee Splitpaw", dropsFrom: [{ location: "Blackburrow", npc: "Refugee Splitpaw" }] },
  ],
  weapons: [],
});

const plan = buildGearPlan(build, inventory, catalog);
assert.equal(plan.status, "ready");
assert.equal(plan.equippedGoalCount, 1);
assert.equal(plan.bagUpgradeCount, 1);
assert.equal(plan.missingGoalCount, 0);
assert.equal(plan.goals.find((goal) => goal.slot === "SHOULDERS").ownership, "bag");
assert.equal(plan.goals.find((goal) => goal.slot === "HEAD").zone, "Plane of Fear");

const missingPlan = buildGearPlan(build, [], catalog);
assert.equal(missingPlan.missingGoalCount, 2);
assert.equal(missingPlan.routes[0].goalCount, 1);
assert.ok(missingPlan.routes.some((route) => route.zone === "Blackburrow"));

console.log("Gear plan import audit: ALL PASS");
