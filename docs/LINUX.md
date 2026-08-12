# SpinUI and Loremaster on Linux

EverQuest Legends runs on Linux under Wine or Proton. SpinUI's skins are ordinary
client assets, so they work there unchanged. Loremaster runs **natively** — it is
not run under Wine, and you should never try to. It reads your ordinary EQ log
files and, for two optional features, performs one-shot user-triggered screen
OCR. There is no injection and no game-memory access.

Before trusting a fresh install in a real session, work through
[the in-game test plan](LINUX_INGAME_TESTPLAN.md).

## Requirements

| Requirement | Why | Notes |
| --- | --- | --- |
| Python 3.10 or newer | Runs the parser engine | Almost certainly already installed. The engine is stdlib-only — no pip packages. |
| An X11 session, or Wayland with XWayland | Overlays, always-on-top, screen capture | Loremaster forces the X11 backend by default. See below. |
| `tesseract` **and its English language data** | Hover OCR and instance-lockout scan only | Optional. Everything else works without it. |

Loremaster deliberately does **not** ship a bundled Python. The engine is
stdlib-only, so using your system interpreter keeps the download small and
avoids glibc compatibility problems across distributions.

### The tesseract trap

Installing `tesseract` is not enough — it ships without language data on most
distributions, and OCR then fails while the binary looks perfectly installed.
Check:

```
tesseract --list-langs
```

If `eng` is not listed, install the language pack:

| Distribution | Package |
| --- | --- |
| Arch / CachyOS / Manjaro | `tesseract-data-eng` |
| Debian / Ubuntu | `tesseract-ocr-eng` |
| Fedora / RHEL | `tesseract-langpack-eng` |

Loremaster detects this at startup and tells you which package you need.

## Installing

### Loremaster

Download from the releases page and either:

- **AppImage** — `chmod +x Loremaster-*-x86_64.AppImage` and run it. Needs FUSE;
  if your system lacks it, run with `--appimage-extract-and-run`.
- **tar.gz** — extract and run `./loremaster` inside.

### The skin

The installer copies the skin into your EverQuest folder and writes a layout
profile. It runs headless on Linux — there is no GUI installer here.

```
# See what it would do, without writing anything
python3 installer/spinui_installer.py --install --dry-run --layout combat-focus

# Do it
python3 installer/spinui_installer.py --install --layout combat-focus
```

**Close EverQuest first.** The installer refuses to write over a running client,
because doing so corrupts UI files.

If auto-discovery does not find your install, point at it explicitly:

```
python3 installer/spinui_installer.py --install --eq-dir "/path/to/EverQuest Legends"
```

Useful flags: `--list-presets`, `--skin {spinui_reloaded,spinui_glass}`,
`--layout {combat-focus,social-focus,hybrid}`, `--resolution`, `--dry-run`.

Then, in game: `/loadskin spinui_reloaded 1` or `/loadskin spinui_glass 1`. The
trailing `1` preserves your window positions.

If the installer finds only a `.tar.gz` Loremaster build it will say so and skip
installing Loremaster — extract that archive and run `./loremaster` yourself.
The skin still installs normally.

## Finding your EQ logs

Loremaster searches Wine and Proton prefixes automatically:

- `$WINEPREFIX`
- `~/.wine`
- **Lutris prefixes, read from Lutris's own game configuration.** Every
  `~/.local/share/lutris/games/*.yml` (and the Flatpak equivalent) carries an
  absolute `prefix:` path. This matters because Lutris prefixes routinely live
  outside your home directory on a separate drive — a path no home-relative
  search could ever guess.
- `~/.steam/steam/steamapps/compatdata/*/pfx` and
  `~/.local/share/Steam/steamapps/compatdata/*/pfx`
- Flatpak Steam under `~/.var/app/com.valvesoftware.Steam`
- `~/Games/*`, Lutris's default install location

Inside each prefix it probes the usual EverQuest folder shapes, including both
`users/Public` and Proton's `users/steamuser` profile, plus
`Program Files (x86)`. Prefix enumeration is capped so a large Steam library
does not slow startup, and Lutris prefixes are collected before that cap
applies.

