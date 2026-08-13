# Native Linux support — summary for upstream

This describes a branch that adds native Linux support to the Loremaster
desktop application, the SpinUI skin installer, and the release pipeline. It is
written to be checked rather than taken on trust: every claim below is either
marked verified with the evidence that supports it, or marked unverified.

**Nothing here asks Linux users to run the Windows build under Wine.** Only
EverQuest itself runs under Wine or Proton. Loremaster runs natively.

## Where the code is

- Branch: [`agent/linux-native`](https://github.com/JDS300/spinips/tree/agent/linux-native)
- Pull request: [JDS300/spinips#1](https://github.com/JDS300/spinips/pull/1)
- Releases: [v0.3.4](https://github.com/JDS300/spinips/releases/tag/v0.3.4) and earlier, Linux only

Commits are scoped one change per commit, and each message states what was
observed rather than only what was altered — the history is meant to be read as
the argument for the change.

### Defects found during the port, and where they were resolved

Everything below was found by running the software rather than by reading it.
Issues are on the fork so the trail is public; the fixes are in this branch.

| | Defect | Resolution |
| --- | --- | --- |
| [#2](https://github.com/JDS300/spinips/issues/2) | Analysis view clamps to the display but its content does not scroll, so data is unreachable on a short screen | [#4](https://github.com/JDS300/spinips/pull/4) — grid items lacked `min-height:0`, so their existing `overflow` rules never engaged. Cross-platform. |
| [#3](https://github.com/JDS300/spinips/issues/3) | Collapsing to the seed after Analyze leaves the window oversized | **Open.** The obvious cause is disproven; two candidates recorded. |
| [#5](https://github.com/JDS300/spinips/issues/5) | NVIDIA GPU crash believed to block the X11 backend | **Closed as misdiagnosed** — every measurement came from runs silently on Wayland. |
| [#6](https://github.com/JDS300/spinips/issues/6) | `ozone-platform` set through `app.commandLine`, which Chromium reads too late, so the X11 backend was never used | [#7](https://github.com/JDS300/spinips/pull/7) and [#8](https://github.com/JDS300/spinips/pull/8) |

Two engine defects were also found and fixed here; both are cross-platform and
predate this branch. They are described under their own heading below.

## Principle

Strictly additive. No Windows code path changes behaviour. Where a platform
difference exists, the Windows branch is left exactly as it was and a Linux
branch is added beside it.

The retired tkinter GUI (`loremaster/loremaster.py`, `windows_tray.py`,
`windows_hotkeys.py`, `wiki_overlay.py`) is untouched. Milestone 2 states it is
no longer published, so porting it would have been wasted effort.

## Why this was small

The shipping stack was already portable: Electron and React over a stdlib-only
Python engine speaking JSONL on stdio. No second UI implementation was needed.
The work was almost entirely platform plumbing — process launch, path
discovery, screen capture, packaging — rather than application logic.

## What changed

### Desktop application

- **Engine resolution** is platform-aware: a bundled native binary, then
  `LOREMASTER_PYTHON`, then the system `python3` (`py -3` on Windows).
- **No PyInstaller binary ships on Linux.** The engine is stdlib-only, so using
  the system interpreter keeps the download small and avoids glibc skew across
  distributions. Engine sources ship through `extraResources`.
- **Log discovery** searches Wine and Proton prefixes: `$WINEPREFIX`, `~/.wine`,
  Steam `compatdata`, Flatpak Steam, `~/Games`, and — importantly — prefixes
  read out of Lutris's own game configuration, because Lutris prefixes routinely
  live outside `$HOME` on another drive where no home-relative probe finds them.
  Steam libraries are additionally searched for `steamapps/common/EverQuest*`,
  which sits outside any prefix's `drive_c`.
- **Chromium backend detection is left alone.** Forcing the X11 backend was
  tried and reverted; see *Known limits*.
- **AppImage and tar.gz targets**, PNG icon, `.desktop` integration.
- **Each window has a distinct title** (`Loremaster`, `Loremaster Alert`,
  `Loremaster Controls`). They render the same document, so they previously
  shared one caption and no window-manager rule could target them individually.
- **A saved window position is only restored when a display still covers it.**

### Parser engine

- **New `loremaster/linux_capture.py`**: X11 capture through `ctypes`/`libX11`
  plus the Tesseract CLI, behind the existing hover-scan seam. No new Python
  dependencies.
- It captures **the verified window's own drawable**, not the root window. A
  region-arithmetic bug therefore cannot reach another application, and it stays
  correct under XWayland where the root window is not the composited desktop.
- Identity is checked through `_NET_WM_PID` and `/proc` **before any pixels are
  read**, and any window not owned by `eqgame.exe` is refused.

### Alt+Z lockout scan

Two corrections that also describe latent problems on Windows:

- The scan **captures the whole game window** rather than a 960×720 region
  framed on the mouse pointer. Framing on the cursor suits a tooltip, which is
  under the cursor by definition, and fails for a panel the player has placed
  somewhere at their own resolution.
- The panel is reachable **from a button** rather than only a global shortcut,
  and **an empty table reports success rather than an error**. Having no raid
  lockouts is the ordinary state, and it was previously indistinguishable from a
  failed scan.

### Installer

Headless `--install` / `--dry-run` CLI, Wine-prefix EverQuest discovery, XDG
paths, freedesktop `.desktop` entries pointing at the native build, and a
`/proc` running-client guard. Also fixes a latent crash: `stop_running_loremaster`
invoked `taskkill.exe`, which does not exist on Linux.

### CI

Linux build and release jobs. The platform-agnostic UI audits move to
`ubuntu-latest`, which is cheaper and now passes there. Windows jobs unchanged.

## Two pre-existing bugs fixed

Both affect Windows equally and are unrelated to Linux.

- **The generated-layout drift check has been dead since the squashed public
  release.** It replays `0eac353:default_modern/*.ini`, but that commit is
  unreachable from every ref, so no clone retrieves it at any depth —
  `fetch-depth: 0` is necessary and not sufficient, and the error text ("fetch
  full git history") points the reader at a dead end. GitHub still serves the
  object by exact SHA, so CI now fetches it explicitly before the gate runs.
- `instance_lockout_ocr.py` was missing from the quality gate's
  `SOURCE_REQUIRED` list.

## Verification

Test environment: CachyOS (Arch), KDE Plasma on Wayland, NVIDIA 610.43.03 on an
RTX 4080 SUPER, three monitors with fractional scaling, EverQuest Legends
installed through Lutris with Proton Experimental via umu, prefix on a separate
mount.

| Check | Result |
| --- | --- |
| Python test suite | 331 pass, from a 281 baseline |
| Suite headless, and with no English Tesseract model | passes in both |
| `release_quality_gate.py` | ALL PASS on Linux |
| Electron build, fixtures, gear audit | pass |
| `dist:linux` | AppImage and tar.gz produced |
| Skin install | 1667 and 1669 files, byte-identical to source |
| `/loadskin` both skins | load, nothing missing or broken |
| Log auto-discovery | found the real log in a Lutris prefix with nothing configured |
| Parser on a 690,174-line log | correct character and zone |
| Parser on live combat | kills, damage, crits, healing, damage taken |
| Running-client guard | a live Wine client reports `comm` = `eqgame.exe` |
| Capture and OCR round trip | three strings in a real X11 window returned exactly |
| Alt+Z scan, empty table | reads the panel, reports success rather than an error |
| Alt+Z scan, populated table | read a real panel and marked two raid completions |
| Charm-break alert | fires on a proven break |
| Mez timers | warning leads the safe floor; wake window shown after it |
| Window placement | dragged, quit, restored — no compositor rules, on a Wayland session |
| AppImage self-update | an AppImage manager saw v0.3.2 and applied it |
| Live DPS during a fight | updates during combat, not only afterwards |

The skin check matters most. The skin is roughly 500 XML documents referencing
about 2,800 textures, and Linux filesystems are case-sensitive where Windows is
not, so any capitalisation mismatch Windows silently tolerates would have
surfaced as a missing texture or a window that refused to open. None did.

## Known limits

**Wayland gives clients no way to read or set an absolute window position.**
This is protocol design, not a bug, and it cannot be worked around in the
application:

- The alert and control surfaces are anchored to the seed on X11. On Wayland
  they neither follow it nor move.
- A window cannot raise itself above a fullscreen game.
- Click-through is unverified and likely unavailable.

The compositor can do all of this, which is why the windows are now
individually titled: one window rule per title, with position forced, places
every surface reliably. On an X11 session the application handles it natively
and no rules are needed.

**Forcing Chromium's X11 backend inside a Wayland session is not a workaround.**
It was tried. On KDE Wayland with the NVIDIA driver the GPU process fails to
`dlopen` `/usr/lib/gbm/dri_gbm.so`, segfaults repeatedly, and the window is
never mapped at all — a tray icon and nothing else. A visible application
without the overlay guarantees beats an invisible one that has them on paper.

## Not yet verified

Honest gaps, all requiring game time rather than code:

- The compact timer column of the Alt+Z panel. A real scan marked two raid
  completions correctly but reported the timer text unreadable and refused to
  guess an expiry. A second OCR pass now re-reads the located panel at 2x; it
  is written but unconfirmed, because it needs a scan while a lockout with a
  live timer is on screen.
- Lull timers and the weekly raid ledger from a live raid kill.
- A long session: stability, memory, and no orphaned engine process on quit.
- Overlay behaviour above a fullscreen game, and click-through. Both are X11
  capabilities and the application now runs on X11, so they are reachable —
  they simply have not been exercised.

`docs/LINUX_INGAME_TESTPLAN.md` covers these as a 30-check plan.

## New runtime dependencies on Linux

| Requirement | Needed for | Notes |
| --- | --- | --- |
| Python 3.10+ | the parser engine | stdlib only, no pip packages |
| X11 or XWayland | capture and overlays | Wayland sessions run the app fine; see limits |
| `tesseract` **and its English data** | the Alt+Z lockout scan only | optional; everything else works without it |

The language pack is worth calling out. Installing `tesseract` is not enough —
most distributions ship it without language data, so OCR fails while the binary
looks correctly installed. The application detects this at startup and names the
package (`tesseract-data-eng`, `tesseract-ocr-eng`, `tesseract-langpack-eng`).

## Two engine bugs found while testing, and fixed here

Both are cross-platform and predate this branch. They are included because
Linux testing is what surfaced them and the fixes are small and covered by
tests; split them out if you would rather take them separately.

- **A scanned completion left a confirmation prompt that could never be
  satisfied.** `import_instance_lockouts` recorded the completion but never
  cleared `pending_raid_target`, so after an Alt+Z scan marked Lady Vox
  complete the UI still asked for her difficulty. The scan is itself the
  confirmation, so it now clears the prompt for each target it records.
- **A second raid kill silently discarded the first.** `pending_raid_target`
  was a single string assigned on each qualifying kill, so killing two targets
  before confirming a difficulty overwrote the first — no prompt, no ledger
  entry, no message. That is most likely to happen on a raid night, which is
  when it matters. Pending kills are now an ordered queue, and confirming a
  difficulty resolves all of them.

The snapshot keeps `pendingRaidTarget` with its original meaning and adds
`pendingRaidTargets` beside it, so protocol v1 stays append-only and an older
renderer sees exactly what it saw before.

## Separate issues, not part of this branch

Raised as observations rather than changes, because they are cross-platform
product decisions:

- **The Windows Alt+Z scan is still framed on the mouse pointer**, and has the
  same latent flaw fixed here for Linux. Deliberately left alone.
- **Hover OCR and the Lore Lens are absent from the Electron application on
  every platform.** They exist only in the retired tkinter GUI, while the README
  still advertises an item companion and user-triggered screen OCR. The Linux
  backend already implements the hover capture path, so if that feature returns
  to the Electron app it will work on Linux without further porting.
- **Nothing enforces `Log=1` in `eqclient.ini`.** Loremaster is inert if the
  player has not enabled logging, and nothing says so.

## Known gaps in this work

- `HoverOcrService.backend_problem` is populated but never consumed, so a
  missing language pack surfaces on first scan rather than at startup.
- The installer places an AppImage but not a tar.gz; a tar.gz-only payload is
  reported honestly and skipped.
- `parse_instance_character` returned empty against a real panel capture.
  Harmless while the table is empty, unverified once it is not.
- The AppImage's embedded update information is not populated, so external
  AppImage managers cannot offer updates. `latest-linux.yml` is emitted.
