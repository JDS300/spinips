export const EQ_LEGENDS_TOOLS_URL = "https://eqlegendstools.com/";
export const EQ_LEGENDS_CHAR_SHEET_URL = "https://eqlegendstools.com/char-sheet/";

export interface GearCatalogRecord {
  id: string;
  name: string;
  source: string;
  zone: string;
  targets: string[];
  itemUrl: string;
}

export interface ImportedBuild {
  name: string;
  classes: string[];
  exportedAt: string;
  equipped: Record<string, string>;
}

export interface InventoryEntry {
  location: string;
  name: string;
  placement: "equipped" | "bag" | "bank" | "owned";
}

export interface GearGoalView {
  slot: string;
  itemId: string;
  itemName: string;
  itemUrl: string;
  source: string;
  zone: string;
  targets: string[];
  ownership: "missing" | "equipped" | "bag" | "bank" | "owned";
  location: string;
}

export interface FarmingRouteView {
  zone: string;
  goalCount: number;
  itemNames: string[];
  targets: string[];
}

export interface GearPlanView {
  status: "empty" | "ready" | "error";
  detail: string;
  buildName: string;
  classes: string[];
  exportedAt: string;
  buildPath: string;
  inventoryPath: string;
  catalogUpdatedAt: string;
  goals: GearGoalView[];
  equippedGoalCount: number;
  bagUpgradeCount: number;
  ownedGoalCount: number;
  missingGoalCount: number;
  routes: FarmingRouteView[];
}

export const emptyGearPlan = (buildPath = "", inventoryPath = "", detail = "Import an EQ Legends Tools character build to begin."): GearPlanView => ({
  status: "empty",
  detail,
  buildName: "",
  classes: [],
  exportedAt: "",
  buildPath,
  inventoryPath,
  catalogUpdatedAt: "",
  goals: [],
  equippedGoalCount: 0,
  bagUpgradeCount: 0,
  ownedGoalCount: 0,
  missingGoalCount: 0,
  routes: [],
});