Steam libraries are additionally searched natively for
`steamapps/common/EverQuest{, Legends}`, including extra drives listed in
`libraryfolders.vdf`. A Steam-installed game lives outside any prefix's
`drive_c`, so prefix probing alone cannot find it.

If several EverQuest installs are registered, the most recently written
`eqlog_*.txt` wins — so the one you last played is the one that is picked up.

**Auto-discovery is the least-proven part of the Linux port** — it had no prior
art to copy. If it misses your install, open settings and set **EVERQUEST
DIRECTORY** to your EQ or Logs folder. That path is fully supported, persists
across restarts, and is not a second-class fallback.

Also make sure logging is on in the client: `/log on`. Loremaster cannot do
anything without it.

## Wayland and XWayland

Loremaster forces Chromium's X11 backend on Linux. This is deliberate: EQ runs
under Wine or Proton and therefore renders through XWayland, and putting
Loremaster on the same X server is what makes always-on-top, click-through
overlays, global hotkeys, and screen capture work. Under a native Wayland
backend, Wayland's security model blocks most of that.

To override:

```
LOREMASTER_OZONE=wayland ./loremaster   # native Wayland
LOREMASTER_OZONE=auto ./loremaster      # let Chromium decide
```

One known cosmetic gap: Electron's mouse-move *forwarding* for click-through
windows is Windows/macOS-only, so hover effects on overlays are inert on Linux.
Click-through itself works.

## Environment variables

| Variable | Effect |
| --- | --- |
| `LOREMASTER_PYTHON` | Interpreter used for the parser engine. Set this if your `python3` is too old or lives somewhere unusual. |
| `LOREMASTER_OZONE` | `x11` (default), `wayland`, or `auto`. |
| `SPIN_LOREMASTER_TESSERACT_LANG` | OCR language, default `eng`. |
| `SPIN_LOREMASTER_TESSERACT_PSM` | Tesseract page-segmentation mode. Try `11` if tooltip OCR returns nothing. |

## Running from source

```
cd loremaster-desktop
pnpm install --frozen-lockfile
pnpm build
pnpm dev
```

`pnpm dev` picks up `python3` automatically; set `LOREMASTER_PYTHON` if you need
a specific interpreter. To build distributables: `pnpm run dist:linux`.

Run the checks the way CI does:

```
cd loremaster/tests && python3 -m unittest discover -s . -p 'test_*.py'
python3 tools/release_quality_gate.py
python3 installer/spinui_installer.py --selftest
```

Note the test discovery start directory — running it from the repository root
fails with "Start directory is not importable".

The quality gate replays a layout-drift check against an early commit that is
unreachable from any branch, so no clone fetches it at any depth. Fetch it
explicitly once:

```
git fetch --no-tags origin 0eac353de160346146fc8bd451fc60eb7b7a371a
```

## Troubleshooting

**Engine never reaches "live".** Confirm `/log on` in the client and that an
`eqlog_*.txt` is growing. Then set the folder manually in settings. Launch from
a terminal to see the resolved engine and log path on stdout.

**"No Python interpreter was found."** Install Python 3.10+ or set
`LOREMASTER_PYTHON`.

**Overlays vanish when EQ is fullscreen.** Use borderless or windowed
fullscreen. Always-on-top maps to `_NET_WM_STATE_ABOVE`, which some window
managers rank below a true fullscreen window.

**Overlays misbehave and you launch through gamescope.** gamescope is a nested
compositor — the game renders inside gamescope's own session, while Loremaster's
overlays are ordinary windows on the host session, so they cannot composite
inside it. `--force-grab-cursor` additionally holds the pointer, which can stop
clicks reaching either the overlay or the game. Turn gamescope off in Lutris and
retest before treating this as a Loremaster bug.

**Ctrl+Shift+Z does nothing.** Another application likely holds the shortcut.
Registration failure is non-fatal and reported at startup; the rest of the app
is unaffected.

**Hover OCR returns nothing.** Check `tesseract --list-langs` for `eng` first,
then try `SPIN_LOREMASTER_TESSERACT_PSM=11`. If the captured frame is blank, use
borderless rather than exclusive fullscreen.

**OCR says it will only capture eqgame.exe.** Working as intended — it verifies
the focused window belongs to the game before capturing anything, and refuses
otherwise.
