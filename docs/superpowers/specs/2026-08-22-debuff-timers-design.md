# Debuff timers: DoT, slow, and resist tracking

Date: 2026-08-22
Status: approved design, not yet implemented

## Problem

Loremaster tracks mez and lull as live countdowns on a control deck. It does
not track anything else on a mob. Dropping a slow on a raid target is as
costly as dropping a mez, and there is no surface for it.

The premise that this is already configurable is not quite right. The one
hand-editable hook is `custom_alerts` in `loremaster_config.json`
(`loremaster/loremaster.py:2466`, documented at `README.md:448`), which fires a
one-shot text banner on a regex match. It carries no target and no duration, so
it cannot express a timer. It is also Tk-only: `set_alert_config()`
(`loremaster/desktop_worker.py:211`) whitelists fourteen camelCase keys and
`custom_alerts` is not among them, so the Electron app never receives it.

Today's coverage of the three families:

- **DoTs** are parsed for damage attribution only, via `dot_out`
  (`loremaster.py:712`), `dot_in`, and `dot_third`. No duration data exists.
- **Slow** and **resist debuffs** are not parsed at all. A sweep for
  `slow|cripple|tashan|malos|weaken|snare|root` across `loremaster/*.py`
  returns only Tk `root` windows, the X11 root window, and an item-tooltip
  "haste" keyword.

## Scope

In scope: a built-in spell table with per-kind UI toggles, covering DoTs, slow,
and resist debuffs, rendered as a separate mob-grouped deck in the Electron
desktop app.

Out of scope, deliberately:

- **Snare and root.** Considered and dropped.
- **A user-definable trigger schema.** Rejected in favour of a curated table:
  correct on first run, and it keeps the rank-scaling and cast-correlation
  logic that makes mez accurate.
- **The Tk overlay.** `MezTimerOverlay` gains nothing. The engine is shared, so
  the Tk app still tracks debuffs internally; it just renders no deck. Adding
  one later needs no rework, since the tracker and snapshot are shared.
- **Sha's Advantage (BST 60)** and everything above level 50.

### Class coverage

| Family | Classes |
|---|---|
| Slow | Shaman, Enchanter, Beastlord |
| Resist | Shaman, Enchanter |
| DoT | Shaman, Enchanter, Beastlord, Necromancer, Druid |

## Spell data

Landing prose and durations come from Allakhazam's classic spell database.
Landing families found:

| Family | Landing line | Spells (to L50) |
|---|---|---|
| slow, yawns | `Soandso yawns.` | Drowsy (SHM 5 / BST 20), Walking Sleep (SHM 13), Tagar's Insects (SHM 27), Togor's Insects (SHM 38) |
| slow, slows down | `Soandso slows down.` | Languid Pace (ENC 9), Tepid Deeds (ENC 23), Shiftless Deeds (ENC 41) |
| slow, lethargic | `Soandso feels lethargic.` | Sha's Lethargy (BST 50) |
| resist, multi | `Soandso looks somewhat uncomfortable.` | Malaise (SHM 18), Malaisement (SHM 32), Malosi (SHM 48) |
| resist, magic | `Soandso glances nervously about.` | Tashina (ENC 2), Tashani (ENC 18), Tashania (ENC 41) |

DoTs need no landing family. `dot_out` names target and spell on every tick,
which is stronger attribution than any landing line provides.

### Durations

Duration is a function of caster level, which the app already parses from the
log (`("level", ...Welcome to level (?P<level>\d+))`). Allakhazam publishes no
formula field, but it prints duration at minimum and maximum level, and those
two points are linear in level:

| Spell | Published | Ticks | Formula |
|---|---|---|---|
| Drowsy | 3 ticks @L5, 3.5 min @L70 | 3 to 35 | `level/2`, cap 35 |
| Tagar's Insects | 1.4 min @L27, 3.5 min @L70 | 14 to 35 | `level/2`, cap 35 |
| Togor's Insects | 1.9 min @L38, 3.5 min @L70 | 19 to 35 | `level/2`, cap 35 |
| Tepid Deeds | 1.2 min @L23, 3.5 min @L70 | 12 to 35 | `level/2`, cap 35 |
| Sha's Lethargy | 2.5 min @L50, 3.5 min @L70 | 25 to 35 | `level/2`, cap 35 |
| Malaise | 4.6 min @L18, 14.0 min @L65 | 46 to 140 | `2*level + 10` |
| Tashani | 4.6 min @L18, 14.0 min @L65 | 46 to 140 | `2*level + 10` |

Every slow in the game is `level // 2` ticks capped at 35, across three prose
families and three classes. Both resist lines share `2*level + 10`.

Rank composes on top. `scaled_duration_ticks` (`mez_timer.py:246`) applies
10% per rank half-up, and `_split_rank` reads the rank off the spell name in
the log. Debuffs reuse both:

    ticks = scaled_duration_ticks(min(formula(level), cap), rank)

The cap is a level cap and is applied to the level-derived base, before rank
scaling.

## Module

New `loremaster/debuff_timer.py`, Tk-free, mirroring `lull_timer.py`.

    @dataclass(frozen=True)
    class DebuffSpell:
        name: str
        kind: str                    # "dot" | "slow" | "resist"
        duration_formula: str        # "level_half" | "level_x2_plus10"
        duration_cap_ticks: int
        landing_family: str | None   # None for DoTs
        published_endpoints: tuple[tuple[int, int], ...]  # (level, ticks)
        aliases: tuple[str, ...] = ()

