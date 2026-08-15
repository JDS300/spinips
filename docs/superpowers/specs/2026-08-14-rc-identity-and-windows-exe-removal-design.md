# RC app identity, and dropping the Windows exe from releases

Date: 2026-08-14

Two independent changes to what a release publishes. They share three files
(`.github/workflows/build-loremaster.yml`, `tools/release_quality_gate.py`,
`CHANGELOG.md`), so they are specified together and shipped as two pull
requests that can be reverted separately.

## Part 1 — a release candidate installs alongside the live release

### Problem

Gear Lever refuses to hold both the RC and the live AppImage, because both
present the same identity: `productName: "Loremaster"` gives them the same
`Name=` and the root-level `desktopName: "loremaster.desktop"` gives them the
same desktop filename. Only one can be integrated at a time.

### What decides "this is an RC"

The version's semver prerelease component. The publish step already enforces
that a candidate carries one (`^v?\d+\.\d+\.\d+-`) and that a full release does
not, so this needs no new workflow input and cannot disagree with how the
release is actually published.

The Linux build step already derives `version` from `RELEASE_TAG`. When that
version contains a prerelease component, it layers extra `-c.` overrides onto
the `electron-builder` call.

### The overrides

| Override | Live | RC |
| --- | --- | --- |
| `extraMetadata.version` | tag | tag (unchanged behaviour) |
| `productName` | `Loremaster` | `Loremaster RC` |
| `extraMetadata.desktopName` | `loremaster.desktop` | `loremaster-rc.desktop` |
| `linux.executableName` | `loremaster` | `loremaster-rc` |
| `appId` | `com.spinui.loremaster` | `com.spinui.loremaster.rc` |
| `linux.artifactName` | `Loremaster-${version}-${arch}.${ext}` | `Loremaster-RC-${version}-${arch}.${ext}` |

`package.json` is not edited. A local `pnpm dist:linux` and every full release
keep producing exactly what they produce today; the RC identity exists only as
build-time overrides on a candidate build.

### Why `desktopName` must be overridden, not just `executableName`

`app-builder-lib`'s `LinuxTargetHelper.getDesktopFileName()` (26.15.7) reads
`metadata.desktopName` and only falls back to `executableName` when it is
empty. The same value becomes `StartupWMClass`, which Electron uses as its
app_id for window association. Overriding `executableName` alone would leave
the entry named `loremaster.desktop` and the collision unfixed.

`desktopName` lives at the top level of `package.json`, so it is reached
through `extraMetadata`, not through a `-c.linux.*` key.

Verified against
`node_modules/.pnpm/app-builder-lib@26.15.7_*/node_modules/app-builder-lib/out/targets/LinuxTargetHelper.js`
lines 184-200 and 226-250.

### Shared settings are the default, and must stay that way

Electron derives `userData` from `package.json` `name`, which is
`spins-loremaster` — confirmed on disk at `~/.config/spins-loremaster`,
holding `desktop-settings.json`. `productName` lives under `build` and never
reaches the packaged metadata, so renaming the product does **not** move the
data directory.

The RC therefore shares the live settings directory with no runtime code at
all. No `app.setPath("userData", ...)` call is needed, and none should be
added.

**Constraint:** the RC overrides must never set `extraMetadata.name` or
`extraMetadata.productName`. Either one would move `userData` and silently
split the config, which is the opposite of the intent. This is the one way
this design can be broken by a later well-meaning edit.

### First-launch backup

Shared settings mean an RC can damage live config. Before anything can write,
an RC build snapshots the state files.

- **Trigger:** `app.getVersion()` has a prerelease component. A dev run
  (`0.3.4`) and a live release both fail this, so the path is inert outside a
  candidate build. On Windows it is harmless and equally applicable.
- **Destination:** `<appData>/spins-loremaster-rc-backups/<version>/` — a
  sibling of the live directory, so the RC never writes inside the thing it is
  protecting, and deleting a corrupted config does not take the backups with
  it.
- **Once per release:** the destination directory's existence is the marker.
  Present means skip. The snapshot therefore captures the config as it stood
  before that candidate first ran, and a later launch cannot overwrite it with
  already-damaged state.
