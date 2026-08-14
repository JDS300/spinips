import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, renameSync, statSync, unlinkSync, writeFileSync } from "node:fs";
import path from "node:path";

const EQL_WIKI_ORIGIN = "https://eqlwiki.com";
const CACHE_TTL_MS = 7 * 24 * 60 * 60 * 1000;
const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;
const MAX_CACHE_BYTES = 512 * 1024;
const MAX_QUERY_LENGTH = 160;
const CACHE_SCHEMA_VERSION = 1;
const MAX_CONCURRENT_REQUESTS = 4;

const sectionParameters: Readonly<Record<string, string>> = {
  dropsfrom: "Drops From",
  soldby: "Sold by",
  relatedquests: "Related quests",
  quests: "Related quests",
  playercrafted: "Player crafted",
  tradeskillrecipes: "Tradeskill recipes",
  recipes: "Tradeskill recipes",
};

const profileLabels: Readonly<Record<string, string>> = {
  merchantvalue: "Merchant value",
  focuseffect: "Focus Effect",
  worneffect: "Worn Effect",
  clickeffect: "Click Effect",
  proceffect: "Proc Effect",
};

export interface ItemLookupView {
  status: "ready" | "not-found" | "offline" | "error";
  requestedName: string;
  title: string;
  url: string;
  stats: string[];
  notes: string[];
  sections: Record<string, string[]>;
  freshness: "live" | "cached" | "stale";
  detail: string;
}

interface CachedItem extends Omit<ItemLookupView, "status" | "requestedName" | "freshness" | "detail"> {
  fetchedAt: number;
}

interface CacheEnvelope {
  schemaVersion: number;
  item: CachedItem;
}

function stringRows(value: unknown, limit: number): string[] {
  if (!Array.isArray(value)) return [];
  return value.slice(0, limit).map((row) => String(row).slice(0, 4_000));
}

function sanitizeCachedItem(value: unknown): CachedItem | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Partial<CachedItem>;
  const title = normalizeItemName(String(raw.title ?? ""));
  if (title.length < 2 || !Number.isFinite(raw.fetchedAt)) return null;
  let url = wikiUrl(title);
  try {
    const candidate = new URL(String(raw.url ?? ""));
    if (candidate.protocol === "https:" && ["eqlwiki.com", "www.eqlwiki.com"].includes(candidate.hostname)) {
      url = candidate.toString();
    }
  } catch { /* a canonical EQL Wiki URL is supplied below */ }
  const sections: Record<string, string[]> = {};
  if (raw.sections && typeof raw.sections === "object" && !Array.isArray(raw.sections)) {
    for (const [heading, rows] of Object.entries(raw.sections).slice(0, 16)) {
      const cleaned = stringRows(rows, 24);
      if (cleaned.length) sections[String(heading).slice(0, 120)] = cleaned;
    }
  }
  return {
    title,
    url,
    stats: stringRows(raw.stats, 48),
    notes: stringRows(raw.notes, 24),
    sections,
    fetchedAt: Number(raw.fetchedAt),
  };
}

export async function readLimitedResponse(response: Response): Promise<string> {
  if (!response.body) {
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (bytes.byteLength > MAX_RESPONSE_BYTES) throw new Error("EQL Wiki response exceeded the 2 MB safety limit");
    return new TextDecoder().decode(bytes);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let total = 0;
  let text = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > MAX_RESPONSE_BYTES) {
      await reader.cancel("response-size-limit");
      throw new Error("EQL Wiki response exceeded the 2 MB safety limit");
    }
    text += decoder.decode(value, { stream: true });
  }
  return text + decoder.decode();
}

function emptyLookup(
  requestedName: string,
  status: ItemLookupView["status"],
  detail: string,
): ItemLookupView {
  return {
    status,
    requestedName,
    title: requestedName,
    url: wikiUrl(requestedName),
    stats: [],
    notes: [],
    sections: {},
    freshness: "live",
    detail,
  };
}

export function normalizeItemName(value: string): string {
  return String(value ?? "")
    .replace(/[\u0000-\u001f\u007f]/g, " ")
    .replace(/\s+\+[0-9]+\s*$/, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, MAX_QUERY_LENGTH);
}

function wikiUrl(value: string): string {
  const slug = encodeURIComponent(normalizeItemName(value).replace(/\s+/g, "_"))
    .replaceAll("%3A", ":")
    .replaceAll("%27", "'")
    .replaceAll("%28", "(")
    .replaceAll("%29", ")");
  return `${EQL_WIKI_ORIGIN}/${slug}`;
}

function decodeEntities(value: string): string {
  const named: Readonly<Record<string, string>> = {
    amp: "&", lt: "<", gt: ">", quot: "\"", apos: "'", nbsp: " ",
  };
  return value.replace(/&(#x[0-9a-f]+|#[0-9]+|[a-z]+);/gi, (match, entity: string) => {
    if (entity[0] === "#") {
      const hex = entity[1]?.toLowerCase() === "x";
      const parsed = Number.parseInt(entity.slice(hex ? 2 : 1), hex ? 16 : 10);
      return Number.isFinite(parsed) && parsed > 0 && parsed <= 0x10ffff
        ? String.fromCodePoint(parsed)
        : match;
    }
    return named[entity.toLowerCase()] ?? match;
  });
}

