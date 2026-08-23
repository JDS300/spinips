# Changelog

What each release is for. Written in the pull request that makes the change,
so the release itself carries it: `tools/release_notes.py` reads the entry
matching the version being published, and a candidate and the release it is
promoted to resolve to the same entry.

## 0.5.1

Fixes AppImage update information, which has never worked.

### Fork-specific

- **Gear Lever can update Loremaster again.** An update manager reads a 1 KB
  `.upd_info` section inside the AppImage to learn where a newer build lives.
  electron-builder never wrote it -- app-builder-lib 26.x has no writer for it
  and no zsync code at all -- so the section shipped as the zeroed placeholder
  baked into the AppImage runtime. Confirmed with `readelf` against the
  published v0.4.0 and v0.5.0-rc.1 images: 1024 bytes, entirely zero in both.
  Every release this project has made showed a blank update panel, and the
  `.zsync` added in 0.4.0 was an orphan -- a correct file that nothing pointed
  at.

  CI now writes the section after the build and verifies it by reading it back,
  so a silent regression fails the build rather than shipping.

- **Candidates track candidates, releases track releases.** GitHub's
  `/releases/latest` excludes prereleases, so a release candidate could never
  have found a newer candidate through it. Candidates now advertise the
  `latest-pre` channel and match `Loremaster-RC-*`; releases stay on `latest`
  and match `Loremaster-[0-9]*`. The two globs cannot match each other's
  assets, in either direction.

## 0.5.0

Adds debuff timers — the first fork-only *feature*, rather than platform
plumbing or a bug fix.

### Fork-specific

- **Debuff timers.** Your own damage-over-time spells, slows and resist
  debuffs now count down on their own deck below the mez and lull control
  stack, grouped one block per mob. Coverage is shaman, enchanter and
  beastlord for slows, shaman and enchanter for resist debuffs, and shaman,
  enchanter, beastlord, necromancer and druid for DoTs, to level 50.

  The two families are tracked by different evidence, and the deck marks which
  is which. **DoTs are confirmed:** every tick line names target and spell
  together, so attribution is never guessed, and the tick doubles as a
  heartbeat — a DoT still ticking past its computed expiry is held on the deck
  instead of dropped. **Slows and resist debuffs are estimates,** marked `EST`:
  their landing prose names the target but not the spell, so the timer is
  correlated against your own recent cast exactly as mez is, and a nearby
  shaman's slow prints the same line and is ignored.

  Durations do not account for **focus items**, which extend them and which
  Loremaster cannot see — the same limitation mez and lull have always had. An
  `EST` countdown is a floor rather than a measurement. DoT rows correct
  themselves from their ticks; slow and resist rows cannot, so they linger
  briefly at zero instead of vanishing.

  Spell durations are derived from published per-level endpoints, and the test
  suite asserts every formula still reproduces both of its published
  endpoints, so the table cannot drift silently. Visibility, per-family
  toggles, the warning threshold and the mob cap live in
  **Settings → Debuff Timers**.

- **The README no longer claims the fork adds "nothing else."** It now says
  what it does add.

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
- **The game's new interface options are there again.** The August patch added
  Use System Cursor, Cursor Scaling and "Use Actions - Spells instead of
  Spellbook" to Options > Interface > General. Both skins ship their own copy of
  that window, so the client could not find the three controls: it logged
  "Could not find child" every time the window opened and the settings were
  unreachable while a skin was loaded. They are laid out with the rest of the
  page now, and Cursor Scaling offers the same eleven steps the default UI does.
- **UI Scaling asks for the scale it names.** Both skins listed `1x` through
  `5x`, from before the game moved to quarter steps. The client reads the
  selection by which row is chosen rather than by its text, so the rows had
  quietly stopped meaning what they said: `3x` asked for 1.50x and `5x` asked
  for 2.00x, and nothing above 2.00x could be picked at all. Both scaling menus
  now carry the client's eleven steps in the client's order.
- **An update manager can see this release.** The Linux AppImage has always
  advertised zsync updates, so a manager like Gear Lever goes looking for a
  matching `.zsync` file in the newest release -- but nothing in the build ever
  produced one. Only 0.3.4 carried it, made by hand, which is why that was the
  last release an update could be offered from. It is built and published
  alongside the AppImage from here on.

### Removed

- **Alt+Z instance lockout OCR.** Upstream retired the feature and this fork
  follows them; raid context now comes from the log rather than from scanning
  the Instance Information window. `Ctrl+Shift+Z` is no longer claimed.
