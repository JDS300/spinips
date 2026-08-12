# Linux in-game test plan

Everything in this document requires a real EverQuest Legends install under
Wine or Proton. None of it could be verified during development, because the
development machine has no EQ install — no `eqgame.exe` and no real
`eqlog_*.txt`. Automated coverage stops exactly where this document starts.

Work top to bottom. Each check states what to do, what should happen, and what
it means if it does not. Record the result in the box. If a check fails, the
note under it says whether to keep going or stop.

Environment recorded for this run:

| Field | Value |
| --- | --- |
| Distro / kernel | |
| Desktop + session (`echo $XDG_SESSION_TYPE $XDG_CURRENT_DESKTOP`) | |
| Wine or Proton version | |
| EQ install path | |
| Screen resolution | |
| Loremaster artifact (AppImage / tar.gz / source) | |

---

## Part 1 — Skin install (no Loremaster needed)

### 1.1 Auto-discovery finds your EQ install

```
python3 installer/spinui_installer.py --list-presets
```

**Expect:** the command prints available layout presets and exits 0.

☐ Pass ☐ Fail — notes:

### 1.2 Dry run reports the right target and writes nothing

```
python3 installer/spinui_installer.py --install --dry-run --layout combat-focus
```

**Expect:** it names *your* real EQ folder (inside your Wine/Proton prefix), the
skin it would install, and the layout INI it would touch. Nothing on disk
changes.

**If it cannot find your EQ folder:** this is the single most likely failure in
the whole port. Prefix discovery had no prior art to copy. Re-run with an
explicit `--eq-dir "/path/to/EverQuest Legends"`. If the explicit path works,
auto-discovery is the only broken part — record your prefix layout, it is a
one-line fix. Keep going either way.

☐ Pass ☐ Fail — notes:

### 1.3 Real install

Close EverQuest completely first — the installer refuses to write over a
running client, and that guard is protecting you from a corrupted UI.

```
python3 installer/spinui_installer.py --install --layout combat-focus
```

**Expect:** exit 0; a summary listing the installed skin path, the layout INI
applied, and a timestamped backup of your previous INI.

☐ Pass ☐ Fail — notes:

### 1.4 The running-client guard actually fires

Start EverQuest, get to the character select or in-game, then re-run the same
install command.

**Expect:** it refuses with a message telling you to close the client. It must
not write anything.

**Why this matters:** if this guard does not fire under Wine, the `/proc`-based
process detection is not seeing `eqgame.exe`, and a careless install could
corrupt UI files mid-session.

☐ Pass ☐ Fail — notes:

### 1.5 The client loads the skin

In game: `/loadskin spinui_reloaded 1`

**Expect:** the Vellum & Ember interface loads. The trailing `1` preserves your
window positions.

**This is the highest-value check in Part 1.** The skin is ~500 XML files and
~2800 textures. Linux filesystems are case-sensitive and Windows ones are not,
so any texture reference whose capitalisation disagrees with the actual filename
works on Windows and fails here. Missing or black textures, or windows that
refuse to open, are the symptom. The asset audits pass on Linux, which should
mean references resolve — this check is what proves it against the real client.

☐ Pass ☐ Fail — notes:

### 1.6 The other skin loads too

In game: `/loadskin spinui_glass 1`

**Expect:** Midnight Frost Glass loads, with translucent panes intact.

☐ Pass ☐ Fail — notes:

### 1.7 Layout is correct at your resolution

**Expect:** the HUD sits where the preset intends — nothing off-screen, no
overlapping HUD windows, chat readable, no clipped bars.

☐ Pass ☐ Fail — notes:

---

## Part 2 — Loremaster engine and log parsing

### 2.1 Logging is enabled in the client

In game: `/log on`. Confirm an `eqlog_<Character>_<server>.txt` file exists and
is growing.

**Loremaster is useless without this** and the app does not currently turn it on
for you. Do this before anything below.

☐ Pass ☐ Fail — notes:

### 2.2 Loremaster starts

Launch the AppImage (or `./loremaster` from the tar.gz, or from source per
`docs/LINUX.md`).

