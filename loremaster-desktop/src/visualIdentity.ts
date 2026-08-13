import type { CSSProperties } from "react";
import type { CombatAbilityCategory } from "./protocol";

type IdentityStyle = CSSProperties & {
  "--identity-color": string;
  "--identity-soft": string;
};

// A broad, dark-surface-safe palette keeps a full group visually distinct far
// more often than the original seven-color set. The hash remains deterministic,
// so a player keeps the same identity in Seed, HUD, and Combat Archive without
// storing presentation state.
const actorPalette = [
  ["#64c7f2", "rgba(100,199,242,.16)"],
  ["#f2ad3d", "rgba(242,173,61,.16)"],
  ["#39c79b", "rgba(57,199,155,.16)"],
  ["#f2df66", "rgba(242,223,102,.15)"],
  ["#7b9cff", "rgba(123,156,255,.17)"],
  ["#f07845", "rgba(240,120,69,.16)"],
  ["#dc82c9", "rgba(220,130,201,.16)"],
  ["#b49af5", "rgba(180,154,245,.16)"],
  ["#79d4c7", "rgba(121,212,199,.16)"],
  ["#e7c07a", "rgba(231,192,122,.16)"],
  ["#ef8e9d", "rgba(239,142,157,.16)"],
  ["#91ca68", "rgba(145,202,104,.16)"],
  ["#82b9f4", "rgba(130,185,244,.16)"],
  ["#d99a5e", "rgba(217,154,94,.16)"],
  ["#a8d86e", "rgba(168,216,110,.16)"],
  ["#ef91d2", "rgba(239,145,210,.16)"],
  ["#72d0ee", "rgba(114,208,238,.16)"],
  ["#c8a7ef", "rgba(200,167,239,.16)"],
  ["#f1ca5c", "rgba(241,202,92,.16)"],
  ["#63cfa5", "rgba(99,207,165,.16)"],
  ["#ff9871", "rgba(255,152,113,.16)"],
  ["#9baef8", "rgba(155,174,248,.16)"],
  ["#d6d86d", "rgba(214,216,109,.16)"],
  ["#dc91b8", "rgba(220,145,184,.16)"],
] as const;

const categoryColors: Record<CombatAbilityCategory, readonly [string, string]> = {
  melee: ["#f2ad3d", "rgba(242,173,61,.15)"],
  spell: ["#64c7f2", "rgba(100,199,242,.15)"],
  dot: ["#c889ef", "rgba(200,137,239,.15)"],
  proc: ["#f2df66", "rgba(242,223,102,.14)"],
  damage_shield: ["#f07845", "rgba(240,120,69,.15)"],
  pet: ["#dc82c9", "rgba(220,130,201,.15)"],
  healing: ["#39c79b", "rgba(57,199,155,.15)"],
  unknown: ["#8ea3b1", "rgba(142,163,177,.12)"],
};

function stableHash(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function styleFor(colors: readonly [string, string]): IdentityStyle {
  return { "--identity-color": colors[0], "--identity-soft": colors[1] };
}

export function actorIdentityStyle(name: string): IdentityStyle {
  const normalized = name.trim().toLocaleLowerCase() || "unknown";
  return styleFor(actorPalette[stableHash(normalized) % actorPalette.length]);
}

export function normalizeAbilityCategory(value: unknown, name = ""): CombatAbilityCategory {
  const normalized = String(value ?? "").toLocaleLowerCase().replace(/[\s-]+/g, "_");
  if (["melee", "physical", "weapon"].includes(normalized)) return "melee";
  if (["spell", "nuke", "direct_spell", "direct_damage", "magic"].includes(normalized)) return "spell";
  if (["dot", "damage_over_time"].includes(normalized)) return "dot";
  if (["proc", "weapon_proc"].includes(normalized)) return "proc";
  if (["damage_shield", "ds", "reflect"].includes(normalized)) return "damage_shield";
  if (["pet", "charmed", "summoned"].includes(normalized)) return "pet";
  if (["healing", "heal", "hot"].includes(normalized)) return "healing";

  // Older protocol snapshots do not carry a category. Keep this deliberately
  // conservative: only unmistakable source labels are classified locally.
  const label = name.toLocaleLowerCase();
  if (/damage shield|\bds\b/.test(label)) return "damage_shield";
  if (/\bproc\b/.test(label)) return "proc";
  if (/\b(dot|damage over time)\b/.test(label)) return "dot";
  if (/\b(heal|healing|regeneration)\b/.test(label)) return "healing";
  if (/^(melee|slash|slashing|crush|crushing|pierce|piercing|bash|kick|backstab|archery|ranged)$/i.test(name.trim())) return "melee";
  return "unknown";
}

export function abilityIdentityStyle(category: CombatAbilityCategory): IdentityStyle {
  return styleFor(categoryColors[category] ?? categoryColors.unknown);
}

export function abilityCategoryLabel(category: CombatAbilityCategory): string {
  if (category === "damage_shield") return "DAMAGE SHIELD";
  return category.toUpperCase().replaceAll("_", " ");
}