function cleanWikiText(input: string, limit = 4_000): string[] {
  let value = String(input ?? "").replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, " ");
  value = value.slice(0, Math.max(limit * 8, 32_000));
  value = value
    .replace(/<(?:script|style)\b[^>]*>[\s\S]*?<\/(?:script|style)\s*>/gi, "")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<!--[\s\S]*?-->/g, "")
    .replace(/\[\[(?:[^\]|]+\|)?([^\]]+)\]\]/g, "$1")
    .replace(/\[(?:https?:\/\/\S+)\s+([^\]]+)\]/g, "$1")
    .replace(/\[(?:https?:\/\/[^\]]+)\]/g, "");
  for (let pass = 0; pass < 100; pass += 1) {
    const next = value.replace(/\{\{[^{}]*\}\}/g, "");
    if (next === value) break;
    value = next;
  }
  value = decodeEntities(value.replace(/<[^>]+>/g, "").replace(/'''?/g, ""));
  const rows: string[] = [];
  let consumed = 0;
  for (const rawLine of value.split(/\r?\n/)) {
    let line = rawLine.trim();
    if (!line) continue;
    let depth = 0;
    const marker = line.match(/^([*#:;]+)\s*(.*)$/);
    if (marker) {
      depth = Math.max(1, marker[1].replaceAll(":", "").length);
      line = marker[2].trim();
    }
    line = line.replace(/\s+/g, " ").replace(/^[\s-]+|[\s-]+$/g, "");
    if (!line) continue;
    if (depth) line = `${"  ".repeat(depth - 1)}\u2022 ${line}`;
    const remaining = Math.max(0, limit - consumed);
    if (!remaining) break;
    line = line.slice(0, remaining);
    rows.push(line);
    consumed += line.length;
  }
  return rows;
}

function templateParameters(wikiText: string): Record<string, string> {
  const parameters: Record<string, string[]> = {};
  let current = "";
  let inItem = false;
  for (let line of String(wikiText ?? "").split(/\r?\n/)) {
    if (!inItem) {
      const match = line.match(/\{\{\s*Itempage\b/i);
      if (!match || match.index === undefined) continue;
      inItem = true;
      line = line.slice(match.index + match[0].length);
    }
    if (/^\s*\}\}\s*(?:<\/onlyinclude>)?\s*$/i.test(line)) break;
    const parameter = line.match(/^\s*\|\s*([A-Za-z0-9_ ]+)\s*=\s*(.*)$/);
    if (parameter) {
      current = parameter[1].toLowerCase().replace(/[^a-z0-9]/g, "");
      parameters[current] = [parameter[2]];
    } else if (current) {
      parameters[current].push(line);
    }
  }
  return Object.fromEntries(Object.entries(parameters).map(([key, lines]) => [key, lines.join("\n").trim()]));
}

export function parseItemPayload(payload: unknown, requestedName: string): CachedItem | null {
  if (!payload || typeof payload !== "object") return null;
  const parsed = (payload as { parse?: unknown }).parse;
  if (!parsed || typeof parsed !== "object") return null;
  const record = parsed as { title?: unknown; wikitext?: unknown };
  const rawWikiText = typeof record.wikitext === "object" && record.wikitext !== null
    ? String((record.wikitext as { "*"?: unknown })["*"] ?? "")
    : String(record.wikitext ?? "");
  const parameters = templateParameters(rawWikiText);
  if (!parameters.itemname && !parameters.statsblock) return null;
  const title = normalizeItemName(parameters.itemname || String(record.title ?? requestedName));
  if (!title) return null;
  const sections: Record<string, string[]> = {};
  for (const [parameter, section] of Object.entries(sectionParameters)) {
    if (!parameters[parameter]) continue;
    const rows = cleanWikiText(parameters[parameter]);
    if (rows.length) sections[section] = [...(sections[section] ?? []), ...rows];
  }
  const stats = cleanWikiText(parameters.statsblock ?? "", 2_600);
  const structural = new Set(["itemname", "lucyimgid", "statsblock", "notes", ...Object.keys(sectionParameters)]);
  for (const [key, value] of Object.entries(parameters)) {
    if (structural.has(key) || !value.trim()) continue;
    const rows = cleanWikiText(value, 800);
    if (!rows.length) continue;
    const label = profileLabels[key] ?? key.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
    stats.push(`${label}: ${rows[0]}`, ...rows.slice(1).map((row) => `  ${row}`));
    if (stats.length >= 40) break;
  }
  return {
    title,
    url: wikiUrl(title),
    stats: stats.slice(0, 40),
    notes: cleanWikiText(parameters.notes ?? "", 1_200),
    sections,
    fetchedAt: Date.now(),
  };
}

export class ItemIntelligenceService {
  private readonly cacheDirectory: string;
  private readonly inflight = new Map<string, Promise<ItemLookupView>>();
  private activeFetches = 0;

  constructor(userDataDirectory: string) {
    this.cacheDirectory = path.join(userDataDirectory, "item-intelligence");
  }

  private cachePath(name: string): string {
    const key = createHash("sha256").update(normalizeItemName(name).toLowerCase(), "utf8").digest("hex").slice(0, 32);
    return path.join(this.cacheDirectory, `${key}.json`);
  }

  private readCache(name: string): CachedItem | null {
    try {
      const target = this.cachePath(name);
      if (statSync(target).size > MAX_CACHE_BYTES) return null;
      const decoded = JSON.parse(readFileSync(target, "utf8")) as CacheEnvelope | CachedItem;
      if (decoded && typeof decoded === "object" && "item" in decoded
          && decoded.schemaVersion !== CACHE_SCHEMA_VERSION) return null;
      const value = "item" in decoded ? decoded.item : decoded;
      return sanitizeCachedItem(value);
    } catch {
      return null;
    }
  }

  private writeCache(name: string, item: CachedItem): void {
    mkdirSync(this.cacheDirectory, { recursive: true });
    const target = this.cachePath(name);
    const temporary = `${target}.${process.pid}.tmp`;
    try {
      const payload: CacheEnvelope = { schemaVersion: CACHE_SCHEMA_VERSION, item };
      writeFileSync(temporary, JSON.stringify(payload), "utf8");
      renameSync(temporary, target);
    } finally {
      try { unlinkSync(temporary); } catch { /* atomic rename already consumed it */ }
    }
  }

  private ready(name: string, item: CachedItem, freshness: ItemLookupView["freshness"]): ItemLookupView {
    return {
      status: "ready",
      requestedName: name,
      title: item.title,
      url: item.url,
      stats: item.stats,
      notes: item.notes,
      sections: item.sections,
      freshness,
      detail: freshness === "live" ? "Validated against EQL Wiki just now."
        : freshness === "cached" ? "Loaded instantly from Loremaster's local EQL Wiki cache."
          : "EQL Wiki is offline; showing the most recent cached profile.",
    };
  }

  lookup(rawName: string, networkEnabled = true): Promise<ItemLookupView> {
    const name = normalizeItemName(rawName);
    if (name.length < 2) return Promise.resolve(emptyLookup(name, "not-found", "Select a valid item name."));
    const cache = this.readCache(name);
    if (cache && Date.now() - cache.fetchedAt <= CACHE_TTL_MS) {
      return Promise.resolve(this.ready(name, cache, "cached"));
    }
    if (!networkEnabled) {
      return Promise.resolve(cache
        ? this.ready(name, cache, "stale")
        : emptyLookup(name, "offline", "Network item lookups are disabled. Enable them in Settings or open EQL Wiki manually."));
    }
    const key = name.toLowerCase();
    const existing = this.inflight.get(key);
    if (existing) return existing;
    if (this.activeFetches >= MAX_CONCURRENT_REQUESTS) {
      return Promise.resolve(emptyLookup(
        name, "error", "Too many item lookups are already active. Select the item again in a moment."));
    }
    // Only duplicate item requests are coalesced. Independent selections are
    // allowed to resolve concurrently so one offline page cannot hold every
    // subsequent click behind its full timeout.
    this.activeFetches += 1;
    const request = this.fetchItem(name, cache).finally(() => {
      this.activeFetches = Math.max(0, this.activeFetches - 1);
    });
    this.inflight.set(key, request);
    void request.finally(() => this.inflight.delete(key));
    return request;
  }

  private async fetchItem(name: string, stale: CachedItem | null): Promise<ItemLookupView> {
    const query = new URLSearchParams({
      action: "parse",
      format: "json",
      page: name,
      prop: "wikitext|sections",
      redirects: "1",
    });
    try {
      const response = await fetch(`${EQL_WIKI_ORIGIN}/api.php?${query}`, {
        headers: {
          Accept: "application/json",
          "User-Agent": "Spins-Loremaster/2.0 (https://github.com/itsspin/spinips)",
        },
        signal: AbortSignal.timeout(8_000),
      });
      if (!response.ok) throw new Error(`EQL Wiki returned HTTP ${response.status}`);
      const contentLength = Number(response.headers.get("content-length") ?? 0);
      if (contentLength > MAX_RESPONSE_BYTES) throw new Error("EQL Wiki response exceeded the 2 MB safety limit");
      const text = await readLimitedResponse(response);
      const item = parseItemPayload(JSON.parse(text), name);
      if (!item) return emptyLookup(name, "not-found", `No exact EQL Wiki item page was found for “${name}”.`);
      try { this.writeCache(name, item); } catch { /* read-only data directories must not hide a valid response */ }
      return this.ready(name, item, "live");
    } catch (error) {
      if (stale) return this.ready(name, stale, "stale");
      const detail = error instanceof Error ? error.message : String(error);
      const offline = /fetch|network|timeout|abort|ENOTFOUND|HTTP 5\d\d/i.test(detail);
      return emptyLookup(name, offline ? "offline" : "error", offline
        ? "EQL Wiki is unavailable and this item is not cached yet."
        : `Item lookup failed: ${detail}`);
    }
  }
}