**Expect:** the window appears. No crash, no blank window.

☐ Pass ☐ Fail — notes:

### 2.3 It finds your log by itself

**Expect:** engine health reaches a **live** state without you choosing a
folder, having auto-discovered the log inside your Wine/Proton prefix.

**If it reports "searching" forever:** discovery missed your prefix. Use the
in-app folder chooser to point at your EQ or Logs folder — that path is a
first-class fallback and must work. Record which prefix layout you have.

☐ Pass ☐ Fail — notes:

### 2.4 Manual folder selection works

Even if 2.3 passed, use the in-app EverQuest folder chooser once and confirm it
takes effect and survives a restart.

☐ Pass ☐ Fail — notes:

### 2.5 Combat parses correctly

Kill several mobs.

**Expect:** kills register; fight and session DPS look plausible; your own
damage, charmed-pet damage and summoned-pet damage are attributed separately.

**Note:** the parser is platform-independent and has 281 passing tests, so a
failure here is far more likely to be log *discovery or encoding* than parsing
logic. Note the exact log line if something is misattributed.

☐ Pass ☐ Fail — notes:

### 2.6 Character switch and zoning

Camp to desktop, log in a different character, zone a few times.

**Expect:** Loremaster follows the newest character's log and keeps parsing;
zone changes are reflected.

☐ Pass ☐ Fail — notes:

### 2.7 Mez / lull timers

As a class with mez or lull, land one and watch the countdown.

**Expect:** a timer appears only with real landing evidence, shows a safe
remaining time, and marks its final tick. Harmony and Lull Animal produce an
honest `unconfirmed` notice and no countdown — that is deliberate, not a bug.

☐ Pass ☐ Fail — notes:

### 2.8 Charm break alert

Let a charm break.

**Expect:** a short danger banner. Unrelated buff fades stay silent.

☐ Pass ☐ Fail — notes:

### 2.9 Weekly raid ledger

If you kill any of the six tracked raid targets, confirm the ledger records it
under the right difficulty and that ordinary trash is never promoted.

☐ Pass ☐ Fail — notes:

---

## Part 3 — Overlay behaviour (the genuinely uncertain part)

These could not be tested during development at all. Input synthesis is
unavailable on this machine, and there was no game window to sit above.

### 3.0 Check gamescope first — read this before running Part 3

**If you launch EQ through gamescope, do this check first; it changes the
meaning of every result below.** In Lutris, look at your EverQuest Legends
configuration under System options.

gamescope is a *nested compositor*: the game renders inside gamescope's own
session rather than directly on your desktop. Loremaster's overlays are ordinary
windows on the host session, so they sit above or beside the gamescope window
rather than inside it. Two consequences:

- Overlays may still be **visible** above the gamescope window, since that window
  is just another window on your desktop.
- Click-through is much less likely to work, and `--force-grab-cursor` in
  particular tells gamescope to hold the pointer, which can prevent clicks from
  reaching either the overlay or the game.

**Run Part 3 twice.** First as you normally play. If anything in 3.1–3.4 fails,
turn gamescope off in Lutris and repeat. If it then works, the answer is
"gamescope and external overlays do not mix" — a configuration finding, not a
code defect, and worth recording rather than chasing.

☐ gamescope ON — used for the first pass
☐ gamescope OFF — used for the second pass
☐ N/A, not using gamescope

Notes:

### 3.1 Always-on-top over windowed EQ

Run EQ windowed. Put Loremaster over it and click on the EQ window.

**Expect:** Loremaster stays visible above EQ.

☐ Pass ☐ Fail — notes:

### 3.2 Always-on-top over fullscreen EQ

Now run EQ **fullscreen**.

**Expect:** Loremaster and its alert/control overlays remain visible above it.

**This is the check most likely to fail.** A comparable community tool holds
above this same game on Linux using nothing but ordinary window-manager
always-on-top, which is why we did not add extra machinery. If it fails here,
try EQ in borderless-windowed instead and record whether that fixes it — that
distinction tells us exactly what to change.

☐ Pass ☐ Fail (windowed) ☐ Fail (fullscreen only) — notes:

