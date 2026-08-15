# RC App Identity and Windows Exe Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a release candidate install beside the live release in Gear Lever, and stop publishing the Windows executable from this repository.

**Architecture:** A candidate is identified by the semver prerelease component already enforced at publish time. When present, the Linux build step layers `-c.` overrides onto `electron-builder` to give the candidate its own desktop identity; `package.json` is never edited, so live builds are untouched. A candidate shares the live settings directory (that is the default, not something arranged) and snapshots the state files on first launch. Separately, the Windows executable is removed from every published path while still being built and tested in CI.

**Tech Stack:** GitHub Actions (bash + PowerShell steps), electron-builder 26.15.7, Electron 43, TypeScript (Node16 modules, strict), Node `node:test`-free assertion scripts using `node:assert/strict`, Python 3.12 for the release quality gate.

## Global Constraints

- **Never override `extraMetadata.name` or `extraMetadata.productName`.** `userData` derives from `package.json` `name` (`spins-loremaster`, live at `~/.config/spins-loremaster`). Setting either would move the candidate's data directory and silently split the config, defeating the shared-settings intent.
- `package.json` is not edited for RC identity. All candidate differences are build-time `-c.` overrides.
- `-c.linux.artifactName` must be **single quoted** in bash: `${version}`, `${arch}` and `${ext}` are electron-builder templates, and bash would expand them to empty strings.
- A candidate carries a semver prerelease component; a full release does not. The publish step already enforces this. Detection regex, matching the workflow's own charset: `^[0-9]+\.[0-9]+\.[0-9]+-[0-9A-Za-z.-]+$`.
- The RC backup must never block startup. Any failure is logged and swallowed.
- The skin assets (`SpinUI-UI.zip`, `SpinUI-Update.json`, `SpinUI-Manual.zip`) and `SHA256SUMS.txt` keep being published. Only the Windows executable goes.
- `tools/release_quality_gate.py` audits the workflow's own text. Workflow edits and gate edits that concern the same literal **must land in the same commit**, or the tree is red between commits.
- Verification command for the whole repo: `python3 tools/release_quality_gate.py` (~23s, currently ALL PASS).

---

## Phase 1 — PR 1: RC app identity and first-launch backup

Branch: `feat/rc-app-identity` (already exists, carries the spec commit).

### Task 1: RC backup module

**Files:**
- Create: `loremaster-desktop/electron/rc-backup.ts`
- Create: `loremaster-desktop/scripts/test-rc-backup.cjs`
- Modify: `loremaster-desktop/package.json` (scripts block)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `isReleaseCandidateVersion(version: string): boolean`, `backupBeforeReleaseCandidate(request: RcBackupRequest): RcBackupResult`, and the constant `RC_BACKUP_FILES: readonly string[]`. `RcBackupRequest` is `{ version: string; userDataDir: string; backupRoot: string }`. `RcBackupResult` is a discriminated union on `status`: `{ status: "skipped"; reason: "not-a-candidate" | "already-backed-up" }`, `{ status: "created"; directory: string; files: string[] }`, `{ status: "failed"; error: string }`. Task 2 consumes `backupBeforeReleaseCandidate` only.

- [ ] **Step 1: Add the test script entry**

In `loremaster-desktop/package.json`, add to `"scripts"` immediately after `"test:skin-updates"`:

```json
    "test:rc-backup": "node scripts/test-rc-backup.cjs"
```

- [ ] **Step 2: Write the failing test**

Create `loremaster-desktop/scripts/test-rc-backup.cjs`:

```js
const assert = require("node:assert/strict");
const { existsSync, mkdirSync, readFileSync, writeFileSync } = require("node:fs");
const { mkdtemp, rm } = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");

const {
  RC_BACKUP_FILES,
  backupBeforeReleaseCandidate,
  isReleaseCandidateVersion,
} = require("../dist-electron/rc-backup.js");

function seedUserData(root) {
  mkdirSync(root, { recursive: true });
  writeFileSync(path.join(root, "desktop-settings.json"), '{"live":true}');
  writeFileSync(path.join(root, "update-center.json"), '{"seen":1}');
  // spinui-update-receipts.json and eq-legends-tools-gear-cache.json are
  // deliberately absent: a fresh install has neither, and that must not raise.
}

async function withTempDir(run) {
  const dir = await mkdtemp(path.join(os.tmpdir(), "rc-backup-"));
  try {
    await run(dir);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

async function testVersionDetection() {
  assert.equal(isReleaseCandidateVersion("0.4.0-rc.1"), true);
  assert.equal(isReleaseCandidateVersion("0.4.0"), false);
  assert.equal(isReleaseCandidateVersion("0.3.4"), false);
  // Build metadata is not a prerelease component.
  assert.equal(isReleaseCandidateVersion("0.4.0+build.5"), false);
  // A version that could escape the backup root is not a candidate.
  assert.equal(isReleaseCandidateVersion("0.4.0-../../etc"), false);
  assert.equal(isReleaseCandidateVersion(""), false);
  console.log("  version detection: PASS");
}

async function testSkipsFullRelease() {
  await withTempDir(async (dir) => {
    const userDataDir = path.join(dir, "userdata");
    const backupRoot = path.join(dir, "backups");
    seedUserData(userDataDir);
    const result = backupBeforeReleaseCandidate({
      version: "0.4.0",
      userDataDir,
      backupRoot,
    });
    assert.deepEqual(result, { status: "skipped", reason: "not-a-candidate" });
    assert.equal(existsSync(backupRoot), false, "a full release must not create a backup root");
  });
  console.log("  skips a full release: PASS");
}

async function testCopiesOnlyExistingStateFiles() {
  await withTempDir(async (dir) => {
    const userDataDir = path.join(dir, "userdata");
    const backupRoot = path.join(dir, "backups");
    seedUserData(userDataDir);
    // Regenerable data must not be copied.
    mkdirSync(path.join(userDataDir, "item-intelligence"), { recursive: true });
    writeFileSync(path.join(userDataDir, "item-intelligence", "cache.bin"), "x");

    const result = backupBeforeReleaseCandidate({
      version: "0.4.0-rc.1",
      userDataDir,
      backupRoot,
    });

    assert.equal(result.status, "created");
    assert.equal(result.directory, path.join(backupRoot, "0.4.0-rc.1"));
    assert.deepEqual(result.files, ["desktop-settings.json", "update-center.json"]);
    assert.equal(
      readFileSync(path.join(result.directory, "desktop-settings.json"), "utf8"),
      '{"live":true}',
    );
    assert.equal(existsSync(path.join(result.directory, "item-intelligence")), false);
    assert.equal(existsSync(path.join(result.directory, "spinui-update-receipts.json")), false);
  });
  console.log("  copies only existing state files: PASS");
}

async function testSnapshotIsTakenOnce() {
  await withTempDir(async (dir) => {
    const userDataDir = path.join(dir, "userdata");
    const backupRoot = path.join(dir, "backups");
    seedUserData(userDataDir);

    const first = backupBeforeReleaseCandidate({
      version: "0.4.0-rc.1",
      userDataDir,
      backupRoot,
    });
    assert.equal(first.status, "created");

    // The candidate has now damaged the live config.
    writeFileSync(path.join(userDataDir, "desktop-settings.json"), '{"corrupt":true}');

    const second = backupBeforeReleaseCandidate({
      version: "0.4.0-rc.1",
      userDataDir,
      backupRoot,
    });
    assert.deepEqual(second, { status: "skipped", reason: "already-backed-up" });
    assert.equal(
      readFileSync(path.join(first.directory, "desktop-settings.json"), "utf8"),
      '{"live":true}',
      "the pre-candidate snapshot must survive a later launch",
    );
  });
  console.log("  snapshot is taken once per version: PASS");
}

async function testEachCandidateGetsItsOwnSnapshot() {
  await withTempDir(async (dir) => {
    const userDataDir = path.join(dir, "userdata");
    const backupRoot = path.join(dir, "backups");
    seedUserData(userDataDir);

    const first = backupBeforeReleaseCandidate({
      version: "0.4.0-rc.1",
      userDataDir,
      backupRoot,
    });
    const second = backupBeforeReleaseCandidate({
      version: "0.4.0-rc.2",
      userDataDir,
      backupRoot,
    });

    assert.equal(first.status, "created");
    assert.equal(second.status, "created");
    assert.notEqual(first.directory, second.directory);
    assert.equal(existsSync(path.join(backupRoot, "0.4.0-rc.1")), true);
    assert.equal(existsSync(path.join(backupRoot, "0.4.0-rc.2")), true);
  });
  console.log("  each candidate gets its own snapshot: PASS");
}

async function testFailureNeverThrows() {
  await withTempDir(async (dir) => {
    const userDataDir = path.join(dir, "userdata");
    seedUserData(userDataDir);
    // A file where the backup root should be: mkdir cannot succeed here.
    const backupRoot = path.join(dir, "blocked");
    writeFileSync(backupRoot, "not a directory");

    const result = backupBeforeReleaseCandidate({
      version: "0.4.0-rc.1",
      userDataDir,
      backupRoot,
    });
    assert.equal(result.status, "failed");
    assert.equal(typeof result.error, "string");
    assert.ok(result.error.length > 0);
  });
  console.log("  an unwritable destination never throws: PASS");
}

async function testBackupFileListIsTheStateFiles() {
  assert.deepEqual([...RC_BACKUP_FILES], [
    "desktop-settings.json",
    "update-center.json",
    "spinui-update-receipts.json",
    "eq-legends-tools-gear-cache.json",
  ]);
  console.log("  backup file list: PASS");
}

async function main() {
  console.log("rc backup:");
  await testVersionDetection();
  await testBackupFileListIsTheStateFiles();
  await testSkipsFullRelease();
  await testCopiesOnlyExistingStateFiles();
  await testSnapshotIsTakenOnce();
  await testEachCandidateGetsItsOwnSnapshot();
  await testFailureNeverThrows();
  console.log("rc backup: ALL PASS");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
cd loremaster-desktop && pnpm build && pnpm test:rc-backup
```

