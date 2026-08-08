# Loremaster desktop milestone 1

## Delivered scope

- Existing zero-dependency Python app preserved.
- Evidence-first lull/pacification tracker added beside the mez tracker.
- Nearby-caster mez ambiguity is no longer silently discarded.
- Control rows expose confidence, same-name ambiguity, final-tick state, and
  non-color urgency labels.
- Independent mez and lull visual/sound settings.
- Sanitized deterministic log sequences cover cast-only, landing, fizzle,
  interrupt, resist, overwrite, fade, damage, death, zone, character switch,
  reset, same-name grouping, silent-result lulls, and nearby-caster ambiguity.
- Protocol-v1 frozen Python snapshots and matching TypeScript types.
- Separate Electron/React fixture preview with Rune Seed and expanded control
  dashboard states.

## Evidence policy

Active timers require a recognized local cast plus a compatible observable
landing. The client spell data has no landing message for Harmony and Lull
Animal, so those casts produce an honest `unconfirmed` notice and no timer.
Unknown character level uses a strict lower-bound duration and is labeled
`conservative`; a logged level produces `exact` lull duration.

## Security and threading

The preview is fixture-only in this milestone. It has context isolation,
sandboxed rendering, no Node access in React, blocked in-app navigation, and no
network dependency. The tested Python ingest/parser remains independent and no
game process access or input control was introduced.

## Performance instrumentation

- Python release gate measures 30,000-line ingest throughput and peak memory.
- Electron main reports cold-start milliseconds and resident memory through a
  narrow preload boundary that also exposes only expand, minimize, and close
  window commands.
- React measures one-frame snapshot render latency in the preview footer.
- Fixture events are immutable replacements and replay at a bounded cadence;
  no parser or filesystem work runs in React.

Measured values for the validated build are recorded in the final validation
section of this document before release.

## Final local validation

Validated on Windows with Python 3.12, Node 24.14, pnpm 11.16, and the
current supported Electron 43.3 runtime:

- Python: 252 unit/fixture tests passed in 0.413 seconds.
- Deterministic ingest gate: 30,000 lines at 12,365 lines/second with
  0.02 MiB traced peak allocation.
- Desktop protocol fixture: 6 ordered protocol-v1 snapshots passed runtime
  validation.
- Desktop production build: 31 modules; 198.91 kB JavaScript (61.90 kB gzip),
  8.12 kB CSS (2.46 kB gzip), and a 0.69 kB HTML shell.
- Visual replay: all 6 states fit the 470 x 620 expanded viewport without
  clipped control rows, horizontal overflow, or a hidden health footer.
- Actual Electron shell: trusted local renderer loaded successfully; the
  frameless Rune Seed opened at 128 x 74 and expanded to 470 x 620.
- Native GUI smoke: Vellum & Ember and Midnight Frost Glass both passed Seed,
  Settings, expand, and collapse geometry checks.
- Full release quality gate: all SpinUI structure, Glass parity, layout,
  Loremaster, installer, unit, and ingest audits passed in 8.0 seconds.

## Known gaps

- Live Python-worker IPC is intentionally not enabled until fixture and parser
  parity are accepted. The protocol is defined; the preview currently replays
  local snapshots.
- EQL emits no success line for some lull-family spells. Loremaster refuses to
  invent a target or active duration for them.
- The Electron preview is not yet a release artifact and does not replace the
  Python EXE.
- The preview currently reports main-process RSS and renderer frame latency;
  whole Electron process-tree memory, idle/combat CPU, event backlog, and cold
  start distributions still need release-hardware baselines before any
  performance comparison is claimed.
- Tray/click-through/opacity parity is still provided by Python; Electron
  parity is a later gate.
- Stance advice and automatic loot upgrade classification are P3/P4 and are not
  part of this correctness-first milestone.
