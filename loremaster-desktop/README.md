# Loremaster desktop

This is the live Electron + React + TypeScript migration of Loremaster. The
renderer receives immutable protocol-v1 snapshots from a supervised local
Python engine; it never reads EverQuest files or exposes Node to React.

```powershell
pnpm install --frozen-lockfile
pnpm test:fixtures
pnpm build

# Source development (point to a Python 3.10+ executable when the Windows
# Python launcher is unavailable):
$env:LOREMASTER_PYTHON = "C:\path\to\python.exe"
pnpm dev
```

`pnpm dist:windows` produces the portable `Loremaster.exe` after
`../dist/LoremasterEngine.exe` has been built. The package deliberately has no
installer target.

Electron owns windowing, animation, settings, log-folder selection and engine
health. The parser engine remains authoritative for combat attribution,
charmed pets, mez/lull evidence and D0–D4 weekly raid events. The narrow preload
exposes only versioned state, folder selection, reset, and window commands.

## Native Loremaster themes

Loremaster includes two complete presentation systems using the same parser,
layout and accessibility behavior:

- **Vellum & Ember** is the default and matches `spinui_reloaded` with oiled
  leather surfaces, parchment text, brass edges and restrained spirit-blue
  selections.
- **Midnight Frost Glass** matches `spinui_glass` with deep translucent panes,
  ice-blue edges, mint actions and violet selections.

The theme picker in Settings applies immediately to the Seed, expanded HUD,
Settings, alerts, crowd-control timers and Combat Archive. The selection is
stored with the other desktop settings and restored before windows are shown,
so changing themes never restarts the parser or moves an overlay.

Alert Sound Studio includes four locally generated cues plus Silent, with a
separate selection for charm breaks, tells, summons, deaths, big hits, name
calls, mez warnings and lull warnings. Each event may instead use a local WAV,
MP3, OGG or M4A file selected through the native file picker. Custom audio is
validated and size-limited by Electron's main process; the sandboxed renderer
never receives general filesystem access.

Weekly D0–D4 progress comes from explicit raid difficulty plus combat-log boss
evidence, with a confirmation prompt when the difficulty is not known and a
manual correction grid. Loremaster deliberately does not scrape EverQuest's
Instance Information window or reserve a global lockout-screen hotkey.

The Gear Path surface imports EQ Legends Tools' version-1 character-sheet JSON
and EverQuest's `/outputfile inventory` TXT locally. It identifies goal items
already equipped or held in bags/bank and groups missing pieces by source zone.
Item/source metadata is refreshed on explicit user action and cached locally.
Credit: [EQ Legends Tools](https://eqlegendstools.com/) by **FlammHammer**.

Because releases remain portable (no installer), Settings includes a safe
GitHub release check and opens the official release page when an update exists;
the app never silently replaces its running executable.

See [milestone 2](../docs/LOREMASTER_MILESTONE_2.md) for the live scope and
release validation gates.
