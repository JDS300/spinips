const assert = require("node:assert/strict");
const { createHash } = require("node:crypto");
const { existsSync, readFileSync, writeFileSync } = require("node:fs");
const { mkdtemp, mkdir, rm } = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");

const {
  acknowledgePortableUpdateRelaunch,
  PortableUpdateService,
  compareVersions,
  parseChecksums,
  portableUpdaterConstants,
  resolvePortableExecutable,
} = require("../dist-electron/portable-updater.js");

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function releaseJson(version, executable) {
  return {
    tag_name: `v${version}`,
    html_url: `https://github.com/itsspin/spinips/releases/tag/v${version}`,
    draft: false,
    prerelease: false,
    published_at: "2026-08-13T18:00:00Z",
    body: "A verified test release.",
    assets: [
      {
        name: "Loremaster.exe",
        browser_download_url: "https://github.com/itsspin/spinips/releases/download/v2.0.0/Loremaster.exe",
        size: executable.length,
        digest: `sha256:${sha256(executable)}`,
      },
      {
        name: "SHA256SUMS.txt",
        browser_download_url: "https://github.com/itsspin/spinips/releases/download/v2.0.0/SHA256SUMS.txt",
        size: 82,
        digest: `sha256:${"f".repeat(64)}`,
      },
    ],
  };
}

function responseFor(value, headers = {}) {
  return new Response(value, { status: 200, headers });
}

function fetchFixture(executable, checksum = sha256(executable)) {
  return async (input) => {
    const url = String(input);
    if (url === portableUpdaterConstants.releaseApi) {
      const body = JSON.stringify(releaseJson("2.0.0", executable));
      return responseFor(body, { "content-length": String(Buffer.byteLength(body)) });
    }
    if (url.endsWith("/SHA256SUMS.txt")) {
      return responseFor(`${checksum}  Loremaster.exe\n`, { "content-length": "82" });
    }
    if (url.endsWith("/Loremaster.exe")) {
      return responseFor(executable, { "content-length": String(executable.length) });
    }
    throw new Error(`Unexpected updater request: ${url}`);
  };
}

