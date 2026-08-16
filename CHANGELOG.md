# Changelog

What each release is for. Written in the pull request that makes the change,
so the release itself carries it: `tools/release_notes.py` reads the entry
matching the version being published, and a candidate and the release it is
promoted to resolve to the same entry.

## 0.4.0

First build carrying the upstream work merged since 0.3.4, plus the fork fixes
that came with it.

### From upstream ([itsspin/spinips](https://github.com/itsspin/spinips))

- **Native themes** — Vellum & Ember, and Midnight Frost for Glass, applied
  consistently across every window and remembered between sessions.
- **Adventure journal** — loot and encounter history kept in a local database,
  so a session's kills and drops survive a restart.
- **Raid context from the log** — instance and difficulty are read from log
  evidence instead of being asked for, so kills are credited without a prompt
  where the log already says enough.
- **Item intelligence** and a rebuilt gear plan import.
- **Combat frames** — a foreground attack perimeter, a brighter auto-attack
  pulse, and tightened player progression bars.
- **Pet illusions restored**, and alert sounds you can point at your own files.
- **SpinTexture** companion project for sharper world textures.

### Fork-specific

- **Updates check this fork.** Both updaters previously asked
  `itsspin/spinips` what the newest build was — which never carries the Linux
  AppImage, and would install upstream's skins over this fork's. They now
  follow this repository.
- **Every raid kill awaiting a difficulty is kept.** A single pending slot
  discarded the first kill when two raid targets died before you confirmed a
  difficulty, which is exactly what happens when a raid clears several at
  once. Each kill now keeps its own zone, character and clear time.
- **Release candidates install beside the release** — a candidate now builds as
  "Loremaster RC" with its own desktop entry, so a tool like Gear Lever can hold
  it and the live release at the same time instead of treating them as one app.
  It shares the live settings on purpose, so bugs show up against real data, and
  it copies those settings aside once per candidate before it can touch them.
- **The Windows executable is no longer published here** — releases carry the
  Linux build and the skins. The executable is still built and tested on every
  run, so a change that breaks it is still caught, but it is not offered for
  download from this fork. Anyone already running the Windows build will see
  its updater fail rather than find a new one.

- **Loremaster starts again on Linux.** The Windows portable updater resolved a
  PowerShell path while the app was still starting, which fails on Linux and
  took the whole startup with it: no window, no tray icon, no engine. The path
  is now looked up only when a Windows update is actually being installed.
- **The stance row is visible again.** The player frame's bottom row -- Mage
  Hunter, Defensive, Invocation, Over Channel, Recovery -- was cut off because
  the frame was ~12px shorter inside than its layout assumed. The frame is
  taller and the row now rides its lower edge, so it stays readable at any
  size. Both skins, all seven variants.
- **Alert cards keep out of the way.** They no longer land on the crowd-control
  panel, which cannot be dragged aside, and they never cover the seed window --
  which had made analyze, settings and even moving the app unreachable.

### Removed

- **Alt+Z instance lockout OCR.** Upstream retired the feature and this fork
  follows them; raid context now comes from the log rather than from scanning
  the Instance Information window. `Ctrl+Shift+Z` is no longer claimed.