Expected: FAIL — `Cannot find module '../dist-electron/rc-backup.js'`.

- [ ] **Step 4: Write the implementation**

Create `loremaster-desktop/electron/rc-backup.ts`:

```ts
import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import path from "node:path";

// The files holding state a candidate can damage. Regenerable data
// (item-intelligence/, updates/, Electron's own caches) is deliberately
// absent: it is large, slow to copy, and rebuilt on demand.
export const RC_BACKUP_FILES = [
  "desktop-settings.json",
  "update-center.json",
  "spinui-update-receipts.json",
  "eq-legends-tools-gear-cache.json",
] as const;

export interface RcBackupRequest {
  version: string;
  userDataDir: string;
  backupRoot: string;
}

export type RcBackupResult =
  | { status: "skipped"; reason: "not-a-candidate" | "already-backed-up" }
  | { status: "created"; directory: string; files: string[] }
  | { status: "failed"; error: string };

// Mirrors the charset the publish step enforces on a release tag, so a
// candidate is recognised here exactly when it was published as one. Requiring
// the full string to match also keeps the version usable as a directory name:
// nothing with a separator in it can reach the filesystem.
const RELEASE_CANDIDATE_VERSION = /^\d+\.\d+\.\d+-[0-9A-Za-z.-]+$/;

export function isReleaseCandidateVersion(version: string): boolean {
  return RELEASE_CANDIDATE_VERSION.test(version.trim());
}

// A candidate shares the live settings directory on purpose, so it snapshots
// the state files before it can write to them. The snapshot lives beside that
// directory rather than inside it, so the candidate never writes into the
// thing it is protecting and deleting a ruined config keeps the backups.
export function backupBeforeReleaseCandidate(request: RcBackupRequest): RcBackupResult {
  const version = request.version.trim();
  if (!isReleaseCandidateVersion(version)) {
    return { status: "skipped", reason: "not-a-candidate" };
  }

  const directory = path.join(request.backupRoot, version);
  try {
    // The directory's presence is the marker, so a later launch cannot
    // overwrite the pre-candidate snapshot with already-damaged state.
    if (existsSync(directory)) {
      return { status: "skipped", reason: "already-backed-up" };
    }
    mkdirSync(directory, { recursive: true });

    const files: string[] = [];
    for (const name of RC_BACKUP_FILES) {
      const source = path.join(request.userDataDir, name);
      // A fresh install has none of these, which is not a failure.
      if (!existsSync(source)) {
        continue;
      }
      copyFileSync(source, path.join(directory, name));
      files.push(name);
    }
    return { status: "created", directory, files };
  } catch (error) {
    return {
      status: "failed",
      error: error instanceof Error ? error.message : String(error),
    };
  }
}
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd loremaster-desktop && pnpm build && pnpm test:rc-backup
```

Expected: PASS, ending `rc backup: ALL PASS`.

- [ ] **Step 6: Commit**

