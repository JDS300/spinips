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