- **Contents:** `desktop-settings.json`, `update-center.json`,
  `spinui-update-receipts.json`, `eq-legends-tools-gear-cache.json`. Files that
  do not exist are skipped rather than raising. Regenerable data
  (`item-intelligence/`, `updates/`, Electron's own caches) is deliberately
  excluded — it is large, slow to copy, and rebuilt automatically.
- **Synchronous**, because the payload is a few kilobytes and it removes any
  chance of the app racing its own backup.
- **Never blocks launch:** wrapped so a failure is logged and startup
  continues. A backup that cannot be written must not stop the app.
- **Retention:** keep every snapshot. A few kilobytes per candidate does not
  justify pruning logic. Recovery is a manual copy back.

### Structure and tests

The copy logic goes in its own module with injectable paths, mirroring how
`portable-updater.ts` is structured, with `scripts/test-rc-backup.cjs` in the
style of the existing `test:updates` and `test:skin-updates` scripts. It runs
against `dist-electron/` like its siblings and is added to the desktop
verification step.

Cases: skips when the snapshot directory already exists; tolerates missing
source files; survives an unwritable destination without throwing; copies only
the four named files.

### Release notes

The Installing section names `Loremaster-$version-x86_64.AppImage`, which is
wrong for a candidate. That line becomes conditional so a prerelease names
`Loremaster-RC-$version-x86_64.AppImage`.

### Shell detail

`linux.artifactName` contains `${version}` and `${arch}`, which are
electron-builder templates, not shell variables. The override must be single
quoted in the workflow so bash does not expand them to empty strings.

## Part 2 — the Windows exe stops being published

### Intent

The Windows executable should not be downloadable from this repository. The
skins are staying: `spinui-updater.ts` fetches `SpinUI-UI.zip` and
`SpinUI-Update.json` from this repo's latest release, and that updater ships in
the Linux build, so removing them would break a working feature for Linux
users.

### The exe leaks from four places

1. Published as the standalone asset `dist-electron-release/Loremaster.exe`.
2. **Copied into `SpinUI-Manual.zip`** (`Copy-Item -Force
   dist-electron-release/Loremaster.exe $manualPackage`). Removing only the
   standalone asset would still ship the exe inside the manual bundle.
3. Hashed into `SHA256SUMS.txt`.
4. Named in the release notes' Installing section.

All four go.

`SHA256SUMS.txt` itself stays — it still covers `SpinUI-Manual.zip`,
`SpinUI-UI.zip` and `SpinUI-Update.json`, which continue to be published.

### CI keeps building it

`build-loremaster` still compiles and tests the Windows executable on every
qualifying run, so a shared-code change that breaks the Windows build still
fails CI. Only the publishing steps change. `package-windows-release` no longer
needs to download the `Loremaster-Windows` artifact to assemble the manual
bundle.

### The quality gate inverts

`tools/release_quality_gate.py` currently *requires* the exe, and will fail
this change until it is updated:

- `COMMON_PACKAGE_TOP_LEVEL` asserts `Loremaster.exe` is in the manual package.
  The same check also fails on unexpected top-level entries, so the set and the
  package must move together.
- The workflow self-audit requires the literals
  `dist-electron-release/Loremaster.exe` and `Copy-Item -Force
  dist-electron-release/Loremaster.exe $manualPackage`.

Those assertions move from `required` to `retired`, next to `LoremasterNext.exe`
and `dist/Loremaster.exe`. The gate then fails if the exe ever returns to the
release path, which is what makes this survive the next upstream sync instead
of being quietly undone by it.

### Documentation

`README.md` (6 references), `installer/INSTALL-MANUAL.md` (which ships inside
the manual bundle, so it must not instruct people to run a file that is no
longer there), and `docs/RELEASING.md`.

### Known fallout, accepted

`portable-updater.ts` looks for a `Loremaster.exe` asset on the latest release
and will throw when it finds none, so anyone already running the Windows build
sees an update error rather than a clean "no longer published" message.
Accepted deliberately: nobody should be running that build from this repo.
Not scoped into this work.

## Sequencing

Two pull requests, each independently revertable:

1. RC identity and first-launch backup.
2. Windows exe removal.

Both need a `CHANGELOG.md` entry under `0.4.0`, since `tools/release_notes.py`
reads that entry to build the release notes and resolves a candidate to the
entry for the release it is promoted to.

## Out of scope

- Any change to the skin assets or the skin updater.
- A graceful end-of-life message in the Windows portable updater.
- Repointing or disabling the Linux portable updater (a separate open question
  already tracked).
- Pruning old RC backups.
