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
| An X11 session, or Wayland with XWayland | Window placement, overlays, screen capture | Loremaster selects X11 automatically. Without one it runs on Wayland with reduced window control. |
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

## Multi-monitor: the recommended layout

If you have more than one screen, use it. Put **EverQuest fullscreen on one
monitor and Loremaster on another.**

This is not merely tidy — it removes the only genuinely uncertain part of
running Loremaster on Linux. Overlay compositing above a fullscreen game,
click-through, and always-on-top ranking against the window manager all exist
solely because the overlay has to sit on top of the game. Move it to a second
screen and none of them apply: Loremaster becomes an ordinary window, and every
feature works the way it does on any desktop app.

It also helps the game. EverQuest confines the mouse pointer during right-click
mouse-look by asking Windows to clip the cursor to its window. Wine has to
translate that into an X pointer confine, and on multi-monitor setups —
especially with fractional scaling — that translation often fails, letting the
cursor escape onto another screen mid-look or leaving the camera pitching. The
supported fix is winecfg → Graphics → **"Automatically capture the mouse in
full-screen windows"**, which keys off *fullscreen*, so run the game truly
fullscreen rather than borderless.

### A note on gamescope

Launching EverQuest through gamescope appears to fix the cursor-escape problem,
but it does so by collapsing your monitor layout: inside a nested session the
game sees exactly one output, so there is nowhere for the cursor to escape to.
That is a workaround for a Wine problem, not a gamescope feature, and it costs
you overlays — gamescope is a nested compositor, so Loremaster's overlays are
host-session windows that cannot composite inside it. `--force-grab-cursor`
compounds this by holding the pointer.

gamescope also disables the OCR features. Hover scan and the Alt+Z lockout scan
verify that the focused window belongs to `eqgame.exe` before capturing
anything. Under gamescope the game runs on gamescope's own nested display, so
the focused window on your session is gamescope's, owned by the gamescope
process — the check refuses, naming what it saw. That guard is a privacy
guarantee and is not going to be relaxed, so treat OCR as unavailable whenever
the game is launched through gamescope.

Running the client windowed rather than fullscreen does not change either
limitation. At a resolution matching gamescope's output it looks identical and
usefully avoids Wine's exclusive-fullscreen mode set, but overlays and OCR stay
unavailable, and windowed mode also stops winecfg's fullscreen mouse capture
from ever engaging — which removes the very lever that would let you drop
gamescope later.

Summary of the trade:

| Setup | Overlays | OCR | Mouse-look |
| --- | --- | --- | --- |
| gamescope, any window mode | no | no | fixed, by hiding your other monitors |
| No gamescope, fullscreen + winecfg mouse capture | yes | yes | fixed at the Wine level |

Prefer fixing the cursor confinement at the Wine level and keeping gamescope
out of the picture. If you genuinely need gamescope, put Loremaster on a second
monitor, and expect the overlay and OCR features to be unavailable.

## Window placement

Loremaster places and remembers its own windows. Drag one where you want it,
and it returns there next time. If the display it was on no longer exists, it
falls back to a position the platform chooses rather than opening off-screen.

**No window rules are required, on any desktop.** Earlier revisions of this
document asked KDE users to create per-window rules; that advice is obsolete
and should be removed if you followed it.

This works because the application runs on Chromium's X11 backend, which it
selects automatically wherever an X server is reachable — including XWayland on
a Wayland session, which is also how EverQuest itself renders. X11 is the only
backend on which a client may position itself: Wayland deliberately gives
applications no way to read or set an absolute window position, and no
application can work around that.

If you deliberately run the Wayland backend with `LOREMASTER_OZONE=wayland`,
expect the limitations that come with it:

- Windows cannot be positioned or restored by the application.
- The alert and control surfaces cannot anchor to the seed.
- No window can raise itself above a fullscreen game.

Those are properties of the display protocol, not of Loremaster. On that path
the compositor has to place the windows, which is why each one carries a
distinct title — `Loremaster`, `Loremaster Alert`, `Loremaster Controls` — so a
window rule can target it. Prefer the default.

## Wayland and XWayland

Loremaster runs on Chromium's **X11 backend** wherever an X server is reachable,
including XWayland on a Wayland session. That is the same path EverQuest itself
takes under Wine or Proton.

This is not a preference. X11 is the only backend on which an application may
position and remember its own windows; Wayland deliberately forbids it. Running
X11 is what makes placement, anchored alert surfaces, always-on-top and global
hotkeys work without asking you to configure your compositor.

Selecting it needs care, and this is worth knowing if you are reading the code:
Chromium chooses its ozone platform **before application code runs**, so setting
the switch with `app.commandLine.appendSwitch` has no effect at all. The flag
must be on the command line the process started with, so Loremaster re-executes
itself once with `--ozone-platform` appended. The relaunched process already
carries the switch, so it starts normally.

If no X server is reachable — `DISPLAY` unset, a pure Wayland session without
XWayland — Loremaster does not force X11 and runs on Wayland instead. Forcing it
with no X server produces a tray icon and no window, which is worse than the
limitations of the Wayland backend.

To override:

```
LOREMASTER_OZONE=wayland ./loremaster   # force the Wayland backend
LOREMASTER_OZONE=x11 ./loremaster       # force X11 even without DISPLAY set
```

Expect the Wayland backend to cost you window placement, anchored surfaces and
raising above a fullscreen game, as described under *Window placement*.

One cosmetic consequence of the re-exec: the relaunched process detaches from
the terminal it was started from, so diagnostic output on stdout is not visible
when launching from a shell.

## Environment variables

| Variable | Effect |
| --- | --- |
| `LOREMASTER_PYTHON` | Interpreter used for the parser engine. Set this if your `python3` is too old or lives somewhere unusual. |
| `LOREMASTER_OZONE` | Force a Chromium backend: `x11` or `wayland`. Unset selects X11 wherever an X server is reachable, which is the default and what makes window placement work. |
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
