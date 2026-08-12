# SpinUI manual installation

This package does not require the installer. It contains both complete skins:
the classic **Vellum & Ember** `spinui_reloaded` skin and the optional
**Midnight Frost** `spinui_glass` skin, plus Spin's Loremaster, the optional
character-layout profiles, and alternate chat presets. Seven validated screen
profiles cover 1920×1080, 2048×1080, 2560×1080, 2560×1440, 3440×1440,
3840×1600, and 3840×2160.

> **Safest layout option:** install either skin and keep your current
> character UI INI. Combat Focus, Social Focus, and Hybrid are
> optional full-file profiles: they replace the selected character UI file,
> including its window and chat preferences. Make a byte-exact backup before
> applying one so the original arrangement is easy to restore.

> **Antivirus note:** the unsigned `Loremaster.exe` can trip machine-learning
> heuristics (commonly `Wacatac!ml` or "suspicious PE"). Every release
> publishes a `SHA256SUMS.txt`; verify a download with
> `Get-FileHash -Algorithm SHA256 <file>` in PowerShell before restoring it
> from quarantine. The executable is built in public by GitHub Actions from
> the repository source.

## 1. Close EverQuest completely

EverQuest rewrites character UI files when it exits. Do not copy or replace an
INI while the game is running.

## 2. Install the skin

Choose **Vellum & Ember** (`spinui_reloaded`) or **Midnight Frost Glass**
(`spinui_glass`). You may install both and switch between them in game. For a
clean update, rename or remove the older folder with that same name first,
then copy the complete new folder into the game's `uifiles` folder. Do not
merge a release into an older skin tree; retired files can otherwise linger.
The final path should look like either or both of these:

```text
<EverQuest folder>\uifiles\spinui_reloaded\EQUI.xml
<EverQuest folder>\uifiles\spinui_glass\EQUI.xml
```

Common EverQuest folders include:

```text
C:\EQLegends
C:\Users\Public\Daybreak Game Company\Installed Games\EverQuest Legends
C:\Program Files (x86)\Steam\steamapps\common\EverQuest
```

In game, select the look you want with one of:

```text
/loadskin spinui_reloaded 1
/loadskin spinui_glass 1
```

The `1` preserves your current window positions. Both variants retain the
same ScreenIDs, EQTypes, resizable windows, Spell Ledger, and Extended Target
behavior, so changing skins does not require a different layout profile.

## 3. Optional: install a resolution profile

Skip this step if you want to keep your existing window arrangement. Otherwise
choose the exact resolution and chat emphasis under:

```text
layouts\profiles\<resolution>\<combat-focus|social-focus|hybrid>\
```

Do not apply a 3440×1440 character INI to a narrower screen; choose its
validated profile instead.

Copying one of the preset INIs over an existing character INI replaces that
whole file, including any chat/window preferences stored there. Before doing
so, make a separate backup of the character INI in the EverQuest folder. Its
name follows this pattern:

```text
UI_<Character>_<server>_LO1.ini
```

Choose `UI_Spin_qeynos_LO1.ini` from the matching resolution/preset folder.
Rename the selected file to match your character's **existing filename
exactly**, then copy it beside `eqgame.exe`. Detected layouts can use `LO2`,
`LO3`, and later slots; retain that existing suffix instead of forcing `LO1`.

For a genuinely new character target, preserve the character's capitalization
and use the canonical lowercase server token. New manual targets default to
`LO1`:

```text
UI_Spin_qeynos_LO1.ini
```

| Server shown in Legends | Filename token |
|---|---|
| Erudin (European) | `erudin` |
| Freeport | `freeport` |
| Halas | `halas` |
| Neriak | `neriak` |
| Oggok | `oggok` |
| Paineel (European) | `paineel` |
| Qeynos | `qeynos` |
| Rivervale | `rivervale` |

Before copying, verify that the destination filename matches the intended
character, server token, and existing layout suffix exactly. Never treat a
matching filename as permission to overwrite it without a backup.

## 4. Run Spin's Loremaster

Move `Loremaster.exe` anywhere you prefer, then run it. In EverQuest, type:

```text
/log on
```

Loremaster searches common Daybreak and Steam locations automatically. If it
does not find the active log, click **LOCATE LOG** and select the EverQuest
folder or its `Logs` folder.

Drag the compact HUD into place and click **LOCK**. In the detailed Encounter
Lab, **OLDER / NEWER / LIVE** browse encounters and **Overview / Damage /
Healing / Targets / Timeline** change the analysis. **CLICK-THRU** enables
click-through only if Loremaster successfully reserves the recovery shortcut;
press **Ctrl+Alt+L** at any time to restore interaction.