async function main() {
  assert.equal(compareVersions("1.2.3", "1.2.2"), 1);
  assert.equal(compareVersions("v1.2.3", "1.2.3"), 0);
  assert.equal(compareVersions("1.2.3-beta.2", "1.2.3-beta.10"), -1);
  assert.equal(compareVersions("1.2.3", "1.2.3-rc.1"), 1);
  assert.throws(() => compareVersions("nightly", "1.0.0"), /Unsupported release version/);

  const checksums = parseChecksums(`${"a".repeat(64)} *Loremaster.exe\r\n${"b".repeat(64)}  SpinUI-Manual.zip\r\n`);
  assert.equal(checksums.get("Loremaster.exe"), "a".repeat(64));
  assert.equal(checksums.get("SpinUI-Manual.zip"), "b".repeat(64));
  assert.throws(() => parseChecksums(`${"a".repeat(64)}  ../Loremaster.exe`), /unsafe asset name/);
  assert.throws(() => parseChecksums(`${"a".repeat(64)}  Loremaster.exe\n${"b".repeat(64)}  Loremaster.exe`), /Duplicate/);

  assert.equal(resolvePortableExecutable({ PORTABLE_EXECUTABLE_FILE: "relative.exe" }), null);
  assert.equal(resolvePortableExecutable({ PORTABLE_EXECUTABLE_FILE: "C:\\Apps\\Loremaster.exe" }), "C:\\Apps\\Loremaster.exe");
  assert.equal(resolvePortableExecutable({ PORTABLE_EXECUTABLE_FILE: "C:\\Apps\\Loremaster.zip" }), null);

  const workspace = await mkdtemp(path.join(os.tmpdir(), "loremaster-updater-test-"));
  try {
    const targetDir = path.join(workspace, "portable app");
    const userDataDir = path.join(workspace, "user data");
    await mkdir(targetDir, { recursive: true });
    const targetPath = path.join(targetDir, "Loremaster.exe");
    writeFileSync(targetPath, Buffer.from("MZold-build"));
    const executable = Buffer.concat([Buffer.from("MZ"), Buffer.alloc(4094, 0x5a)]);
    const progress = [];
    const service = new PortableUpdateService({
      currentVersion: "1.0.0",
      userDataDir,
      executablePath: targetPath,
      fetchImpl: fetchFixture(executable),
      minExecutableBytes: 32,
      maxExecutableBytes: 8192,
    });
    service.subscribe((value) => progress.push(value));
    const check = await service.check();
    assert.equal(check.ok, true);
    assert.equal(check.updateAvailable, true);
    assert.equal(check.latestVersion, "2.0.0");
    assert.equal(Object.hasOwn(check, "release"), false, "asset URLs must never be exposed to the renderer");

    const [staged, sameStaged] = await Promise.all([service.stage(), service.stage()]);
    assert.equal(staged.stagedPath, sameStaged.stagedPath, "concurrent downloads must coalesce");
    assert.deepEqual(readFileSync(staged.stagedPath), executable);
    assert.equal(existsSync(staged.helperPath), true);
    assert.match(readFileSync(staged.helperPath, "utf8"), /Get-FileHash/);
    assert.match(readFileSync(staged.helperPath, "utf8"), /Move-Item -LiteralPath \$target/);
    assert.equal(progress.at(-1).phase, "ready");

    const spawnCalls = [];
    const installService = new PortableUpdateService({
      currentVersion: "1.0.0",
      userDataDir,
      executablePath: targetPath,
      fetchImpl: fetchFixture(executable),
      minExecutableBytes: 32,
      maxExecutableBytes: 8192,
      spawnImpl: (command, args, options) => {
        const child = { pid: 4321, unrefCalled: false, unref() { this.unrefCalled = true; } };
        spawnCalls.push({ command, args, options, child });
        return child;
      },
    });
    assert.equal(installService.installAndRelaunch(staged, 1234), 4321);
    assert.equal(spawnCalls.length, 1);
    assert.match(spawnCalls[0].command, /System32\\WindowsPowerShell\\v1\.0\\powershell\.exe$/i);
    assert.equal(spawnCalls[0].args.includes("-NoProfile"), true);
    assert.equal(spawnCalls[0].args.includes("1234"), true);
    assert.equal(spawnCalls[0].args.includes("-HealthToken"), true);
    assert.equal(spawnCalls[0].options.detached, true);
    assert.equal(spawnCalls[0].options.windowsHide, true);
    assert.equal(spawnCalls[0].child.unrefCalled, true);

    await service.discard(staged);
    assert.equal(existsSync(path.dirname(staged.stagedPath)), false);

    const corrupt = new PortableUpdateService({
      currentVersion: "1.0.0",
      userDataDir: path.join(workspace, "corrupt-data"),
      executablePath: targetPath,
      fetchImpl: fetchFixture(executable, "0".repeat(64)),
      minExecutableBytes: 32,
      maxExecutableBytes: 8192,
    });
    const corruptCheck = await corrupt.check();
    await assert.rejects(() => corrupt.stage(), /asset digest and the release checksum manifest/);
    assert.equal(corrupt.getProgress().phase, "error");

    const redirectAttack = new PortableUpdateService({
      currentVersion: "1.0.0",
      userDataDir,
      executablePath: targetPath,
      fetchImpl: async () => new Response(null, {
        status: 302,
        headers: { location: "https://example.com/fake-release.json" },
      }),
    });
    const attacked = await redirectAttack.check();
    assert.equal(attacked.ok, false);
    assert.match(attacked.detail, /outside the official GitHub/);

    const currentService = new PortableUpdateService({
      currentVersion: "2.0.0",
      userDataDir,
      executablePath: targetPath,
      fetchImpl: fetchFixture(executable),
    });
    const current = await currentService.check();
    assert.equal(current.updateAvailable, false);
    assert.equal(currentService.getProgress().phase, "current");
    await assert.rejects(() => currentService.stage(), /Check for a newer official release/);

    const healthDir = path.join(userDataDir, "updates", "v2.0.0");
    await mkdir(healthDir, { recursive: true });
    const healthPath = path.join(healthDir, "ready.txt");
    const healthToken = "c".repeat(64);
    assert.equal(await acknowledgePortableUpdateRelaunch(userDataDir, [
      "Loremaster.exe", "--loremaster-update-health-token", healthToken,
      "--loremaster-update-health-path", healthPath,
    ]), true);
    assert.equal(readFileSync(healthPath, "ascii"), healthToken);
    assert.equal(await acknowledgePortableUpdateRelaunch(userDataDir, [
      "Loremaster.exe", "--loremaster-update-health-token", healthToken,
      "--loremaster-update-health-path", path.join(workspace, "escaped.txt"),
    ]), false);
  } finally {
    await rm(workspace, { recursive: true, force: true });
  }
  process.stdout.write("Portable updater tests: PASS\n");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
