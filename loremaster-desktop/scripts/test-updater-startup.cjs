// Startup guard: constructing the update services must never throw, on any
// platform. main.ts calls initializeUpdateServices() synchronously inside
// app.whenReady(), before createWindow() and ensureTray(). A constructor that
// throws there takes the window and the tray icon down with it, and the only
// symptom is an UnhandledPromiseRejectionWarning in a log nobody reads.
const assert = require("node:assert/strict");
const { mkdtemp, rm } = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");

const { PortableUpdateService } = require("../dist-electron/portable-updater.js");
const { SpinUISkinUpdateService } = require("../dist-electron/spinui-updater.js");

async function withTempDir(run) {
  const dir = await mkdtemp(path.join(os.tmpdir(), "updater-startup-"));
  try {
    await run(dir);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

// A Linux/macOS process has neither of the variables the Windows PowerShell
// lookup needs. Clear them explicitly so this test proves the same thing when
// it runs on a Windows CI runner.
function withoutWindowsEnvironment(run) {
  const saved = { SystemRoot: process.env.SystemRoot, WINDIR: process.env.WINDIR };
  delete process.env.SystemRoot;
  delete process.env.WINDIR;
  try {
    return run();
  } finally {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }
}

async function testPortableUpdaterConstructs() {
  await withTempDir(async (dir) => {
    withoutWindowsEnvironment(() => {
      const service = new PortableUpdateService({
        currentVersion: "0.4.0",
        userDataDir: dir,
        executablePath: null,
      });
      assert.ok(service, "the portable updater must construct without Windows");
      assert.equal(typeof service.subscribe, "function");
    });
  });
  console.log("  portable updater constructs without Windows PowerShell: PASS");
}

async function testSkinUpdaterConstructs() {
  await withTempDir(async (dir) => {
    withoutWindowsEnvironment(() => {
      const service = new SpinUISkinUpdateService({ userDataDir: dir, eqRoot: null });
      assert.ok(service, "the skin updater must construct without Windows");
    });
  });
  console.log("  skin updater constructs without Windows PowerShell: PASS");
}

async function testStartupSequenceSurvives() {
  // The exact shape main.ts uses: build both services back to back and let any
  // throw escape, the way it would inside app.whenReady().
  await withTempDir(async (dir) => {
    withoutWindowsEnvironment(() => {
      assert.doesNotThrow(() => {
        const portable = new PortableUpdateService({
          currentVersion: "0.4.0",
          userDataDir: dir,
          executablePath: null,
        });
        portable.subscribe(() => {});
        const skins = new SpinUISkinUpdateService({ userDataDir: dir, eqRoot: null });
        skins.subscribe(() => {});
      }, "initializeUpdateServices must not throw during startup");
    });
  });
  console.log("  full startup sequence does not throw: PASS");
}

async function main() {
  console.log("updater startup:");
  await testPortableUpdaterConstructs();
  await testSkinUpdaterConstructs();
  await testStartupSequenceSurvives();
  console.log("updater startup: ALL PASS");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