### 3.3 Click-through actually passes clicks to the game

With an alert or control overlay visible, click *through* it onto the game
underneath — ideally on something harmless like the ground.

**Expect:** the game receives the click. The overlay must not swallow it.

**Background:** Electron's `setIgnoreMouseEvents` carries no platform
restriction and implements this via an empty XFixes input-shape region on X11,
so it should work. Only mouse-move *forwarding* is Windows/macOS-only, which
means overlay hover effects may be inert on Linux — that is expected and
cosmetic, not this check failing.

☐ Pass ☐ Fail — notes:

### 3.4 Overlays do not steal focus

**Expect:** overlays appearing mid-fight never take keyboard focus from EQ. Your
keys keep going to the game.

**If this fails it is the most disruptive bug possible here** — stop and report
it before playing seriously.

☐ Pass ☐ Fail — notes:

### 3.5 Tray

Minimise Loremaster.

**Expect:** it goes to the system tray and clicking the tray icon restores it.

☐ Pass ☐ Fail — notes:

### 3.6 Multi-monitor and resolution changes

If you have more than one display, move Loremaster between them and confirm
overlays follow sanely. Change resolution once and confirm it re-asserts.

☐ Pass ☐ Fail ☐ N/A — notes:

---

## Part 4 — Hotkey and OCR

### 4.1 Global hotkey while EQ has focus

With EQ focused, press **Ctrl+Shift+Z**.

**Expect:** the instance-lockout scan triggers.

**If nothing happens:** on Wayland sessions a global hotkey may not reach the
app. The app deliberately treats registration failure as non-fatal. Confirm the
same action works from the in-app button — if the button works and the hotkey
does not, the feature is degraded but not broken.

☐ Pass ☐ Fail — notes:

### 4.2 Hover OCR reads an item tooltip

**Prerequisite — check this first.** Hover OCR needs tesseract *and* its English
language data. Having the `tesseract` binary is not enough, and this trips
people up because the tool appears installed while the feature cannot work.
Confirm `eng` appears in:

```
tesseract --list-langs
```

If it does not, install the language pack — `tesseract-data-eng` on Arch,
`tesseract-ocr-eng` on Debian/Ubuntu, `tesseract-langpack-eng` on Fedora. The
development machine hit exactly this: tesseract 5.5.3 present, but only `afr`
and `osd` data, so no English OCR was possible.

Hover an item in game so its tooltip shows, then trigger the hover scan.

**Expect:** the item name is read back correctly.

**Background:** the Linux path captures via X11 and OCRs with tesseract, and
verifies the captured window really belongs to `eqgame.exe` before reading. It
was verified against a non-EQ window with known text; EQ's actual tooltip font,
size and background contrast are unverified. Expect this to be the feature most
likely to need tuning. Note any misread characters — those inform the
confusion-variant table.

☐ Pass ☐ Fail — notes:

### 4.3 OCR refuses to capture non-EQ windows

Focus a non-EQ window and trigger a scan.

**Expect:** it refuses with a clear message rather than capturing your desktop.

**This is a privacy guarantee, not a nicety.** It must hold.

☐ Pass ☐ Fail — notes:

### 4.4 Instance lockout scan

Trigger the lockout scan with the relevant in-game window open.

**Expect:** lockouts are read and populate the ledger.

☐ Pass ☐ Fail — notes:

---

## Part 5 — Longevity

### 5.1 A full play session

Play normally for an hour or more with Loremaster running.

**Expect:** no crash, no runaway memory or CPU, no engine restart loop, parsing
still accurate at the end.

☐ Pass ☐ Fail — notes:

### 5.2 Clean shutdown

Quit Loremaster.

**Expect:** it exits and leaves no orphaned `python3` engine process behind.
Check with `pgrep -af desktop_worker` — it should return nothing.

☐ Pass ☐ Fail — notes:

---

## Reporting

For any failure, the most useful things to capture are: the check number, what
you saw, your session type (`echo $XDG_SESSION_TYPE`), whether EQ was
fullscreen/borderless/windowed, and for parsing issues the exact log line.
