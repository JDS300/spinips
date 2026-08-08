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
