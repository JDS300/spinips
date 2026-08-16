import { spawn, type ChildProcess } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import { createWriteStream, existsSync, statSync } from "node:fs";
import { mkdir, open, rename, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { once } from "node:events";

const RELEASE_API = "https://api.github.com/repos/JDS300/spinips/releases/latest";
const RELEASE_PAGE = "https://github.com/JDS300/spinips/releases/latest";
const LOREMASTER_ASSET = "Loremaster.exe";
const CHECKSUM_ASSET = "SHA256SUMS.txt";
const MAX_RELEASE_BYTES = 2 * 1024 * 1024;
const MAX_CHECKSUM_BYTES = 1024 * 1024;
const MAX_EXECUTABLE_BYTES = 300 * 1024 * 1024;
const MIN_EXECUTABLE_BYTES = 1024 * 1024;
const MAX_REDIRECTS = 5;
const INACTIVITY_TIMEOUT_MS = 30_000;

const OFFICIAL_DOWNLOAD_HOSTS = new Set([
  "api.github.com",
  "github.com",
  "objects.githubusercontent.com",
  "release-assets.githubusercontent.com",
]);

export type UpdatePhase =
  | "idle"
  | "checking"
  | "current"
  | "available"
  | "downloading"
  | "verifying"
  | "ready"
  | "installing"
  | "error";

export interface UpdateProgress {
  phase: UpdatePhase;
  percent: number;
  detail: string;
  version?: string;
  bytesReceived?: number;
  totalBytes?: number;
}

export interface ReleaseAsset {
  name: string;
  url: string;
  size: number;
  sha256: string;
}

export interface PortableRelease {
  version: string;
  tag: string;
  releaseUrl: string;
  publishedAt: string;
  notes: string;
  executable: ReleaseAsset;
  checksums: ReleaseAsset;
}

export interface UpdateCheckResult {
  ok: boolean;
  currentVersion: string;
  latestVersion: string;
  updateAvailable: boolean;
  releaseUrl: string;
  detail: string;
}

export interface StagedPortableUpdate {
  version: string;
  targetPath: string;
  stagedPath: string;
  expectedSha256: string;
  helperPath: string;
  healthPath: string;
  healthToken: string;
  releaseUrl: string;
}

export interface PortableUpdaterOptions {
  currentVersion: string;
  userDataDir: string;
  executablePath?: string | null;
  fetchImpl?: typeof fetch;
  spawnImpl?: typeof spawn;
  minExecutableBytes?: number;
  maxExecutableBytes?: number;
  powershellPath?: string;
}

type ProgressListener = (progress: UpdateProgress) => void;

function boundedPercent(value: number): number {
  return Math.max(0, Math.min(100, Math.round(value)));
}

function normalizeVersion(value: string): string {
  return value.trim().replace(/^v/i, "");
}

/** Compares release versions without adding an update-time runtime dependency. */
export function compareVersions(left: string, right: string): number {
  const parse = (raw: string) => {
    const match = normalizeVersion(raw).match(
      /^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$/,
    );
    if (!match) throw new Error(`Unsupported release version: ${raw}`);
    return {
      core: [Number(match[1]), Number(match[2]), Number(match[3])],
      prerelease: match[4]?.split(".") ?? [],
    };
  };
  const a = parse(left);
  const b = parse(right);
  for (let index = 0; index < 3; index += 1) {
    if (a.core[index] !== b.core[index]) return a.core[index] > b.core[index] ? 1 : -1;
  }
  if (!a.prerelease.length && !b.prerelease.length) return 0;
  if (!a.prerelease.length) return 1;
  if (!b.prerelease.length) return -1;
  const length = Math.max(a.prerelease.length, b.prerelease.length);
  for (let index = 0; index < length; index += 1) {
    const av = a.prerelease[index];
    const bv = b.prerelease[index];
    if (av === undefined) return -1;
    if (bv === undefined) return 1;
    if (av === bv) continue;
    const an = /^\d+$/.test(av) ? Number(av) : null;
    const bn = /^\d+$/.test(bv) ? Number(bv) : null;
    if (an !== null && bn !== null) return an > bn ? 1 : -1;
    if (an !== null) return -1;
    if (bn !== null) return 1;
    return av > bv ? 1 : -1;
  }
  return 0;
}

export function parseChecksums(text: string): Map<string, string> {
  const checksums = new Map<string, string>();
  for (const rawLine of text.replace(/^\uFEFF/, "").split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const match = line.match(/^([0-9a-fA-F]{64})\s+\*?(.+)$/);
    if (!match) throw new Error("The release checksum manifest is malformed.");
    const name = match[2].trim().replace(/\\/g, "/");
    if (!name || name.includes("/") || name === "." || name === "..") {
      throw new Error("The release checksum manifest contains an unsafe asset name.");
    }
    if (checksums.has(name)) throw new Error(`Duplicate checksum entry for ${name}.`);
    checksums.set(name, match[1].toLowerCase());
  }
  return checksums;
}

export function resolvePortableExecutable(
  environment: NodeJS.ProcessEnv = process.env,
): string | null {
  const candidate = environment.PORTABLE_EXECUTABLE_FILE?.trim();
  if (!candidate || !path.isAbsolute(candidate) || path.extname(candidate).toLowerCase() !== ".exe") {
    return null;
  }
  return path.normalize(candidate);
}

function validateOfficialUrl(value: string): URL {
  const url = new URL(value);
  if (url.protocol !== "https:" || !OFFICIAL_DOWNLOAD_HOSTS.has(url.hostname.toLowerCase())) {
    throw new Error("The release redirected outside the official GitHub download service.");
  }
  if (url.username || url.password) throw new Error("Authenticated release URLs are not accepted.");
  return url;
}

async function fetchOfficial(
  fetchImpl: typeof fetch,
  input: string,
  init: RequestInit,
): Promise<Response> {
  let url = validateOfficialUrl(input);
  for (let redirects = 0; redirects <= MAX_REDIRECTS; redirects += 1) {
    const response = await fetchImpl(url, { ...init, redirect: "manual" });
    if (response.status < 300 || response.status >= 400) return response;
    const location = response.headers.get("location");
    if (!location) throw new Error("GitHub returned a redirect without a destination.");
    if (redirects === MAX_REDIRECTS) throw new Error("The release download redirected too many times.");
    url = validateOfficialUrl(new URL(location, url).toString());
  }
  throw new Error("The release download could not be resolved.");
}

async function readNextChunk(
  reader: ReadableStreamDefaultReader<Uint8Array>,
): Promise<ReadableStreamReadResult<Uint8Array>> {
  let timer: NodeJS.Timeout | undefined;
  try {
    return await Promise.race([
      reader.read(),
      new Promise<never>((_resolve, reject) => {
        timer = setTimeout(
          () => reject(new Error("The release download stopped responding.")),
          INACTIVITY_TIMEOUT_MS,
        );
        timer.unref?.();
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

async function readLimitedBytes(response: Response, maximum: number): Promise<Uint8Array> {
  const declared = Number(response.headers.get("content-length") ?? "0");
  if (Number.isFinite(declared) && declared > maximum) throw new Error("The release response is unexpectedly large.");
  if (!response.body) throw new Error("GitHub returned an empty release response.");
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  while (true) {
    const { done, value } = await readNextChunk(reader);
    if (done) break;
    total += value.byteLength;
    if (total > maximum) {
      await reader.cancel();
      throw new Error("The release response exceeded its safe size limit.");
    }
    chunks.push(value);
  }
  const joined = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    joined.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return joined;
}

function safeReleaseAsset(value: unknown): ReleaseAsset | null {
  if (!value || typeof value !== "object") return null;
  const asset = value as Record<string, unknown>;
  const name = typeof asset.name === "string" ? asset.name : "";
  const url = typeof asset.browser_download_url === "string" ? asset.browser_download_url : "";
  const size = typeof asset.size === "number" && Number.isFinite(asset.size) ? asset.size : 0;
  const digest = typeof asset.digest === "string" ? asset.digest.toLowerCase() : "";
  const digestMatch = digest.match(/^sha256:([0-9a-f]{64})$/);
  if (!name || !url || size < 0 || !digestMatch) return null;
  validateOfficialUrl(url);
  return { name, url, size, sha256: digestMatch[1] };
}

function releaseFromApi(value: unknown): PortableRelease {
  if (!value || typeof value !== "object") throw new Error("GitHub returned invalid release metadata.");
  const source = value as Record<string, unknown>;
  if (source.draft === true || source.prerelease === true) {
    throw new Error("The latest GitHub response is not a stable public release.");
  }
  const tag = typeof source.tag_name === "string" ? source.tag_name.trim() : "";
  const version = normalizeVersion(tag);
  compareVersions(version, version);
  const assets = Array.isArray(source.assets) ? source.assets.map(safeReleaseAsset).filter(Boolean) as ReleaseAsset[] : [];
  const exactAsset = (name: string) => {
    const matches = assets.filter((asset) => asset.name === name);
    if (matches.length !== 1) throw new Error(`Release must contain exactly one ${name} asset.`);
    return matches[0];
  };
  const releaseUrl = typeof source.html_url === "string" ? source.html_url : RELEASE_PAGE;
  validateOfficialUrl(releaseUrl);
  return {
    version,
    tag,
    releaseUrl,
    publishedAt: typeof source.published_at === "string" ? source.published_at : "",
    notes: typeof source.body === "string" ? source.body.slice(0, 16_384) : "",
    executable: exactAsset(LOREMASTER_ASSET),
    checksums: exactAsset(CHECKSUM_ASSET),
  };
}

function safeStageName(version: string): string {
  compareVersions(version, version);
  return `v${version.replace(/[^0-9A-Za-z.+-]/g, "-")}`;
}

function ensureTargetExecutable(value: string | null | undefined): string {
  if (!value || !path.isAbsolute(value) || path.extname(value).toLowerCase() !== ".exe") {
    throw new Error("This build is not running from a supported portable Loremaster executable.");
  }
  const normalized = path.normalize(value);
  if (!existsSync(normalized) || !statSync(normalized).isFile()) {
    throw new Error("The portable Loremaster executable could not be found.");
  }
  return normalized;
}

function resolveWindowsPowerShell(environment: NodeJS.ProcessEnv = process.env): string {
  const windowsRoot = environment.SystemRoot || environment.WINDIR;
  if (!windowsRoot || !path.isAbsolute(windowsRoot)) {
    throw new Error("The trusted Windows PowerShell location could not be resolved.");
  }
  const executable = path.join(windowsRoot, "System32", "WindowsPowerShell", "v1.0", "powershell.exe");
  if (!existsSync(executable)) throw new Error("Windows PowerShell is unavailable for portable replacement.");
  return executable;
}

async function assertTargetDirectoryWritable(targetPath: string): Promise<void> {
  const probe = path.join(
    path.dirname(targetPath),
    `.loremaster-update-write-test-${process.pid}-${randomBytes(6).toString("hex")}`,
  );
  try {
    await writeFile(probe, "Loremaster update permission probe\n", { encoding: "utf8", flag: "wx" });
  } catch {
    throw new Error("Loremaster cannot update this folder. Move it to a user-writable folder or run it with matching permissions.");
  } finally {
    await rm(probe, { force: true }).catch(() => undefined);
  }
}

export async function acknowledgePortableUpdateRelaunch(
  userDataDir: string,
  argv: readonly string[] = process.argv,
): Promise<boolean> {
  const tokenIndex = argv.indexOf("--loremaster-update-health-token");
  const pathIndex = argv.indexOf("--loremaster-update-health-path");
  if (tokenIndex < 0 || pathIndex < 0) return false;
  const token = argv[tokenIndex + 1] ?? "";
  const healthPath = argv[pathIndex + 1] ?? "";
  if (!/^[0-9a-f]{64}$/i.test(token) || !path.isAbsolute(healthPath)) return false;
  const updatesRoot = path.resolve(userDataDir, "updates");
  const resolvedHealth = path.resolve(healthPath);
  const relative = path.relative(updatesRoot, resolvedHealth);
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) return false;
  await mkdir(path.dirname(resolvedHealth), { recursive: true });
  const temporary = `${resolvedHealth}.${process.pid}.tmp`;
  await writeFile(temporary, token, { encoding: "ascii", flag: "wx" });
  await rename(temporary, resolvedHealth);
  return true;
}

async function writeVerifiedDownload(
  response: Response,
  destination: string,
  expectedSha256: string,
  expectedBytes: number,
  maximumBytes: number,
  onProgress: (received: number, total: number) => void,
): Promise<number> {
  if (!response.ok) throw new Error(`GitHub returned HTTP ${response.status} while downloading ${path.basename(destination)}.`);
  if (!response.body) throw new Error("GitHub returned an empty update download.");
  const declared = Number(response.headers.get("content-length") ?? "0");
  if (Number.isFinite(declared) && declared > maximumBytes) throw new Error("The update executable is unexpectedly large.");
  if (declared > 0 && declared !== expectedBytes) throw new Error("The update size differs from GitHub release metadata.");
  const temporary = `${destination}.part`;
  await rm(temporary, { force: true });
  const output = createWriteStream(temporary, { flags: "wx" });
  const digest = createHash("sha256");
  let received = 0;
  try {
    const reader = response.body.getReader();
    while (true) {
      const { done, value } = await readNextChunk(reader);
      if (done) break;
      received += value.byteLength;
      if (received > maximumBytes) {
        await reader.cancel();
        throw new Error("The update executable exceeded its safe size limit.");
      }
      digest.update(value);
      if (!output.write(value)) await once(output, "drain");
      onProgress(received, declared > 0 ? declared : 0);
    }
    output.end();
    await once(output, "close");
    if (received !== expectedBytes) throw new Error("The update download was incomplete.");
    const actual = digest.digest("hex");
    if (actual !== expectedSha256.toLowerCase()) {
      throw new Error("The downloaded Loremaster checksum did not match the release manifest.");
    }
    await rm(destination, { force: true });
    await rename(temporary, destination);
    return received;
  } catch (error) {
    output.destroy();
    await rm(temporary, { force: true }).catch(() => undefined);
    throw error;
  }
}

async function assertPortableExecutable(filePath: string, minimumBytes: number, maximumBytes: number): Promise<void> {
  const file = await open(filePath, "r");
  try {
    const info = await file.stat();
    if (info.size < minimumBytes || info.size > maximumBytes) {
      throw new Error("The staged Loremaster executable has an unexpected size.");
    }
    const header = Buffer.alloc(2);
    const result = await file.read(header, 0, 2, 0);
    if (result.bytesRead !== 2 || header[0] !== 0x4d || header[1] !== 0x5a) {
      throw new Error("The staged update is not a Windows executable.");
    }
  } finally {
    await file.close();
  }
}

function replacementScript(): string {
  return String.raw`param(
  [Parameter(Mandatory=$true)][string]$TargetPath,
  [Parameter(Mandatory=$true)][string]$StagedPath,
  [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ExpectedSha256,
  [Parameter(Mandatory=$true)][string]$HealthPath,
  [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$HealthToken,
  [Parameter(Mandatory=$true)][int]$ParentPid
)
$ErrorActionPreference = 'Stop'
$target = [IO.Path]::GetFullPath($TargetPath)
$staged = [IO.Path]::GetFullPath($StagedPath)
if ([IO.Path]::GetExtension($target) -ine '.exe' -or [IO.Path]::GetExtension($staged) -ine '.exe') {
  throw 'Updater paths must point to Windows executables.'
}
$deadline = [DateTime]::UtcNow.AddSeconds(90)
while ((Get-Process -Id $ParentPid -ErrorAction SilentlyContinue) -and [DateTime]::UtcNow -lt $deadline) {
  Start-Sleep -Milliseconds 250
}
if (Get-Process -Id $ParentPid -ErrorAction SilentlyContinue) { throw 'Loremaster did not close before the update timeout.' }
if (-not (Test-Path -LiteralPath $target -PathType Leaf)) { throw 'Installed Loremaster executable was not found.' }
if (-not (Test-Path -LiteralPath $staged -PathType Leaf)) { throw 'Staged Loremaster update was not found.' }
$actual = (Get-FileHash -LiteralPath $staged -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $ExpectedSha256.ToLowerInvariant()) { throw 'Staged Loremaster checksum changed before installation.' }
$backup = "$target.previous"
$newTarget = "$target.new"
$replaceDeadline = [DateTime]::UtcNow.AddSeconds(90)
$replaced = $false
while (-not $replaced -and [DateTime]::UtcNow -lt $replaceDeadline) {
  try {
    Remove-Item -LiteralPath $newTarget -Force -ErrorAction SilentlyContinue
    Copy-Item -LiteralPath $staged -Destination $newTarget -Force
    Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue
    Move-Item -LiteralPath $target -Destination $backup -Force
    Move-Item -LiteralPath $newTarget -Destination $target -Force
    $replaced = $true
  } catch {
    Remove-Item -LiteralPath $newTarget -Force -ErrorAction SilentlyContinue
    if (-not (Test-Path -LiteralPath $target) -and (Test-Path -LiteralPath $backup)) {
      Move-Item -LiteralPath $backup -Destination $target -Force
    }
    Start-Sleep -Milliseconds 500
  }
}
if (-not $replaced) { throw 'The portable wrapper did not release Loremaster.exe before the update timeout.' }
Remove-Item -LiteralPath $HealthPath -Force -ErrorAction SilentlyContinue
$next = Start-Process -FilePath $target -WorkingDirectory ([IO.Path]::GetDirectoryName($target)) -ArgumentList @('--loremaster-update-health-token', $HealthToken, '--loremaster-update-health-path', $HealthPath) -PassThru
$healthDeadline = [DateTime]::UtcNow.AddSeconds(75)
$healthy = $false
while (-not $healthy -and [DateTime]::UtcNow -lt $healthDeadline -and -not $next.HasExited) {
  if (Test-Path -LiteralPath $HealthPath -PathType Leaf) {
    $healthy = ((Get-Content -LiteralPath $HealthPath -Raw).Trim() -eq $HealthToken)
  }
  if (-not $healthy) { Start-Sleep -Milliseconds 250 }
}
if (-not $healthy) {
  if (-not $next.HasExited) { Stop-Process -Id $next.Id -Force -ErrorAction SilentlyContinue }
  $rollbackDeadline = [DateTime]::UtcNow.AddSeconds(45)
  $rolledBack = $false
  while (-not $rolledBack -and [DateTime]::UtcNow -lt $rollbackDeadline) {
    try {
      Remove-Item -LiteralPath $target -Force
      Move-Item -LiteralPath $backup -Destination $target -Force
      $rolledBack = $true
    } catch { Start-Sleep -Milliseconds 500 }
  }
  if ($rolledBack) { Start-Process -FilePath $target -WorkingDirectory ([IO.Path]::GetDirectoryName($target)) }
  throw 'The updated Loremaster did not report a healthy start; the previous build was restored.'
}
Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $HealthPath -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
`;
}

export class PortableUpdateService {
  private readonly currentVersion: string;
  private readonly userDataDir: string;
  private readonly executablePath: string | null;
  private readonly fetchImpl: typeof fetch;
  private readonly spawnImpl: typeof spawn;
  private readonly minExecutableBytes: number;
  private readonly maxExecutableBytes: number;
  private readonly configuredPowershellPath: string | null;
  private readonly listeners = new Set<ProgressListener>();
  private progress: UpdateProgress = { phase: "idle", percent: 0, detail: "Ready to check for updates." };
  private activeDownload: Promise<StagedPortableUpdate> | null = null;
  private checkedRelease: PortableRelease | null = null;

  constructor(options: PortableUpdaterOptions) {
    compareVersions(options.currentVersion, options.currentVersion);
    this.currentVersion = normalizeVersion(options.currentVersion);
    this.userDataDir = path.resolve(options.userDataDir);
    this.executablePath = options.executablePath === undefined
      ? resolvePortableExecutable()
      : options.executablePath;
    this.fetchImpl = options.fetchImpl ?? fetch;
    this.spawnImpl = options.spawnImpl ?? spawn;
    this.minExecutableBytes = options.minExecutableBytes ?? MIN_EXECUTABLE_BYTES;
    this.maxExecutableBytes = options.maxExecutableBytes ?? MAX_EXECUTABLE_BYTES;
    this.configuredPowershellPath = options.powershellPath ?? null;
  }

  // Resolved at install time, not construction time. The constructor runs
  // during app startup on every platform -- main.ts calls it synchronously
  // inside app.whenReady(), ahead of createWindow() and ensureTray() -- so a
  // throw here silently costs the window and the tray icon. Only the Windows
  // portable-replacement path actually needs PowerShell.
  private resolvePowershellPath(): string {
    return this.configuredPowershellPath ?? resolveWindowsPowerShell();
  }

  subscribe(listener: ProgressListener): () => void {
    this.listeners.add(listener);
    listener(this.progress);
    return () => this.listeners.delete(listener);
  }

  getProgress(): UpdateProgress {
    return { ...this.progress };
  }

  private emit(progress: UpdateProgress): void {
    this.progress = { ...progress, percent: boundedPercent(progress.percent) };
    for (const listener of this.listeners) listener(this.getProgress());
  }

  async check(): Promise<UpdateCheckResult> {
    this.emit({ phase: "checking", percent: 10, detail: "Checking the official SpinUI release feed." });
    try {
      const response = await fetchOfficial(this.fetchImpl, RELEASE_API, {
        signal: AbortSignal.timeout(30_000),
        headers: {
          Accept: "application/vnd.github+json",
          "User-Agent": `Loremaster/${this.currentVersion}`,
          "X-GitHub-Api-Version": "2022-11-28",
        },
      });
      if (!response.ok) throw new Error(`GitHub returned HTTP ${response.status}.`);
      const bytes = await readLimitedBytes(response, MAX_RELEASE_BYTES);
      const release = releaseFromApi(JSON.parse(Buffer.from(bytes).toString("utf8")));
      const updateAvailable = compareVersions(release.version, this.currentVersion) > 0;
      this.checkedRelease = updateAvailable ? release : null;
      const detail = updateAvailable
        ? `Loremaster ${release.version} is ready to download.`
        : `Loremaster ${this.currentVersion} is up to date.`;
      this.emit({
        phase: updateAvailable ? "available" : "current",
        percent: 100,
        detail,
        version: release.version,
      });
      return {
        ok: true,
        currentVersion: this.currentVersion,
        latestVersion: release.version,
        updateAvailable,
        releaseUrl: release.releaseUrl,
        detail,
      };
    } catch (error) {
      this.checkedRelease = null;
      const detail = error instanceof Error ? error.message : String(error);
      this.emit({ phase: "error", percent: 0, detail });
      return {
        ok: false,
        currentVersion: this.currentVersion,
        latestVersion: "",
        updateAvailable: false,
        releaseUrl: RELEASE_PAGE,
        detail,
      };
    }
  }

  stage(): Promise<StagedPortableUpdate> {
    if (this.activeDownload) return this.activeDownload;
    const release = this.checkedRelease;
    if (!release) return Promise.reject(new Error("Check for a newer official release before downloading it."));
    this.activeDownload = this.stageOnce(release).finally(() => {
      this.activeDownload = null;
    });
    return this.activeDownload;
  }

  private async stageOnce(release: PortableRelease): Promise<StagedPortableUpdate> {
    const targetPath = ensureTargetExecutable(this.executablePath);
    await assertTargetDirectoryWritable(targetPath);
    if (compareVersions(release.version, this.currentVersion) <= 0) {
      throw new Error("The selected release is not newer than this Loremaster build.");
    }
    const stageDir = path.join(this.userDataDir, "updates", safeStageName(release.version));
    await mkdir(stageDir, { recursive: true });
    const stagedPath = path.join(stageDir, LOREMASTER_ASSET);
    const helperPath = path.join(stageDir, "install-loremaster-update.ps1");
    const healthPath = path.join(stageDir, "healthy.txt");
    const healthToken = randomBytes(32).toString("hex");
    try {
      this.emit({ phase: "downloading", percent: 2, detail: "Downloading the release checksum manifest.", version: release.version });
      const checksumResponse = await fetchOfficial(this.fetchImpl, release.checksums.url, {
        signal: AbortSignal.timeout(30_000),
        headers: { "User-Agent": `Loremaster/${this.currentVersion}` },
      });
      if (!checksumResponse.ok) throw new Error(`GitHub returned HTTP ${checksumResponse.status} for checksums.`);
      const checksumBytes = await readLimitedBytes(checksumResponse, MAX_CHECKSUM_BYTES);
      const checksums = parseChecksums(Buffer.from(checksumBytes).toString("utf8"));
      const expectedSha256 = checksums.get(LOREMASTER_ASSET);
      if (!expectedSha256) throw new Error(`The release manifest does not authenticate ${LOREMASTER_ASSET}.`);
      if (expectedSha256 !== release.executable.sha256) {
        throw new Error("GitHub's asset digest and the release checksum manifest do not agree.");
      }

      this.emit({ phase: "downloading", percent: 5, detail: "Downloading the verified portable Loremaster update.", version: release.version });
      const executableResponse = await fetchOfficial(this.fetchImpl, release.executable.url, {
        signal: AbortSignal.timeout(15 * 60_000),
        headers: { "User-Agent": `Loremaster/${this.currentVersion}` },
      });
      const downloaded = await writeVerifiedDownload(
        executableResponse,
        stagedPath,
        expectedSha256,
        release.executable.size,
        this.maxExecutableBytes,
        (received, total) => this.emit({
          phase: "downloading",
          percent: total > 0 ? 5 + (received / total) * 85 : 45,
          detail: "Downloading the verified portable Loremaster update.",
          version: release.version,
          bytesReceived: received,
          totalBytes: total || undefined,
        }),
      );
      this.emit({
        phase: "verifying", percent: 94, detail: "Verifying the Windows executable and preparing safe replacement.",
        version: release.version, bytesReceived: downloaded, totalBytes: downloaded,
      });
      await assertPortableExecutable(stagedPath, this.minExecutableBytes, this.maxExecutableBytes);
      await writeFile(helperPath, replacementScript(), { encoding: "utf8", flag: "w" });
      await writeFile(path.join(stageDir, "update.json"), JSON.stringify({
        schemaVersion: 1,
        version: release.version,
        targetPath,
        stagedPath,
        expectedSha256,
        healthPath,
        healthToken,
        releaseUrl: release.releaseUrl,
        stagedAt: new Date().toISOString(),
      }, null, 2), { encoding: "utf8", flag: "w" });
      const result = {
        version: release.version, targetPath, stagedPath, expectedSha256,
        helperPath, healthPath, healthToken, releaseUrl: release.releaseUrl,
      };
      this.emit({ phase: "ready", percent: 100, detail: `Loremaster ${release.version} is verified and ready to install.`, version: release.version });
      return result;
    } catch (error) {
      await rm(`${stagedPath}.part`, { force: true }).catch(() => undefined);
      const detail = error instanceof Error ? error.message : String(error);
      this.emit({ phase: "error", percent: 0, detail, version: release.version });
      throw error;
    }
  }

  installAndRelaunch(update: StagedPortableUpdate, parentPid = process.pid): number {
    const target = ensureTargetExecutable(update.targetPath);
    if (path.normalize(target).toLowerCase() !== path.normalize(ensureTargetExecutable(this.executablePath)).toLowerCase()) {
      throw new Error("The staged update does not target this portable Loremaster executable.");
    }
    if (!existsSync(update.stagedPath) || !existsSync(update.helperPath)) {
      throw new Error("The verified staged update is no longer available.");
    }
    this.emit({ phase: "installing", percent: 100, detail: "Closing Loremaster, installing the update, and reopening it.", version: update.version });
    const child: ChildProcess = this.spawnImpl(
      this.resolvePowershellPath(),
      [
        "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-File", update.helperPath,
        "-TargetPath", update.targetPath,
        "-StagedPath", update.stagedPath,
        "-ExpectedSha256", update.expectedSha256,
        "-HealthPath", update.healthPath,
        "-HealthToken", update.healthToken,
        "-ParentPid", String(parentPid),
      ],
      {
        cwd: path.dirname(target),
        detached: true,
        stdio: "ignore",
        windowsHide: true,
      },
    );
    if (!child.pid) throw new Error("Windows could not start the Loremaster update helper.");
    child.unref();
    return child.pid;
  }

  async discard(update: StagedPortableUpdate): Promise<void> {
    const updatesRoot = path.resolve(this.userDataDir, "updates");
    const stageDir = path.resolve(path.dirname(update.stagedPath));
    const relative = path.relative(updatesRoot, stageDir);
    if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) {
      throw new Error("Refusing to remove an update outside Loremaster's staging directory.");
    }
    await rm(stageDir, { recursive: true, force: true });
    this.emit({ phase: "idle", percent: 0, detail: "The staged update was removed." });
  }
}

export const portableUpdaterConstants = {
  releaseApi: RELEASE_API,
  releasePage: RELEASE_PAGE,
  executableAsset: LOREMASTER_ASSET,
  checksumAsset: CHECKSUM_ASSET,
};