```bash
git add loremaster-desktop/electron/rc-backup.ts loremaster-desktop/scripts/test-rc-backup.cjs loremaster-desktop/package.json
git commit -m "Snapshot the settings a release candidate is about to share"
```

### Task 2: Wire the backup into startup

**Files:**
- Modify: `loremaster-desktop/electron/main.ts` (imports at line 1-31; new block after the ozone relaunch guard that ends at line 77)

**Interfaces:**
- Consumes: `backupBeforeReleaseCandidate` from Task 1.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Add the import**

In `loremaster-desktop/electron/main.ts`, add after the `./portable-updater` import block (which ends at line 23) and before the `./spinui-updater` import block, keeping the existing alphabetical-by-module grouping:

```ts
import { backupBeforeReleaseCandidate } from "./rc-backup";
```

- [ ] **Step 2: Add the startup block**

Insert immediately after the closing `}` of the ozone relaunch guard (line 77), before the `// Which backend is actually running` comment:

```ts
// A candidate shares the live settings directory on purpose -- bugs surface
// against real data that way -- so it snapshots the state files before any
// code can write to them. Runs before app.whenReady on purpose: both paths
// resolve this early, and nothing has opened a settings file yet.
{
  const backup = backupBeforeReleaseCandidate({
    version: app.getVersion(),
    userDataDir: app.getPath("userData"),
    backupRoot: path.join(app.getPath("appData"), "spins-loremaster-rc-backups"),
  });
  if (backup.status === "created") {
    console.info(
      `[Loremaster] release candidate: backed up ${backup.files.length}`
      + ` settings file(s) to ${backup.directory}`);
  } else if (backup.status === "failed") {
    // Logged, never fatal: a backup that cannot be written must not stop the
    // application from starting.
    console.warn(`[Loremaster] release candidate backup failed: ${backup.error}`);
  }
}
```

- [ ] **Step 3: Verify it compiles and the suite still passes**

```bash
cd loremaster-desktop && pnpm build && pnpm test:rc-backup && pnpm test:fixtures && pnpm test:gear
```

Expected: PASS for all four. `pnpm build` runs `tsc -p tsconfig.electron.json && tsc --noEmit && vite build`, so a type error in the new block fails here.

- [ ] **Step 4: Verify a normal run is unaffected**

```bash
cd loremaster-desktop && node -e "console.log(require('./dist-electron/rc-backup.js').isReleaseCandidateVersion(require('./package.json').version))"
```

Expected: `false` — the checked-in version is not a candidate, so a dev run and a live release never touch the backup path.

- [ ] **Step 5: Commit**

```bash
git add loremaster-desktop/electron/main.ts
git commit -m "Take the candidate snapshot before anything can write settings"
```

### Task 3: Give a candidate its own desktop identity in CI

**Files:**
- Modify: `.github/workflows/build-loremaster.yml:377-380` (Linux desktop verification step), `:396-405` (Linux electron-builder invocation), `:560-570` (release notes Installing section)

**Interfaces:**
- Consumes: `test:rc-backup` script from Task 1.
- Produces: RC AppImage named `Loremaster-RC-<version>-x86_64.AppImage`, consumed by the release notes text in this same task.

- [ ] **Step 1: Add the new test to both desktop verification steps**

In the Windows job's step (line 241), append after `pnpm test:skin-updates`:

```yaml
          pnpm test:rc-backup
```

In the Linux job's step (line 380), append after `pnpm test:gear`:

```yaml
          pnpm test:rc-backup
```

- [ ] **Step 2: Replace the Linux electron-builder invocation**

Replace the `run:` body of the "Build Linux Electron artifacts" step (lines 396-405) with:

```yaml
        run: |
          set -euo pipefail
          version="${RELEASE_TAG#v}"
          if ! printf '%s' "$version" \
            | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+([-+][0-9A-Za-z.-]+)?$'; then
            version="$(node -p "require('./package.json').version")"
          fi
          # A candidate has to install beside the live release rather than
          # replace it. Gear Lever keys on the desktop entry, so productName
          # (Name=) and desktopName (the .desktop filename, and StartupWMClass)
          # both have to differ -- app-builder-lib reads desktopName first and
          # only falls back to executableName, so overriding executableName
          # alone leaves the entry named loremaster.desktop and the collision
          # unfixed. desktopName sits at the top level of package.json, which
          # is why it goes through extraMetadata rather than -c.linux.
          #
          # name is deliberately never overridden: userData comes from it, and
          # a candidate shares the live settings on purpose so bugs surface
          # against real data.
          identity=()
          if printf '%s' "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+-'; then
            identity=(
              "-c.productName=Loremaster RC"
              "-c.appId=com.spinui.loremaster.rc"
              "-c.extraMetadata.desktopName=loremaster-rc.desktop"
              "-c.linux.executableName=loremaster-rc"
              # Single quoted: these are electron-builder templates, and bash
              # would expand them to empty strings.
              '-c.linux.artifactName=Loremaster-RC-${version}-${arch}.${ext}'
            )
            echo "building release candidate identity: Loremaster RC ($version)"
          fi
          pnpm build
          pnpm exec electron-builder --linux AppImage tar.gz --x64 \
            --publish never "-c.extraMetadata.version=$version" "${identity[@]}"
```

- [ ] **Step 3: Make the release notes name the file that exists**

In the "Publish workflow-dispatch release" step, immediately after the line `$version = $tag -replace '^v', ''` (line 552), add:

```powershell
          # A candidate ships under its own name so it can sit beside the live
          # release, so the notes have to point at that file, not the other one.
          $appImage = if ($prerelease) {
            "Loremaster-RC-$version-x86_64.AppImage"
          } else {
            "Loremaster-$version-x86_64.AppImage"
          }
```

Then replace the Linux line in the `$notes` array (line 564):

```powershell
            "**Linux** -- download ``$appImage``, ``chmod +x`` it, and run it. There is no self-update on Linux, so new builds always come from this page.",
```

- [ ] **Step 4: Verify the workflow still parses and the gate passes**

```bash
python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/build-loremaster.yml')); print('yaml ok')"
python3 tools/release_quality_gate.py
```

Expected: `yaml ok`, then `RELEASE QUALITY GATE: ALL PASS`. The gate's required literal `-c.extraMetadata.version=$version` is preserved verbatim by Step 2, so this must stay green.

- [ ] **Step 5: Verify the override list is shell-correct**

Nested quoting makes this unreliable to paste inline, so write it to a file first:

```bash
cat > /tmp/rc-identity-check.sh <<'SCRIPT'
set -euo pipefail
version="$1"
identity=()
if printf '%s' "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+-'; then
  identity=(
    "-c.productName=Loremaster RC"
    "-c.appId=com.spinui.loremaster.rc"
    "-c.extraMetadata.desktopName=loremaster-rc.desktop"
    "-c.linux.executableName=loremaster-rc"
    '-c.linux.artifactName=Loremaster-RC-${version}-${arch}.${ext}'
  )
fi
printf '%s\n' "${identity[@]}"
echo "exit-ok"
SCRIPT
bash /tmp/rc-identity-check.sh 0.4.0-rc.1
echo "--- full release ---"
bash /tmp/rc-identity-check.sh 0.4.0
```

Expected: for `0.4.0-rc.1`, five override lines then `exit-ok`, with the last override reading exactly `-c.linux.artifactName=Loremaster-RC-${version}-${arch}.${ext}` — braces intact and unexpanded. For `0.4.0`, only `exit-ok`, which proves the empty-array expansion is safe under `set -u`.

Copy the array block into the workflow from this verified file, so the quoting that passed the test is the quoting that ships.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/build-loremaster.yml
git commit -m "Build a release candidate under its own name"
```

### Task 4: Changelog entry for the candidate identity

**Files:**
- Modify: `CHANGELOG.md` (under the `## 0.4.0` heading)

**Interfaces:**
- Consumes: nothing.
- Produces: the entry `tools/release_notes.py` reads when publishing `0.4.0` or any `0.4.0-rc.N`.

- [ ] **Step 1: Add the entry**

Add to the fork section under `## 0.4.0`, matching the surrounding bold-lead-in style:

```markdown
- **Release candidates install beside the release** — a candidate now builds as
  "Loremaster RC" with its own desktop entry, so a tool like Gear Lever can hold
  it and the live release at the same time instead of treating them as one app.
  It shares the live settings on purpose, so bugs show up against real data, and
  it copies those settings aside once per candidate before it can touch them.
```

- [ ] **Step 2: Verify the extractor still resolves both forms**

```bash
python3 tools/release_notes.py --version v0.4.0 | head -5
python3 tools/release_notes.py --version v0.4.0-rc.1 | head -5
python3 tools/release_notes.py --self-test
```

