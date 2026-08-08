# Loremaster desktop milestone 2

## Outcome

Loremaster is now a live Electron + React + TypeScript application, not a
fixture player. Electron supervises a private headless parser engine over
versioned UTF-8 JSONL and is the portable desktop shipped with UI releases.

## Live path delivered

- Secure Electron main process with context isolation, sandboxed React,
  blocked renderer navigation, and a narrow typed preload API.
- Supervised local engine with bounded restart backoff and explicit starting,
  searching, live, and error health states.
- Automatic newest-character log following plus an in-app EverQuest folder
  chooser and durable per-user location setting.
- Atomic live combat snapshots with fight/session DPS and separate self,
  charmed-pet, and summoned-pet attribution.
- Live evidence-first mez and lull timers, including uncertainty and final-tick
  states.
- Proven charm-break events crossing the process boundary into a short danger
  banner; unrelated fades still remain silent.
- A conservative D0–D4 raid-reset ledger for Master Yael, Phinigel Autropos,
  Lord Nagafen, Lady Vox, Innoruuk, and Cazic-Thule. Only local-player or
  proven-pet kills count. Difficulty is explicit because the EQ log does not
  reliably announce the selected tier.
- A single portable Windows test build containing the React application and
  its hidden parser engine. No installer target is produced.

## Release gate

`Loremaster.exe` is the CI-built Electron desktop and contains its private
headless parser engine. The workflow smoke-tests the protocol, strict
TypeScript build, production renderer, bundled engine, and portable executable
before the same binary is copied into the manual ZIP and attached to the UI
release. The legacy Python GUI remains source/reference code and is not
published as a competing executable.

## Weekly tracker boundary

The ledger answers “which D0–D4 raid lockouts were completed this reset?” It
uses Tuesday at 8:00 AM Pacific, persists events locally, and leaves every cell
manually correctable. Plane of Sky is intentionally outside this weekly ledger.

## Validation

- Python worker/weekly/protocol tests cover exact catalog matching, persistence,
  reset boundaries, live DPS/control snapshots, log-search health, and one-shot
  charm-break propagation.
- The TypeScript main, preload, protocol guard, and React renderer compile in
  strict mode and produce a Vite production bundle.
- The packaged engine passes a real subprocess JSONL handshake.
- The unpacked Electron production application launches its bundled engine and
  exits cleanly through the smoke-only shutdown hook.