const compact = (value: unknown): string => String(value ?? "").replace(/\s+/g, " ").trim();
const slug = (value: string): string => compact(value).toLowerCase()
  .replace(/[’`']/g, "-")
  .replace(/[^a-z0-9]+/g, "-")
  .replace(/^-+|-+$/g, "");

export function normalizeItemName(value: string): string {
  return compact(value).replace(/[’‘]/g, "'")
    .replace(/\s*\([^)]*\)\s*$/u, "")
    .replace(/\s+\+\d+\s*$/u, "")
    .toLocaleLowerCase();
}

function titleFromItemId(itemId: string): string {
  const raw = itemId.replace(/^item:/i, "");
  return raw.split(/[-_]+/).filter(Boolean)
    .map((part) => part.length <= 2 ? part.toUpperCase() : `${part[0].toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

function itemIdForName(name: string): string {
  return `item:${slug(name)}`;
}

export function parseEqToolsBuild(text: string): ImportedBuild {
  const parsed = JSON.parse(text) as Record<string, unknown>;
  const value = ((parsed.characterSheet && typeof parsed.characterSheet === "object")
    ? parsed.characterSheet : parsed) as Record<string, unknown>;
  if (Number(value.version ?? 1) !== 1) throw new Error("Unsupported EQ Legends Tools character-sheet version");
  const source = compact(value.source);
  if (source && !/EQ Legends Tools Character Sheet/i.test(source)) {
    throw new Error("Choose a JSON file exported by EQ Legends Tools Character Sheet");
  }
  if (!value.equipped || typeof value.equipped !== "object" || Array.isArray(value.equipped)) {
    throw new Error("The character-sheet export has no equipped build");
  }
  const equipped: Record<string, string> = {};
  for (const [rawSlot, rawItem] of Object.entries(value.equipped as Record<string, unknown>).slice(0, 64)) {
    const slot = compact(rawSlot).toUpperCase().slice(0, 64);
    const item = compact(rawItem).slice(0, 256);
    if (slot && item) equipped[slot] = item;
  }
  if (Object.keys(equipped).length === 0) throw new Error("The exported build has no goal items equipped");
  const classes = Array.isArray(value.classes)
    ? value.classes.map(compact).filter(Boolean).slice(0, 3)
    : [];
  return {
    name: compact(value.name || value.characterName || "Unnamed build").slice(0, 128),
    classes,
    exportedAt: compact(value.exportedAt),
    equipped,
  };
}

const wornLocations = new Set([
  "charm", "leftear", "head", "face", "rightear", "neck", "shoulders",
  "arms", "back", "leftwrist", "rightwrist", "range", "hands", "primary",
  "secondary", "leftfinger", "rightfinger", "chest", "legs", "feet", "waist", "ammo",
]);

function inventoryPlacement(location: string): InventoryEntry["placement"] {
  const key = location.toLowerCase().replace(/[^a-z0-9]/g, "");
  if (wornLocations.has(key) || /^(worn|equipment)/i.test(location)) return "equipped";
  if (/bank|dragon'?s? hoard|shared/i.test(location)) return "bank";
  if (/general|inventory|pack|bag|cursor/i.test(location)) return "bag";
  return "owned";
}

export function parseInventory(text: string): InventoryEntry[] {
  const entries: InventoryEntry[] = [];
  let locationColumn = 0;
  let nameColumn = 1;
  let headerSeen = false;
  for (const line of text.split(/\r?\n/)) {
    if (!line.trim()) continue;
    const columns = line.split("\t");
    if (!headerSeen) {
      const lowered = columns.map((column) => compact(column).toLowerCase());
      if (lowered.includes("name")) {
        nameColumn = lowered.indexOf("name");
        locationColumn = Math.max(0, lowered.indexOf("location"));
        headerSeen = true;
        continue;
      }
      headerSeen = true;
    }
    const name = compact(columns[nameColumn]);
    const location = compact(columns[locationColumn]);
    if (!name || name.toLowerCase() === "empty") continue;
    entries.push({ location, name, placement: inventoryPlacement(location) });
  }
  return entries;
}

function sourceParts(sourceValue: unknown, dropsValue: unknown, questsValue: unknown): {
  source: string; zone: string; targets: string[];
} {
  const drops = Array.isArray(dropsValue) ? dropsValue as Array<Record<string, unknown>> : [];
  if (drops.length) {
    const zone = compact(drops[0].location || drops[0].zone || "Unknown zone");
    const targets = [...new Set(drops.map((entry) => compact(entry.npc || entry.mob)).filter(Boolean))];
    return { source: `Drops From: ${zone}${targets.length ? `: ${targets.join(", ")}` : ""}`, zone, targets };
  }
  const source = compact(sourceValue);
  const quests = Array.isArray(questsValue) ? questsValue.map(compact).filter(Boolean) : [];
  if (quests.length || /quest/i.test(source)) {
    return { source: source || `Reward from Quest: ${quests.join(", ")}`, zone: "Quest Rewards", targets: quests };
  }
  const cleaned = source.replace(/^Drops From:\s*/i, "");
  const colon = cleaned.indexOf(":");
  if (colon > 0) {
    const zone = compact(cleaned.slice(0, colon));
    const targets = cleaned.slice(colon + 1).split(/\s*,\s*/).map(compact).filter(Boolean);
    return { source, zone, targets };
  }
  return { source: source || "Source available on EQ Legends Tools", zone: source || "Other Sources", targets: [] };
}

export function catalogFromEqToolsData(value: unknown): GearCatalogRecord[] {
  if (!value || typeof value !== "object") throw new Error("EQ Legends Tools returned invalid catalog data");
  const payload = value as Record<string, unknown>;
  const records = new Map<string, GearCatalogRecord>();
  const add = (nameValue: unknown, sourceValue: unknown, dropsValue?: unknown, questsValue?: unknown) => {
    const name = compact(nameValue);
    if (!name) return;
    const id = itemIdForName(name);
    const parts = sourceParts(sourceValue, dropsValue, questsValue);
    const existing = records.get(id);
    if (existing) {
      existing.targets = [...new Set([...existing.targets, ...parts.targets])];
      if (!existing.source && parts.source) existing.source = parts.source;
      return;
    }
    records.set(id, {
      id, name, ...parts,
      itemUrl: `${EQ_LEGENDS_TOOLS_URL}items/${slug(name)}/`,
    });
  };
  const gear = Array.isArray(payload.gear) ? payload.gear as Array<Record<string, unknown>> : [];
  for (const item of gear) add(item.name || item.itemName, item.source, item.dropsFrom, item.rewardFromQuests);
  const weapons = Array.isArray(payload.weapons) ? payload.weapons as Array<Record<string, unknown>> : [];
  for (const item of weapons) add(item.weaponName || item.itemName, item.source, item.dropsFromEntries, item.questRewardEntries);
  return [...records.values()];
}

export function buildGearPlan(build: ImportedBuild, inventory: InventoryEntry[], catalog: GearCatalogRecord[], options: {
  buildPath?: string; inventoryPath?: string; catalogUpdatedAt?: string;
} = {}): GearPlanView {
  const byId = new Map(catalog.map((item) => [item.id, item]));
  const inventoryByName = new Map<string, InventoryEntry[]>();
  for (const entry of inventory) {
    const key = normalizeItemName(entry.name);
    inventoryByName.set(key, [...(inventoryByName.get(key) ?? []), entry]);
  }
  const placementRank = { equipped: 0, bag: 1, owned: 2, bank: 3 } as const;
  const goals = Object.entries(build.equipped).map(([slot, rawId]): GearGoalView => {
    const id = rawId.startsWith("item:") ? rawId : itemIdForName(rawId);
    const catalogItem = byId.get(id);
    const itemName = catalogItem?.name || (rawId.startsWith("item:") ? titleFromItemId(rawId) : rawId);
    const matches = [...(inventoryByName.get(normalizeItemName(itemName)) ?? [])]
      .sort((left, right) => placementRank[left.placement] - placementRank[right.placement]);
    const owned = matches[0];
    return {
      slot, itemId: id, itemName,
      itemUrl: catalogItem?.itemUrl || `${EQ_LEGENDS_TOOLS_URL}items/${id.replace(/^item:/, "")}/`,
      source: catalogItem?.source || "Open the EQ Legends Tools item page for its current source.",
      zone: catalogItem?.zone || "Source lookup needed",
      targets: catalogItem?.targets ?? [],
      ownership: owned?.placement ?? "missing",
      location: owned?.location ?? "",
    };
  });
  const missing = goals.filter((goal) => goal.ownership === "missing");
  const routeMap = new Map<string, { itemNames: Set<string>; targets: Set<string> }>();
  for (const goal of missing) {
    const zone = goal.zone || "Other Sources";
    const route = routeMap.get(zone) ?? { itemNames: new Set(), targets: new Set() };
    route.itemNames.add(goal.itemName);
    goal.targets.forEach((target) => route.targets.add(target));
    routeMap.set(zone, route);
  }
  const routes = [...routeMap.entries()].map(([zone, route]): FarmingRouteView => ({
    zone,
    goalCount: route.itemNames.size,
    itemNames: [...route.itemNames].sort(),
    targets: [...route.targets].sort(),
  })).sort((left, right) => right.goalCount - left.goalCount || left.zone.localeCompare(right.zone));
  return {
    status: "ready",
    detail: inventory.length
      ? `${goals.length} build goals matched against ${inventory.length} inventory rows.`
      : `${goals.length} build goals loaded. Import inventory.txt to identify owned upgrades.`,
    buildName: build.name,
    classes: build.classes,
    exportedAt: build.exportedAt,
    buildPath: options.buildPath ?? "",
    inventoryPath: options.inventoryPath ?? "",
    catalogUpdatedAt: options.catalogUpdatedAt ?? "",
    goals,
    equippedGoalCount: goals.filter((goal) => goal.ownership === "equipped").length,
    bagUpgradeCount: goals.filter((goal) => goal.ownership === "bag").length,
    ownedGoalCount: goals.filter((goal) => goal.ownership !== "missing").length,
    missingGoalCount: missing.length,
    routes,
  };
}