Expected: the first two print the same `0.4.0` entry; the self-test prints `ALL PASS`.

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "Say that candidates now install beside the release"
```

### Task 5: Phase 1 verification and pull request

- [ ] **Step 1: Full gate**

```bash
python3 tools/release_quality_gate.py
```

Expected: `RELEASE QUALITY GATE: ALL PASS`.

- [ ] **Step 2: Full desktop suite**

```bash
cd loremaster-desktop && pnpm install --frozen-lockfile && pnpm test:fixtures && pnpm build && pnpm test:gear && pnpm test:items && pnpm test:updates && pnpm test:skin-updates && pnpm test:rc-backup
```

Expected: every script passes.

- [ ] **Step 3: Open the pull request**

```bash
git push -u origin feat/rc-app-identity
gh pr create --title "Let a release candidate install beside the release" --body "$(cat <<'EOF'
Gear Lever holds one entry per app identity, and a candidate presented the same one as the live release: same `productName`, same `desktopName`. Only one could be integrated at a time.

A candidate now builds as **Loremaster RC** with its own desktop entry, application id, executable name and AppImage filename. These are build-time overrides only — `package.json` is untouched, so local builds and full releases are unchanged.

`userData` comes from `package.json` `name`, not `productName`, so a candidate shares the live settings directory by default. That is deliberate: bugs surface against real data. To make it safe, an RC snapshots the four settings files to `spins-loremaster-rc-backups/<version>/` on first launch, once per candidate, and never blocks startup if that fails.

Note for future edits: overriding `extraMetadata.name` or `extraMetadata.productName` would move `userData` and silently split the config. The plan and spec both record this.

Spec: `docs/superpowers/specs/2026-08-14-rc-identity-and-windows-exe-removal-design.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Phase 2 — PR 2: the Windows executable stops being published

Branch off `main` **after PR 1 merges**: `git checkout main && git pull && git checkout -b fix/stop-publishing-windows-exe`.

### Task 6: Remove the executable from every published path

The workflow edits and the gate edits **must be one commit**. The gate requires two literals that this task deletes, so splitting them leaves the tree red in between.

**Files:**
- Modify: `.github/workflows/build-loremaster.yml:456-460` (artifact download), `:462-473` (manual assembly), `:486-500` (checksums), `:511-519` (tools upload), `:541-547` (publish asset list), `:566-568` (release notes Windows paragraph)
- Modify: `tools/release_quality_gate.py:218-227` (`COMMON_PACKAGE_TOP_LEVEL`), `:330-355` (`required`), `:357-362` (`retired`)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: releases carrying only `SpinUI-Manual.zip`, `SpinUI-UI.zip`, `SpinUI-Update.json`, `SHA256SUMS.txt` and the Linux assets.

- [ ] **Step 1: Confirm the current gate assertions fail-first**

Delete just the manual-package copy line (workflow line 473, `Copy-Item -Force dist-electron-release/Loremaster.exe $manualPackage`) and run:

```bash
python3 tools/release_quality_gate.py 2>&1 | grep -A2 "Electron release pipeline"
```

Expected: FAIL — `Electron release workflow is incomplete: Copy-Item -Force dist-electron-release/Loremaster.exe $manualPackage`. This proves the gate genuinely guards this path before you invert it.

- [ ] **Step 2: Remove the artifact download step**

Delete this step entirely (lines 456-460) — `package-windows-release` no longer needs the executable:

```yaml
      - name: Download verified Loremaster component
        uses: actions/download-artifact@v6
        with:
          name: Loremaster-Windows
          path: package/loremaster-component
```

The `Loremaster-Windows` artifact is still produced by the `build-loremaster` job's upload step, which is what keeps the gate's `"Loremaster-Windows"` required literal satisfied and keeps the Windows build verified in CI.

- [ ] **Step 3: Stop embedding the executable in the manual bundle**

Step 1 already deleted the last of these. In the "Assemble staged manual release" step, delete the two that remain:

```powershell
          New-Item -ItemType Directory -Force -Path dist-electron-release | Out-Null
          Copy-Item -Force package/loremaster-component/Loremaster.exe dist-electron-release/Loremaster.exe