A small gold-and-cyan Loremaster icon remains in the Windows notification area
beside the clock, or in its **^** overflow drawer. Left-click it to restore and
focus the HUD. Right-click for **OPEN LOREMASTER**, **HIDE HUD**, or
**EXIT LOREMASTER**. Hiding keeps log tracking and the Lore Lens hotkey active;
Exit closes the program completely. A hidden state is never carried into the
next normal launch.

Hover an item in EverQuest and press **Ctrl+Shift+E**. Lore Lens opens beside
the cursor in a clear reading state, captures only that bounded cursor region,
and uses Windows OCR before validating likely titles as exact EQL Wiki item
pages. The hovered tooltip takes priority while EQ is foreground. A copied EQ
item link, bracketed item, or EQL Wiki URL is used if Hover Scan cannot identify
the title; ordinary clipboard text only prefills the search field until you
confirm it. The shortcut, Hover Scan, wiki network access, high-contrast
palette, reduced motion, and text scale are configurable through **SETTINGS**.
Lore Lens never injects into or reads memory from `eqgame.exe`.

To start Loremaster with Windows without showing it before the game launches,
create a shortcut in `shell:startup` whose target is:

```text
"C:\path\to\Loremaster.exe" --wait-for-eq
```

The waiting process remains hidden and uses a lightweight process check until
`eqgame.exe` starts. After Loremaster has opened, its notification-area icon
remains available whenever the HUD is hidden.

## 5. Linux / Wine (Proton, Lutris, native Wine)

EverQuest Legends runs under Wine or Proton on Linux; every path above is
inside that prefix's `drive_c`, not your Linux home directory. For example,
`C:\EQLegends` is `<prefix>/drive_c/EQLegends`, and a Steam Proton install is
usually under `~/.local/share/Steam/steamapps/compatdata/<appid>/pfx/drive_c/...`
or `~/.steam/steam/steamapps/compatdata/<appid>/pfx/drive_c/...`. A plain
Wine prefix defaults to `~/.wine/drive_c/...` (or `$WINEPREFIX/drive_c/...`
if you set one); Lutris prefixes are typically `~/Games/<title>/drive_c/...`.

Rather than translating every path above by hand, `spinui_installer.py`
supports a command-line mode that auto-detects these prefixes (including
Proton compatdata and Flatpak Steam) the same way it auto-detects native
Windows installs:

```sh
python3 installer/spinui_installer.py --install \
    --eq-dir "/path/to/prefix/drive_c/EQLegends" \
    --skin spinui_reloaded \
    --layout combat-focus --resolution 3440x1440 \
    --layout-target UI_Spin_qeynos_LO1.ini
```

Omit `--eq-dir` to let it search common Wine/Proton/Lutris locations
automatically; omit `--layout` to install the skin and Loremaster without
touching any character INI. Run `--list-presets` to see the available
layout, resolution, and skin choices, or `--dry-run` (implies `--install`)
to preview exactly what would change without writing anything. `--selftest`
runs the installer's own test suite and is safe to run on Linux at any time.

Loremaster itself is **not** run under Wine on Linux — it ships as a native
build (an AppImage, matched in the release payload as `Loremaster-*.AppImage`)
so it keeps the Linux OCR backend and stays fast. If that native build isn't
in the payload (for example, a plain source checkout with no release
artifacts), `--install` still installs the skin and reports the layout
result normally; it just skips Loremaster with an explicit message telling
you to grab the Linux build from the releases page, rather than silently
doing nothing or falling back to the Windows exe under Wine. `Loremaster.exe`
is only ever installed on Windows. When the native build is found,
`--desktop-shortcut` and `--startup-shortcut` write a freedesktop `.desktop`
entry (to your Desktop folder and `~/.config/autostart`, respectively) whose
`Exec=` points straight at the installed AppImage, instead of a Windows `.lnk`.

## Updating or removing

- Update the skin while EQ is closed by replacing the complete
  `spinui_reloaded` folder, not by merging the two versions.
- Remove the skin by deleting only `uifiles\spinui_reloaded` while EQ is closed.
- Restore your layout from the backup you made in step 3.
- Loremaster stores its configuration and character records in
  `%LOCALAPPDATA%\SpinsLoremaster` on Windows, or
  `$XDG_DATA_HOME/SpinsLoremaster` (defaulting to `~/.local/share/SpinsLoremaster`)
  on Linux.