Fields mirror `MezSpell` (`mez_timer.py:32`) plus the `duration_formula` and
`duration_cap_ticks` already used by the lull table.

One `DebuffTracker` with two internal paths sharing a single pending-cast
mechanism. They differ only in what evidence resolves the target.

**DoT path.** `cast_begin` pends the spell with no target. The first `dot_out`
tick names target and spell together, resolving the pending cast and starting
the countdown from cast time. Later ticks confirm liveness.

**Slow and resist path.** Mez semantics. `cast_begin` pends; a landing line
resolves against pending casts compatible with that family, through a
`DEBUFF_LANDING_COMPATIBILITY` map mirroring `mez_timer.py:894`.

That map is load-bearing. Four shaman and beastlord slows share `yawns` and
their durations differ by more than twenty ticks, so correlating to the right
pending cast is what makes the countdown correct rather than merely plausible.

**Shared lifecycle.** A timer ends on `spell_fade` (which names spell and
target), `spell_overwritten`, the target's death, or expiry. `resist2` cancels
the pending cast. Recasting the same spell on the same target resets the timer.

**Nearby casters.** `Soandso yawns.` is visible when another shaman slows
something. Mez's rule carries over: accept a landing only while a compatible
local cast is pending.

**Snapshot.** Grouped by target, spells sorted by remaining time.

## Focus effects

Focus items extend duration and are not modelled anywhere in the app today,
for mez or lull either. There is no equipped-gear model to read one from. The
two paths degrade differently:

- **DoTs self-correct.** The tick heartbeat is ground truth. If ticks arrive
  past the computed expiry, focus extended it, and the tracker holds the row
  alive while ticks continue rather than expiring on the estimate.
- **Slow and resist cannot self-correct.** No heartbeat, so a focused slow
  counts down short. These rows render as estimates and get a brief grace
  state at zero rather than vanishing.

## Protocol and UI

`ControlKind` (`loremaster-desktop/src/protocol.ts:3`) gains `"dot" | "slow" |
"resist"`, with a matching `DebuffTimerView` in `engine_protocol.py` following
the existing snake-to-camel mapping. `desktop_worker.snapshot_event()` emits a
second, target-grouped payload alongside `controls`.

The deck is a new `<section className="debuff-deck">` in `App.tsx`, below the
existing control deck, one block per mob. It reuses the urgency classes and
meter styling in `styles.css` so it reads as the same instrument.

    MEZ + LULL CONTROL
      a soul carrier   Mesmerize   0:18  ! WARN

    DEBUFFS
      an ice giant
        Turgur's Insects  0:48  OK
        Tashania          4:10  OK
        Envenomed Breath  0:12  !!
      a froglok tad
        Tagar's Insects   1:12  OK

A separate deck rather than one merged list: three DoTs on four mobs is twelve
rows, which would push mez off a deck capped at four
(`MezTimerOverlay.MAX_ROWS`, `loremaster.py:3601`) and six in the worker
snapshot. Grouping by target collapses rows per mob instead of per spell, so it
scales with raid size.

Settings gain a Debuff Timers card in `SettingsPanel` (`App.tsx:389`) beside
the crowd-control card: per-kind toggles for DoT, slow, and resist, a
warning-seconds input, and a mob-count cap. Persisted in
`desktop-settings.json` through the same `readSettings` coercion pattern, and
forwarded to the engine, which requires extending the fourteen-key
`alertConfig` whitelist in `desktop_worker.set_alert_config()`.

## Testing

- `loremaster/tests/test_debuff_timer.py` for the state machine: correlation,
  ambiguity across a shared landing family, re-application, break on death,
  nearby-caster rejection.
- **Endpoint assertion.** Each table row carries its published endpoints and a
  test asserts the formula reproduces both:

      def test_formula_matches_published_endpoints():
          for spell in DEBUFF_SPELLS:
              for level, expected_ticks in spell.published_endpoints:
                  assert duration_ticks(spell, level) == expected_ticks

  This turns scraped data into a standing assertion and is the closest thing to
  a real log fixture the repo has.
- `loremaster/tests/fixtures/debuff_sequences.json` in the style of the
  existing `control_sequences.json`: synthetic log lines in, expected timer
  states out.

## Risks

- **Landing prose is sourced from Allakhazam, not from EQ Legends logs.** The
  repo has no real log fixtures to check against. A wrong regex means a timer
  that silently never starts. Confirm each landing line against live play
  before release; the DoT path is unaffected, since it depends only on
  `dot_out`, which is already proven in production.
- **Whether `Your <spell> spell has worn off of <target>.` fires for debuffs on
  mobs is unverified.** It does not change the build, because timers count down
  from the computed duration regardless and a fade line is only a bonus early
  clear. It is why formula accuracy matters.
- **Only one spell per line has been read from Allakhazam.** Prose is assumed
  to be shared within a line, which held for every line checked (Drowsy,
  Tagar's, and Togor's all print `yawns`), but the remaining spells still need
  their pages pulled and their endpoints recorded during implementation.
- **Fork divergence.** The README states this fork "adds the platform support
  and nothing else", which stops being true. The README needs updating, and
  feature divergence makes the per-sync `electron/main.ts` hand-merge harder.
  See the upstream sync process notes.
