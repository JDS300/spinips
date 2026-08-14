const assert = require("node:assert/strict");
const { mkdtempSync, rmSync } = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const {
  ItemIntelligenceService,
  normalizeItemName,
  parseItemPayload,
  readLimitedResponse,
} = require("../dist-electron/item-intelligence.js");

assert.equal(normalizeItemName("  Cloak   of Flames +4  "), "Cloak of Flames");
assert.equal(normalizeItemName("\u0000 Guise_of_the_Deceiver "), "Guise_of_the_Deceiver");

const item = parseItemPayload({
  parse: {
    title: "Cloak of Flames",
    wikitext: {
      "*": [
        "{{Itempage",
        "|itemname = Cloak of Flames",
        "|statsblock = MAGIC ITEM<br>Slot: BACK<br>AC: 10",
        "|dropsfrom = * [[Lord Nagafen]]",
        "|relatedquests = * [[A Fiery Reward|Fiery Reward]]",
        "|clickeffect = Haste",
        "|notes = A famous cloak.",
        "}}",
      ].join("\n"),
    },
  },
}, "Cloak of Flames +4");

assert.ok(item);
assert.equal(item.title, "Cloak of Flames");
assert.equal(item.url, "https://eqlwiki.com/Cloak_of_Flames");
assert.deepEqual(item.stats.slice(0, 3), ["MAGIC ITEM", "Slot: BACK", "AC: 10"]);
assert.ok(item.stats.includes("Click Effect: Haste"));
assert.deepEqual(item.sections["Drops From"], ["• Lord Nagafen"]);
assert.deepEqual(item.sections["Related quests"], ["• Fiery Reward"]);
assert.deepEqual(item.notes, ["A famous cloak."]);
assert.equal(parseItemPayload({ error: { info: "missing" } }, "Missing Item"), null);

(async () => {
  assert.equal(await readLimitedResponse(new Response("small response")), "small response");
  const oversized = new Response(new Uint8Array(2 * 1024 * 1024 + 1));
  await assert.rejects(() => readLimitedResponse(oversized), /2 MB safety limit/);
  const cacheRoot = mkdtempSync(path.join(os.tmpdir(), "loremaster-items-"));
  try {
    const offline = await new ItemIntelligenceService(cacheRoot).lookup("Uncached Item", false);
    assert.equal(offline.status, "offline");
    assert.match(offline.detail, /disabled/i);
  } finally {
    rmSync(cacheRoot, { recursive: true, force: true });
  }
  console.log("Item intelligence parser: ALL PASS");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
