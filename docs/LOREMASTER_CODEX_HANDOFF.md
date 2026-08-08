# Loremaster Codex handoff

## Outcome

Modernize Spin's Loremaster into a polished Windows desktop companion while
preserving its non-injecting, log-only design. Correct crowd-control tracking is
the first release gate; a TypeScript/Electron interface must not hide or regress
parser bugs.

## Current baseline

- `loremaster/loremaster.py` is the zero-dependency Python application and UI.
- `loremaster/log_ingest.py` tails logs on a background thread with bounded,
  lossless batches and nonblocking UI drains.
- `loremaster/mez_timer.py` owns mez cast/landing correlation, ranked durations,
  grouped same-name targets, wake signals, and conservative server-tick timing.
- Regression coverage lives under `loremaster/tests/`, especially the mez,
  integration, ingest, and alert suites.
- The desired minimal HUD is a restrained Rune Seed that can morph into a
  detailed combat dashboard. The established direction uses dark glass,
  ember/orange and cool-blue accents, one headline metric, and Idle, Live,
  Alert, and Stale states.

## Product priorities

### P0: mez and lull correctness

1. Treat raw logs as the source of truth. Never infer successful mez from a
   cast line alone.
2. Start timers only after a recognized local cast is correlated with a valid
   landing line.
3. Close or amend state for fizzles, interrupts, resists, overwrites, fades,
   damage breaks, deaths, zoning, character changes, and resets.
4. Preserve conservative six-second server-tick handling and honest grouping
   of indistinguishable same-name enemies.
5. Track lull with the same evidentiary rules, including ambiguity when a spell
   or client exposes no result line.
6. Keep sanitized real-log regression fixtures deterministic and UI-free.
7. Surface confidence and ambiguity instead of displaying guesses as exact.

### P1: desktop architecture and performance

Use TypeScript, React, and Electron for a new presentation layer. Migrate in
phases rather than replacing the tested parser and UI simultaneously:

1. Define versioned typed events and immutable snapshots at the engine/UI
   boundary.
2. Keep the Python parser as the source-of-truth worker until parity is proven.
3. Build the Electron shell and React HUD against recorded fixtures first.
4. Port parser modules only behind parity tests; a small permanent Python
   worker is acceptable when it is more reliable.
5. Keep file watching, parsing, wiki/cache I/O, and inventory evaluation off
   the renderer thread and coalesce high-frequency updates.
6. Preserve the security boundary: no injection, memory reading, gameplay
   automation, or input control.

Measure cold start, idle/combat CPU, resident memory, event backlog, and render
latency before claiming an Electron improvement.

### P2: HUD and interaction design

- Minimal HUD: tiny movable Rune Seed with one primary metric and urgent
  secondary signals only.
- Expanded HUD: mez/lull timers first, then alerts and encounter statistics.
- Timers require strong target labels, safe time, last-tick state,
  warning/critical treatments, overflow, and non-color accessibility cues.
- Motion must be restrained and respect reduced-motion settings.
- Preserve always-on-top, lock/move, click-through recovery, tray restore,
  scalable opacity, and clean common/ultrawide resizing.
- Alerts stay optional and individually configurable.

### P3: optional stance assistant

Add a disabled-by-default, deterministic advisor that recommends but never
activates a stance. It needs rolling magical/physical pressure evidence,
confidence, minimum evidence, hysteresis, cooldowns, explanations, Off/Subtle/
Detailed modes, and per-stance suppression.

### P4: automatic live inventory upgrade advice

Add an optional, background, log-driven comparison pipeline. Resolve item data
through the safe cache layer; compare only against explicit profiles; consider
slot, restrictions, level, stats, resists, effects, and weights; report
Upgrade, Sidegrade, Situational, or Unknown with confidence. Never automate an
inventory action.

## First milestone

1. Run and record the Python baseline.
2. Map and regression-test every mez/lull path.
3. Fix correctness and implement lull in Python.
4. Document a typed, versioned snapshot/event protocol.
5. Scaffold Electron + React + TypeScript without deleting Python.
6. Replay fixtures through minimal and expanded HUDs.
7. Document performance instrumentation and known gaps.

### Definition of done

- Existing and new mez/lull regressions pass.
- No mez or lull active timer begins from a cast without sufficient landing
  evidence.
- The Electron preview replays fixtures in minimal and expanded HUDs.
- Mez/lull alerts are readable, stable, nonblocking, and configurable.
- The Python application remains runnable and releasable.
- Measurements and known gaps ship beside the preview.

P3 and P4 remain later milestones and must not weaken P0 correctness.