```

The step now ends at the `Expand-Archive` line. Confirm with:

```bash
grep -n "Loremaster.exe" .github/workflows/build-loremaster.yml
```

Expected at this point: only the `$assets` entry, the checksum `foreach` entry, the tools-upload path, and the release-notes Windows paragraph — all removed in Steps 4-6.

- [ ] **Step 4: Stop hashing the executable**

In the "Publish SHA-256 checksums" step, remove `'dist-electron-release/Loremaster.exe'` from the `foreach` list, leaving:

```powershell
          $lines = foreach ($file in @(
              'package/SpinUI-Manual.zip',
              'package/SpinUI-UI.zip',
              'package/SpinUI-Update.json')) {
```

- [ ] **Step 5: Stop uploading and publishing it**

In "Upload complete Windows tools and checksums", delete the line `            dist-electron-release/Loremaster.exe` from `path:`.

In "Publish workflow-dispatch release", remove the last entry from `$assets` so it reads:

```powershell
          $assets = @(
            'package/SpinUI-Manual.zip',
            'package/SpinUI-UI.zip',
            'package/SpinUI-Update.json',
            'package/SHA256SUMS.txt'
          )
```

- [ ] **Step 6: Remove the Windows paragraph from the release notes**

Delete these two lines from the `$notes` array:

```powershell
            "",
            "**Windows** -- ``Loremaster.exe`` is the portable build. It is unsigned, so antivirus machine-learning heuristics sometimes flag it; see the README's Troubleshooting section.",
```

Then change the checksum sentence, which still names a Windows download, to:

```powershell
            "Check what you downloaded against ``Loremaster-Linux-SHA256SUMS.txt`` (Linux) or ``SHA256SUMS.txt`` (skins).",
```

- [ ] **Step 7: Invert the gate**

In `tools/release_quality_gate.py`, remove `"Loremaster.exe",` from `COMMON_PACKAGE_TOP_LEVEL` (line 227).

Remove these two entries from the `required` tuple:

```python
        "dist-electron-release/Loremaster.exe",
        "Copy-Item -Force dist-electron-release/Loremaster.exe $manualPackage",
```

Add them to the `retired` tuple, which becomes:

```python
    retired = (
        "LoremasterNext.exe",
        "dist/Loremaster.exe",
        "--specpath build/spec loremaster/loremaster.py",
        "LOREMASTER-NEXT-SHA256.txt",
        # The Windows executable is built and tested in CI but never published:
        # it is this repository's code compiled for a platform the fork does
        # not test, and nobody should be installing it from here. Retired
        # rather than deleted so an upstream sync cannot quietly restore it.
        "dist-electron-release/Loremaster.exe",
        "Copy-Item -Force dist-electron-release/Loremaster.exe $manualPackage",
    )
```

Update the failure message on the `retired` check so it still reads true — it currently says "legacy/preview GUI":

```python
    if present:
        fail("release workflow publishes a retired artifact: " + ", ".join(present))
```

- [ ] **Step 8: Verify the gate now passes and guards the other direction**

```bash
python3 tools/release_quality_gate.py
```

Expected: `RELEASE QUALITY GATE: ALL PASS`.

Then prove the guard bites. Temporarily re-add the copy line to the workflow, re-run the gate, and confirm it FAILS with `release workflow publishes a retired artifact: dist-electron-release/Loremaster.exe, Copy-Item ...`. Remove it again and confirm ALL PASS.

- [ ] **Step 9: Verify the workflow still parses**

```bash
python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/build-loremaster.yml')); print('yaml ok')"
```

Expected: `yaml ok`.

- [ ] **Step 10: Commit**

```bash
git add .github/workflows/build-loremaster.yml tools/release_quality_gate.py
git commit -m "Stop publishing the Windows executable"
```

### Task 7: Documentation

**Files:**
- Modify: `README.md:377`, `:397`, `:405`, `:423`, `:492`
- Modify: `installer/INSTALL-MANUAL.md:16`, `:112`, `:149`, `:193`
- Modify: `docs/RELEASING.md:70`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing.

`installer/INSTALL-MANUAL.md` ships **inside** `SpinUI-Manual.zip`, so it must not tell a reader to run a file that is no longer in the archive. That is the highest-priority file here.

- [ ] **Step 1: Read each reference in context**

```bash
grep -n -B3 -A3 "Loremaster.exe" README.md installer/INSTALL-MANUAL.md docs/RELEASING.md
```

- [ ] **Step 2: Rewrite each reference**

Apply this rule per site, preserving the surrounding voice:

- Instructions to **run or download** `Loremaster.exe` from a release (README 377, 397, 423; INSTALL-MANUAL 112, 149): rewrite for the Linux AppImage, which is what the release now carries. Where a step only makes sense on Windows, say the executable is not published from this repository and must be built from source.
- The **antivirus/SmartScreen** notes (README 405; INSTALL-MANUAL 16): these describe downloading an unsigned exe from the releases page, which no longer happens. Remove them, and drop `Get-FileHash` guidance that refers to verifying that download.
- **Descriptions of what a release contains** (README 492; RELEASING 70): state that CI builds and tests the Windows executable but does not publish it.
- INSTALL-MANUAL 193 is prose about Wine fallback that mentions the exe — reword to match, since a reader can no longer obtain it here.

- [ ] **Step 3: Verify no stale instruction survives**

```bash
grep -rn "Loremaster.exe" README.md installer/ docs/ | grep -vi "not published\|built from source\|does not publish"
```

Expected: no output, or only lines you can justify as accurate.

- [ ] **Step 4: Run the gate**

```bash
python3 tools/release_quality_gate.py
```

Expected: ALL PASS. The gate checks required README showcase media and file identity, so a careless edit surfaces here.

- [ ] **Step 5: Commit**

```bash
git add README.md installer/INSTALL-MANUAL.md docs/RELEASING.md
git commit -m "Stop telling people to download an executable this repo no longer ships"
```

### Task 8: Changelog entry and pull request

**Files:**
- Modify: `CHANGELOG.md` (under `## 0.4.0`)

- [ ] **Step 1: Add the entry**

```markdown
- **The Windows executable is no longer published here** — releases carry the
  Linux build and the skins. The executable is still built and tested on every
  run, so a change that breaks it is still caught, but it is not offered for
  download from this fork. Anyone already running the Windows build will see
  its updater fail rather than find a new one.
```

- [ ] **Step 2: Verify the extractor**

```bash
python3 tools/release_notes.py --version v0.4.0 | head -20
python3 tools/release_notes.py --self-test
```

Expected: the entry appears; self-test prints `ALL PASS`.

- [ ] **Step 3: Final verification**

```bash
python3 tools/release_quality_gate.py
```

Expected: `RELEASE QUALITY GATE: ALL PASS`.

- [ ] **Step 4: Commit and open the pull request**

```bash
git add CHANGELOG.md
git commit -m "Say the Windows executable is no longer published"
git push -u origin fix/stop-publishing-windows-exe
gh pr create --title "Stop publishing the Windows executable" --body "$(cat <<'EOF'
The Windows executable should not be downloadable from this fork. It leaked out of four places, not one — the standalone release asset, a copy **inside `SpinUI-Manual.zip`**, the `SHA256SUMS.txt` listing, and the release notes. Removing only the standalone asset would still have shipped it inside the manual bundle.

The skins stay published: `spinui-updater.ts` fetches `SpinUI-UI.zip` and `SpinUI-Update.json` from this repo's latest release, and that updater ships in the Linux build.

CI still builds and tests the executable on every qualifying run, so a shared-code change that breaks the Windows build still fails. Only publishing changed.

The quality gate's assertions moved from `required` to `retired`, so it now fails if the executable ever returns to the release path — which is what stops the next upstream sync from quietly undoing this.

**Known fallout, accepted:** `portable-updater.ts` looks for a `Loremaster.exe` asset and will throw when it finds none, so anyone already running the Windows build sees an update error rather than a clean end-of-life message. Not scoped into this work.

Spec: `docs/superpowers/specs/2026-08-14-rc-identity-and-windows-exe-removal-design.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## What this plan does not verify

The RC identity overrides cannot be fully proven locally — `electron-builder --linux` on this machine builds an AppImage, but the published naming and the `.desktop` contents are only truly confirmed by a real candidate build. After PR 1 merges, the first `workflow_dispatch` with a `-rc.1` tag should be checked for:

- an asset named `Loremaster-RC-<version>-x86_64.AppImage`
- `Name=Loremaster RC` and `StartupWMClass=loremaster-rc` inside the AppImage's `loremaster-rc.desktop`
- Gear Lever accepting it alongside the live entry
- `~/.config/spins-loremaster-rc-backups/<version>/` appearing on first launch, with the live settings unmoved

If a local dry run is wanted first, `pnpm exec electron-builder --linux AppImage --x64 --publish never` with the same override list produces the file to inspect without touching a release.
