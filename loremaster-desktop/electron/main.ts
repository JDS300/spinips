import { app, BrowserWindow, dialog, globalShortcut, ipcMain, Menu, nativeImage, Notification, screen, shell, Tray } from "electron";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { existsSync, readFileSync, readdirSync, renameSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";
import { createInterface } from "node:readline";
import {
  buildGearPlan,
  catalogFromEqToolsData,
  emptyGearPlan,
  parseEqToolsBuild,
  parseInventory,
  type GearCatalogRecord,
  type GearPlanView,
  type InventoryEntry,
} from "./gear-plan";

const processStartedAt = performance.now();
app.commandLine.appendSwitch("autoplay-policy", "no-user-gesture-required");
if (process.platform === "linux") {
  // EverQuest runs under Proton/XWayland, and only the X11 backend gives the
  // overlays working always-on-top, click-through, and global hotkeys; native
  // Wayland silently drops all three. LOREMASTER_OZONE is the escape hatch.
  // Chromium's own detection is the default: a Wayland session gets Wayland,
  // an X11 session gets X11. Forcing X11 everywhere looked attractive because
  // EverQuest renders through XWayland and the X11 backend is what gives
  // overlays always-on-top, click-through and global hotkeys -- but on a KDE
  // Wayland session with the NVIDIA driver it makes the GPU process fail to
  // dlopen the GBM driver and segfault, after which the window is never
  // mapped at all: a tray icon and nothing else. A visible app without those
  // overlay guarantees beats an invisible one that has them on paper.
  // LOREMASTER_OZONE=x11 opts back in where the X11 backend does work.
  const requested = (process.env.LOREMASTER_OZONE ?? "").trim().toLowerCase();
  if (requested === "x11" || requested === "wayland") {
    app.commandLine.appendSwitch("ozone-platform", requested);
  }
}
if (process.env.LOREMASTER_DESKTOP_DATA_DIR) {
  app.setPath("userData", path.resolve(process.env.LOREMASTER_DESKTOP_DATA_DIR));
}
const ownsSingleInstance = app.requestSingleInstanceLock();
if (!ownsSingleInstance) app.quit();
let mainWindow: BrowserWindow | null = null;
let alertWindow: BrowserWindow | null = null;
let controlWindow: BrowserWindow | null = null;
let engine: EngineSupervisor | null = null;
let windowExpanded = false;
let windowAnalysis = false;
let expansionDirection: "up" | "down" = "down";
let movingWindowProgrammatically = false;
let tray: Tray | null = null;
let trayMinimizeNoticeShown = false;
let topmostReassertTimers: NodeJS.Timeout[] = [];
let topmostHeartbeatTimer: NodeJS.Timeout | null = null;

const SEED_SIZE = { width: 128, height: 74 } as const;
const EXPANDED_SIZE = { width: 470, height: 580 } as const;
const ANALYSIS_SIZE = { width: 1180, height: 760 } as const;
const ALERT_SIZE = { width: 420, height: 112 } as const;
const CONTROL_SURFACE_WIDTH = 304;
const CONTROL_SURFACE_HEADER_HEIGHT = 31;
const CONTROL_SURFACE_ROW_HEIGHT = 48;
const CONTROL_SURFACE_MAX_ROWS = 6;
const GROUP_SURFACE_HEADER_HEIGHT = 31;
const GROUP_SURFACE_ROW_HEIGHT = 38;
const GROUP_SURFACE_MAX_ROWS = 5;
const screenshotControls = [
  {
    kind: "mez", state: "active", target: "an essence carrier", count: 2,
    spell: "Mesmerization", rank: 5, landedAt: "2026-08-06T20:00:03.000Z",
    safeExpiresAt: "2026-08-06T20:00:39.000Z", expiresAt: "2026-08-06T20:00:45.000Z",
    durationSeconds: 36, safeRemainingSeconds: 28, remainingSeconds: 34,
    lastTick: false, urgency: "safe", confidence: "confirmed", ambiguity: "",
  },
  {
    kind: "lull", state: "active", target: "a soul carrier", count: 1,
    spell: "Calm", rank: 5, landedAt: "2026-08-06T20:00:32.000Z",
    safeExpiresAt: "2026-08-06T20:01:32.000Z", expiresAt: "2026-08-06T20:01:38.000Z",
    durationSeconds: 60, safeRemainingSeconds: 9, remainingSeconds: 15,
    lastTick: false, urgency: "warning", confidence: "exact", ambiguity: "",
  },
] as const;
type AlertAnchor = "auto" | "above" | "below" | "left" | "right";

export interface AlertSettings {
  alertsEnabled: boolean;
  alertSound: boolean;
  alertSeconds: number;
  alertAnchor: AlertAnchor;
  alertCharmBreak: boolean;
  alertTells: boolean;
  alertSummon: boolean;
  alertDeath: boolean;
  alertBigHit: boolean;
  alertNameCalled: boolean;
  bigHitThreshold: number;
  mezTimersEnabled: boolean;
  mezTimerSound: boolean;
  mezWarningSeconds: number;
  lullTimersEnabled: boolean;
  lullTimerSound: boolean;
  lullWarningSeconds: number;
}

interface DesktopSettings {
  logPath: string;
  raidDifficulty: number | null;
  bisBuildPath: string;
  inventoryPath: string;
  alwaysOnTop: boolean;
  fontScale: number;
  composition: string;
  splitCharmedPetDps: boolean;
  stanceAdvisorEnabled: boolean;
  seedPosition: { x: number; y: number } | null;
  alerts: AlertSettings;
}

interface EngineHealth {
  state: "starting" | "searching" | "live" | "error" | "stopped";
  detail: string;
  configuredPath: string;
  activeLogPath: string;
  character: string;
  server: string;
}

const defaultHealth: EngineHealth = {
  state: "starting",
  detail: "Starting the local parser engine",
  configuredPath: "",
  activeLogPath: "",
  character: "?",
  server: "?",
};

const defaultAlertSettings: AlertSettings = {
  alertsEnabled: true,
  alertSound: true,
  alertSeconds: 5,
  alertAnchor: "auto",
  alertCharmBreak: true,
  alertTells: true,
  alertSummon: true,
  alertDeath: true,
  alertBigHit: true,
  alertNameCalled: true,
  bigHitThreshold: 800,
  mezTimersEnabled: true,
  mezTimerSound: false,
  mezWarningSeconds: 10,
  lullTimersEnabled: true,
  lullTimerSound: false,
  lullWarningSeconds: 12,
};

const defaultSettings: DesktopSettings = {
  logPath: "",
  raidDifficulty: null,
  bisBuildPath: "",
  inventoryPath: "",
  alwaysOnTop: true,
  fontScale: 1.15,
  composition: "",
  splitCharmedPetDps: false,
  stanceAdvisorEnabled: false,
  seedPosition: null,
  alerts: defaultAlertSettings,
};

function settingsPath(): string {
  return path.join(app.getPath("userData"), "desktop-settings.json");
}

function readSettings(): DesktopSettings {
  try {
    const value = JSON.parse(readFileSync(settingsPath(), "utf8")) as Partial<DesktopSettings>;
    const raidDifficulty = Number.isInteger(value.raidDifficulty) && Number(value.raidDifficulty) >= 0 && Number(value.raidDifficulty) <= 4
      ? Number(value.raidDifficulty)
      : null;
    const alertValue = value.alerts && typeof value.alerts === "object"
      ? value.alerts as Partial<AlertSettings>
      : {};
    const alertAnchor = ["auto", "above", "below", "left", "right"].includes(String(alertValue.alertAnchor))
      ? alertValue.alertAnchor as AlertAnchor
      : defaultAlertSettings.alertAnchor;
    const seedPosition = value.seedPosition && Number.isFinite(value.seedPosition.x) && Number.isFinite(value.seedPosition.y)
      ? { x: Math.round(value.seedPosition.x), y: Math.round(value.seedPosition.y) }
      : null;
    const clampInteger = (candidate: unknown, fallback: number, low: number, high: number) => {
      const numeric = Number(candidate);
      return Number.isFinite(numeric) ? Math.max(low, Math.min(high, Math.round(numeric))) : fallback;
    };
    const boolean = (candidate: unknown, fallback: boolean) => typeof candidate === "boolean" ? candidate : fallback;
    return {
      logPath: typeof value.logPath === "string" ? value.logPath : "",
      raidDifficulty,
      bisBuildPath: typeof value.bisBuildPath === "string" ? value.bisBuildPath : "",
      inventoryPath: typeof value.inventoryPath === "string" ? value.inventoryPath : "",
      alwaysOnTop: boolean(value.alwaysOnTop, true),
      fontScale: clampInteger(value.fontScale === undefined ? 115 : Number(value.fontScale) * 100, 115, 90, 160) / 100,
      composition: typeof value.composition === "string" ? value.composition.slice(0, 48) : "",
      splitCharmedPetDps: boolean(value.splitCharmedPetDps, false),
      stanceAdvisorEnabled: boolean(value.stanceAdvisorEnabled, false),
      seedPosition,
      alerts: {
        alertsEnabled: boolean(alertValue.alertsEnabled, defaultAlertSettings.alertsEnabled),
        alertSound: boolean(alertValue.alertSound, defaultAlertSettings.alertSound),
        alertSeconds: clampInteger(alertValue.alertSeconds, defaultAlertSettings.alertSeconds, 1, 15),
        alertAnchor,
        alertCharmBreak: boolean(alertValue.alertCharmBreak, true),
        alertTells: boolean(alertValue.alertTells, true),
        alertSummon: boolean(alertValue.alertSummon, true),
        alertDeath: boolean(alertValue.alertDeath, true),
        alertBigHit: boolean(alertValue.alertBigHit, true),
        alertNameCalled: boolean(alertValue.alertNameCalled, true),
        bigHitThreshold: clampInteger(alertValue.bigHitThreshold, 800, 1, 999999),
        mezTimersEnabled: boolean(alertValue.mezTimersEnabled, true),
        mezTimerSound: boolean(alertValue.mezTimerSound, false),
        mezWarningSeconds: clampInteger(alertValue.mezWarningSeconds, 10, 3, 30),
        lullTimersEnabled: boolean(alertValue.lullTimersEnabled, true),
        lullTimerSound: boolean(alertValue.lullTimerSound, false),
        lullWarningSeconds: clampInteger(alertValue.lullWarningSeconds, 12, 3, 30),
      },
    };
  } catch {
    return { ...defaultSettings, alerts: { ...defaultAlertSettings } };
  }
}

function saveSettings(settings: DesktopSettings): void {
  const target = settingsPath();
  const temporary = `${target}.tmp`;
  writeFileSync(temporary, `${JSON.stringify(settings, null, 2)}\n`, "utf8");
  renameSync(temporary, target);
}

const WINDOWS_LOG_DIRECTORIES = [
  "C:\\EQLegends\\Logs", "C:\\EQLegends",
  "C:\\Users\\Public\\Daybreak Game Company\\Installed Games\\EverQuest Legends\\Logs",
  "C:\\Users\\Public\\Daybreak Game Company\\Installed Games\\EverQuest Legends",
  "C:\\Users\\Public\\Daybreak Game Company\\Installed Games\\EverQuest\\Logs",
  "C:\\Users\\Public\\Daybreak Game Company\\Installed Games\\EverQuest",
];

// EverQuest folder shapes probed inside each Wine/Proton prefix. Wine does not
// always map C:\Users\Public the way a real Windows install does, so the
// Program Files layout is probed alongside it.
// Proton names its only user profile "steamuser" rather than the real account
// name, so an installer that wrote under the current user's profile on Windows
// lands there instead of under users/Public.
const WINE_LOG_SUBPATHS = [
  "EQLegends",
  "users/Public/Daybreak Game Company/Installed Games/EverQuest Legends",
  "users/Public/Daybreak Game Company/Installed Games/EverQuest",
  "users/steamuser/Daybreak Game Company/Installed Games/EverQuest Legends",
  "users/steamuser/Daybreak Game Company/Installed Games/EverQuest",
  "Program Files (x86)/Daybreak Game Company/Installed Games/EverQuest Legends",
  "Program Files (x86)/Daybreak Game Company/Installed Games/EverQuest",
];

// Auto-detect runs on every engine start, so prefix enumeration is capped
// rather than allowed to walk an arbitrarily large Steam library.
const MAX_WINE_PREFIXES = 40;

function subdirectoryNames(directory: string): string[] {
  try {
    return readdirSync(directory, { withFileTypes: true })
      .filter((entry) => entry.isDirectory() || entry.isSymbolicLink())
      .map((entry) => entry.name);
  } catch {
    // Absent or unreadable prefix parents are normal during auto-detect.
    return [];
  }
}

// Lutris writes one YAML per game carrying an absolute `prefix:` path. Reading
// it is the only reliable way to find Lutris prefixes, which routinely live
// outside $HOME on a separate drive and so are invisible to any home-relative
// probe. Nested installer tasks repeat the same key; collecting every absolute
// match and de-duplicating is simpler than parsing YAML, and a non-prefix path
// costs only the drive_c existence check that every root already gets.
function lutrisPrefixRoots(): string[] {
  const home = app.getPath("home");
  const configDirs = [
    path.join(home, ".local", "share", "lutris", "games"),
    path.join(home, ".var", "app", "net.lutris.Lutris", "data", "lutris", "games"),
  ];
  const roots: string[] = [];
  for (const directory of configDirs) {
    let names: string[];
    try {
      names = readdirSync(directory);
    } catch {
      continue;
    }
    for (const name of names) {
      if (!name.endsWith(".yml")) continue;
      try {
        const text = readFileSync(path.join(directory, name), "utf8");
        for (const match of text.matchAll(/^[ \t]*prefix:[ \t]*(\/[^\r\n]+?)[ \t]*$/gm)) {
          roots.push(match[1]);
        }
      } catch {
        // An unreadable or half-written game config is not fatal.
      }
    }
  }
  return roots;
}

function winePrefixRoots(): string[] {
  const home = app.getPath("home");
  const roots: string[] = [];
  const configured = process.env.WINEPREFIX?.trim();
  if (configured) roots.push(path.resolve(configured));
  roots.push(path.join(home, ".wine"));
  // Added before the compatdata sweep so a large Steam library cannot push
  // Lutris prefixes past MAX_WINE_PREFIXES.
  roots.push(...lutrisPrefixRoots());
  const compatParents = [
    path.join(home, ".steam", "steam", "steamapps", "compatdata"),
    path.join(home, ".local", "share", "Steam", "steamapps", "compatdata"),
    path.join(home, ".var", "app", "com.valvesoftware.Steam", ".local", "share",
      "Steam", "steamapps", "compatdata"),
  ];
  for (const parent of compatParents) {
    for (const entry of subdirectoryNames(parent)) {
      if (roots.length >= MAX_WINE_PREFIXES) return roots;
      roots.push(path.join(parent, entry, "pfx"));
    }
  }
  // Lutris installs one prefix per game directly under ~/Games.
  const lutris = path.join(home, "Games");
  for (const entry of subdirectoryNames(lutris)) {
    if (roots.length >= MAX_WINE_PREFIXES) break;
    roots.push(path.join(lutris, entry));
  }
  return roots;
}

// A Steam-installed EverQuest lives in the library's steamapps/common, which
// sits on the Linux filesystem OUTSIDE any prefix's drive_c and is only visible
// inside the prefix through a dosdevices symlink. Prefix probing alone
// therefore cannot find it, so libraries are searched natively as well. This
// mirrors the Steam library scan installer/spinui_installer.py already does.
const STEAM_EQ_SUBPATHS = [
  "steamapps/common/EverQuest Legends",
  "steamapps/common/EverQuest",
];

function steamLibraryRoots(): string[] {
  const home = app.getPath("home");
  const roots = [
    path.join(home, ".steam", "steam"),
    path.join(home, ".local", "share", "Steam"),
    path.join(home, ".var", "app", "com.valvesoftware.Steam", ".local", "share", "Steam"),
  ];
  const libraries: string[] = [];
  for (const root of roots) {
    if (!existsSync(root)) continue;
    libraries.push(root);
    try {
      const vdf = readFileSync(
        path.join(root, "steamapps", "libraryfolders.vdf"), "utf8");
      for (const match of vdf.matchAll(/"path"\s+"([^"]+)"/g)) {
        libraries.push(match[1].replace(/\\\\/g, "\\"));
      }
    } catch {
      // A missing or unreadable libraryfolders.vdf just means no extra drives.
    }
  }
  return libraries;
}

function defaultLogDirectories(): string[] {
  if (process.platform === "win32") return WINDOWS_LOG_DIRECTORIES;
  if (process.platform !== "linux") return [];
  const candidates: string[] = [];
  for (const root of winePrefixRoots()) {
    const driveC = path.join(root, "drive_c");
    if (!existsSync(driveC)) continue;
    for (const relative of WINE_LOG_SUBPATHS) {
      const base = path.join(driveC, ...relative.split("/"));
      candidates.push(path.join(base, "Logs"), base);
    }
  }
  for (const library of new Set(steamLibraryRoots())) {
    for (const relative of STEAM_EQ_SUBPATHS) {
      const base = path.join(library, ...relative.split("/"));
      candidates.push(path.join(base, "Logs"), base);
    }
  }
  return candidates;
}

function newestEqLog(selectedPath: string): string {
  const cleaned = selectedPath.trim().replace(/^"|"$/g, "");
  const candidates = cleaned
    ? [cleaned, path.join(cleaned, "Logs")]
    : defaultLogDirectories();
  if (cleaned.toLowerCase().endsWith(".txt") && existsSync(cleaned)) return path.resolve(cleaned);
  let newest = "";
  let newestMtime = -1;
  for (const directory of [...new Set(candidates)]) {
    try {
      for (const name of readdirSync(directory)) {
        if (!/^eqlog_.+_.+\.txt$/i.test(name)) continue;
        const candidate = path.join(directory, name);
        const mtime = statSync(candidate).mtimeMs;
        if (mtime > newestMtime) {
          newest = candidate;
          newestMtime = mtime;
        }
      }
    } catch {
      // Missing and protected candidate folders are normal during auto-detect.
    }
  }
  return newest;
}

type EngineCommand = { executable: string; args: string[] };
type EngineResolution = { command: EngineCommand } | { error: string };

// A bare interpreter name has to stay bare so spawn keeps resolving it through
// PATH; this only answers "does it exist", so a missing python3 becomes an
// actionable message instead of a raw ENOENT.
function executableExists(name: string): boolean {
  if (name.includes("/") || name.includes("\\")) return existsSync(name);
  const extensions = process.platform === "win32"
    ? (process.env.PATHEXT ?? ".EXE;.CMD;.BAT").split(";")
    : [""];
  for (const directory of (process.env.PATH ?? "").split(path.delimiter)) {
    if (!directory) continue;
    for (const extension of extensions) {
      try {
        if (statSync(path.join(directory, `${name}${extension}`)).isFile()) return true;
      } catch {
        // Unreadable or stale PATH entries are normal.
      }
    }
  }
  return false;
}

function engineScriptPath(): string {
  // Linux ships no PyInstaller binary because the engine is stdlib-only, so the
  // packaged build carries the sources next to the bundled-engine slot.
  return app.isPackaged
    ? path.join(process.resourcesPath, "engine", "desktop_worker.py")
    : path.resolve(app.getAppPath(), "..", "loremaster", "desktop_worker.py");
}

function resolveEngineCommand(): EngineResolution {
  if (app.isPackaged) {
    const binary = path.join(process.resourcesPath, "engine",
      process.platform === "win32" ? "LoremasterEngine.exe" : "LoremasterEngine");
    if (existsSync(binary)) return { command: { executable: binary, args: [] } };
  }
  const script = engineScriptPath();
  if (!existsSync(script)) {
    return {
      error: app.isPackaged
        ? "The packaged parser engine is missing. Reinstall Loremaster."
        : `Could not find the parser engine script at ${script}.`,
    };
  }
  const configuredPython = process.env.LOREMASTER_PYTHON;
  if (configuredPython) return { command: { executable: configuredPython, args: [script] } };
  const interpreter: EngineCommand = process.platform === "win32"
    ? { executable: "py", args: ["-3", script] }
    : { executable: "python3", args: [script] };
  if (!executableExists(interpreter.executable)) {
    return {
      error: "No Python interpreter was found. Install Python 3.10 or newer, "
        + "or set LOREMASTER_PYTHON to your interpreter.",
    };
  }
  return { command: interpreter };
}

// Wine and Proton prefix layouts vary too much to auto-detect reliably, so a
// failed search has to name the manual escape hatch instead of idling.
function autoDetectHint(health: EngineHealth, configuredPath: string): string | null {
  if (process.platform !== "linux") return null;
  if (health.state !== "searching" || health.activeLogPath || configuredPath) return null;
  return "No eqlog_*.txt found in any Wine or Proton prefix. "
    + "Open settings and set EVERQUEST DIRECTORY to your Logs folder.";
}

class EngineSupervisor {
  private child: ChildProcessWithoutNullStreams | null = null;
  private stopping = false;
  private restartCount = 0;
  private restartTimer: NodeJS.Timeout | null = null;
  private attachmentRetryTimer: NodeJS.Timeout | null = null;
  private health: EngineHealth = { ...defaultHealth };
  private snapshot: unknown = null;
  private settings = readSettings();
  private gearCatalog: GearCatalogRecord[] = [];
  private catalogUpdatedAt = "";
  private gearPlan: GearPlanView = emptyGearPlan(
    this.settings.bisBuildPath, this.settings.inventoryPath);

  constructor() {
    this.readCatalogCache();
    this.rebuildGearPlan();
  }

  start(): void {
    this.stopping = false;
    this.spawnWorker();
  }

  private publishHealth(health: EngineHealth): void {
    this.health = health;
    mainWindow?.webContents.send("engine:health", health);
  }

  private spawnWorker(): void {
    const resolution = resolveEngineCommand();
    if ("error" in resolution) {
      this.publishHealth({ ...defaultHealth, state: "error", detail: resolution.error });
      return;
    }
    const command = resolution.command;
    this.publishHealth({
      ...defaultHealth,
      configuredPath: this.settings.logPath,
      detail: this.restartCount > 0 ? "Restarting the local parser engine" : defaultHealth.detail,
    });
    try {
      this.child = spawn(command.executable, command.args, {
        // In a packaged build app.getAppPath() points at app.asar, which is a
        // file rather than a valid working directory. Windows reports that as
        // a spawn failure even when LoremasterEngine.exe exists and is valid.
        cwd: app.isPackaged ? process.resourcesPath : app.getAppPath(),
        env: {
          ...process.env,
          PYTHONUNBUFFERED: "1",
          LOREMASTER_APP_DATA_DIR: app.getPath("userData"),
        },
        stdio: ["pipe", "pipe", "pipe"],
        windowsHide: true,
      });
    } catch (error) {
      this.handleSpawnFailure(error);
      return;
    }
    const child = this.child;
    createInterface({ input: child.stdout }).on("line", (line) => this.handleLine(line));
    createInterface({ input: child.stderr }).on("line", (line) => {
      console.error(`[LoremasterEngine] ${line}`);
    });
    child.once("spawn", () => {
      const parserLogPath = newestEqLog(this.settings.logPath) || this.settings.logPath;
      console.log(`[Loremaster] engine ${[command.executable, ...command.args].join(" ")}`
        + ` | log ${parserLogPath || "(auto-detect found nothing)"}`);
      this.send({
        type: "engine.initialize",
        logPath: parserLogPath,
        raidDifficulty: this.settings.raidDifficulty,
        composition: this.settings.composition,
        alertConfig: this.settings.alerts,
      });
    });
    child.once("error", (error) => this.handleSpawnFailure(error));
    child.once("exit", (code) => {
      this.child = null;
      if (this.stopping) return;
      this.publishHealth({
        ...this.health,
        state: "error",
        detail: `Parser engine stopped unexpectedly${code === null ? "" : ` (${code})`}`,
      });
      if (this.restartCount < 3) {
        const delay = 350 * (2 ** this.restartCount);
        this.restartCount += 1;
        this.restartTimer = setTimeout(() => this.spawnWorker(), delay);
      }
    });
  }

  private handleSpawnFailure(error: unknown): void {
    const message = error instanceof Error ? error.message : String(error);
    this.publishHealth({
      ...this.health,
      state: "error",
      detail: `Could not start the parser engine: ${message}`,
    });
  }

  private handleLine(line: string): void {
    if (line.length > 2_000_000) return;
    let event: Record<string, unknown>;
    try {
      event = JSON.parse(line) as Record<string, unknown>;
    } catch {
      console.error("Loremaster engine emitted invalid JSON");
      return;
    }
    if (event.protocolVersion !== 1 || typeof event.eventType !== "string") return;
    if (event.eventType === "engine.snapshot" && event.snapshot) {
      this.snapshot = event;
      mainWindow?.webContents.send("engine:snapshot", event);
      alertWindow?.webContents.send("engine:snapshot", event);
      if (process.env.LOREMASTER_SCREENSHOT_VIEW !== "controls") {
        controlWindow?.webContents.send("engine:snapshot", event);
      }
      syncControlWindow();
    } else if (event.eventType === "engine.health" || event.eventType === "engine.ready") {
      const health = event.health as EngineHealth | undefined;
      if (health && typeof health.state === "string") {
        this.restartCount = 0;
        this.publishHealth({
          ...health,
          configuredPath: this.settings.logPath,
          detail: autoDetectHint(health, this.settings.logPath) ?? health.detail,
        });
      }
    } else if (event.eventType === "engine.error") {
      this.publishHealth({
        ...this.health,
        state: "error",
        detail: typeof event.message === "string" ? event.message : "Parser engine error",
      });
    }
  }

  private send(command: Record<string, unknown>): void {
    if (!this.child?.stdin.writable) return;
    this.child.stdin.write(`${JSON.stringify(command)}\n`);
  }

  getState(): { health: EngineHealth; snapshot: unknown; settings: DesktopSettings; gearPlan: GearPlanView } {
    return { health: this.health, snapshot: this.snapshot, settings: this.settings, gearPlan: this.gearPlan };
  }

  setLogPath(logPath: string): void {
    this.settings = { ...this.settings, logPath };
    saveSettings(this.settings);
    const parserLogPath = newestEqLog(logPath);
    this.send({ type: "engine.set-log-path", logPath: parserLogPath || logPath });
    this.publishHealth({
      ...this.health,
      state: "searching",
      detail: parserLogPath
        ? `Found ${path.basename(parserLogPath)}; attaching the parser`
        : logPath ? "No eqlog_*.txt found in the selected folder or its Logs folder"
          : "Searching common EverQuest Legends log locations",
      configuredPath: logPath,
      activeLogPath: "",
    });
    if (this.attachmentRetryTimer) clearTimeout(this.attachmentRetryTimer);
    if (parserLogPath) {
      this.attachmentRetryTimer = setTimeout(() => {
        if (this.health.state === "live") return;
        this.send({ type: "engine.set-log-path", logPath: parserLogPath });
        this.publishHealth({
          ...this.health,
          state: "searching",
          detail: `Log found; retrying ${path.basename(parserLogPath)}`,
          configuredPath: this.settings.logPath,
          activeLogPath: parserLogPath,
        });
      }, 2500);
    }
  }

  setRaidDifficulty(raidDifficulty: number | null): void {
    this.settings = { ...this.settings, raidDifficulty };
    saveSettings(this.settings);
    this.send({ type: "engine.set-raid-difficulty", raidDifficulty });
  }

  updateDesktopSettings(patch: Partial<Pick<DesktopSettings, "alwaysOnTop" | "fontScale" | "composition" | "splitCharmedPetDps" | "stanceAdvisorEnabled">> & {
    alerts?: Partial<AlertSettings>;
  }): DesktopSettings {
    const nextAlerts = patch.alerts ? { ...this.settings.alerts, ...patch.alerts } : this.settings.alerts;
    const previousScale = this.settings.fontScale;
    const nextScale = typeof patch.fontScale === "number" ? clamp(patch.fontScale, 0.9, 1.6) : previousScale;
    const nextSeedPosition = nextScale !== previousScale
      ? scaledSeedPosition(this.settings.seedPosition, previousScale, nextScale)
      : this.settings.seedPosition;
    this.settings = {
      ...this.settings,
      ...(typeof patch.alwaysOnTop === "boolean" ? { alwaysOnTop: patch.alwaysOnTop } : {}),
      fontScale: nextScale,
      seedPosition: nextSeedPosition,
      ...(typeof patch.composition === "string" ? { composition: patch.composition.trim().slice(0, 48) } : {}),
      ...(typeof patch.splitCharmedPetDps === "boolean" ? { splitCharmedPetDps: patch.splitCharmedPetDps } : {}),
      ...(typeof patch.stanceAdvisorEnabled === "boolean" ? { stanceAdvisorEnabled: patch.stanceAdvisorEnabled } : {}),
      alerts: nextAlerts,
    };
    saveSettings(this.settings);
    this.send({ type: "engine.set-alert-config", alertConfig: this.settings.alerts });
    if (typeof patch.composition === "string") {
      this.send({ type: "engine.set-composition", composition: this.settings.composition });
    }
    applyDisplayScale(this.settings.fontScale);
    applyAlwaysOnTop(this.settings.alwaysOnTop);
    positionAlertWindow();
    mainWindow?.webContents.send("settings:changed", this.settings);
    alertWindow?.webContents.send("settings:changed", this.settings);
    controlWindow?.webContents.send("settings:changed", this.settings);
    syncControlWindow();
    return this.settings;
  }

  saveSeedPosition(position: { x: number; y: number }): void {
    this.settings = { ...this.settings, seedPosition: position };
    saveSettings(this.settings);
  }

  setRaidCompletion(target: string, difficulty: number, completed: boolean): void {
    this.send({ type: "engine.set-raid-completion", target, difficulty, completed });
  }

  scanAltZLockouts(): void {
    this.send({ type: "engine.scan-alt-z-lockouts" });
  }

  private catalogCachePath(): string {
    return path.join(app.getPath("userData"), "eq-legends-tools-gear-cache.json");
  }

  private readCatalogCache(): void {
    try {
      const value = JSON.parse(readFileSync(this.catalogCachePath(), "utf8")) as {
        updatedAt?: unknown; records?: unknown;
      };
      if (!Array.isArray(value.records)) return;
      this.gearCatalog = value.records as GearCatalogRecord[];
      this.catalogUpdatedAt = typeof value.updatedAt === "string" ? value.updatedAt : "";
    } catch {
      this.gearCatalog = [];
      this.catalogUpdatedAt = "";
    }
  }

  private saveCatalogCache(): void {
    const target = this.catalogCachePath();
    const temporary = `${target}.tmp`;
    writeFileSync(temporary, JSON.stringify({
      schemaVersion: 1,
      source: "https://eqlegendstools.com/",
      credit: "EQ Legends Tools by FlammHammer",
      updatedAt: this.catalogUpdatedAt,
      records: this.gearCatalog,
    }), "utf8");
    renameSync(temporary, target);
  }

  private rebuildGearPlan(): void {
    const { bisBuildPath, inventoryPath } = this.settings;
    if (!bisBuildPath) {
      this.gearPlan = emptyGearPlan(bisBuildPath, inventoryPath);
      this.publishGearPlan();
      return;
    }
    try {
      const buildText = readFileSync(bisBuildPath, "utf8");
      if (buildText.length > 5_000_000) throw new Error("Character build is larger than 5 MB");
      const build = parseEqToolsBuild(buildText);
      let inventory: InventoryEntry[] = [];
      if (inventoryPath && existsSync(inventoryPath)) {
        const inventoryText = readFileSync(inventoryPath, "utf8");
        if (inventoryText.length > 20_000_000) throw new Error("Inventory file is larger than 20 MB");
        inventory = parseInventory(inventoryText);
      }
      this.gearPlan = buildGearPlan(build, inventory, this.gearCatalog, {
        buildPath: bisBuildPath,
        inventoryPath,
        catalogUpdatedAt: this.catalogUpdatedAt,
      });
    } catch (error) {
      this.gearPlan = {
        ...emptyGearPlan(bisBuildPath, inventoryPath),
        status: "error",
        detail: error instanceof Error ? error.message : String(error),
      };
    }
    this.publishGearPlan();
  }

  private publishGearPlan(): void {
    mainWindow?.webContents.send("gear:state", this.gearPlan);
  }

  async setBisBuildPath(bisBuildPath: string): Promise<void> {
    this.settings = { ...this.settings, bisBuildPath };
    saveSettings(this.settings);
    await this.refreshGearCatalog();
  }

  setInventoryPath(inventoryPath: string): void {
    this.settings = { ...this.settings, inventoryPath };
    saveSettings(this.settings);
    this.rebuildGearPlan();
  }

  async refreshGearCatalog(): Promise<boolean> {
    try {
      const response = await fetch("https://eqlegendstools.com/api/char-sheet-data", {
        headers: {
          Accept: "application/json",
          Referer: "https://eqlegendstools.com/char-sheet/",
          "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Loremaster/0.1",
        },
      });
      if (!response.ok) throw new Error(`EQ Legends Tools returned HTTP ${response.status}`);
      const text = await response.text();
      if (text.length > 40_000_000) throw new Error("EQ Legends Tools catalog exceeded the safety limit");
      this.gearCatalog = catalogFromEqToolsData(JSON.parse(text));
      this.catalogUpdatedAt = new Date().toISOString();
      this.saveCatalogCache();
      this.rebuildGearPlan();
      return true;
    } catch (error) {
      console.error("Could not refresh EQ Legends Tools gear data", error);
      this.rebuildGearPlan();
      return false;
    }
  }

  reset(): void {
    this.send({ type: "engine.reset" });
  }

  stop(): void {
    this.stopping = true;
    if (this.restartTimer) clearTimeout(this.restartTimer);
    if (this.attachmentRetryTimer) clearTimeout(this.attachmentRetryTimer);
    this.send({ type: "engine.shutdown" });
    const child = this.child;
    if (child) setTimeout(() => {
      if (!child.killed) child.kill();
    }, 900);
  }
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}

function scaledSize(size: { width: number; height: number }, scale?: number) {
  const factor = scale ?? engine?.getState().settings.fontScale ?? defaultSettings.fontScale;
  return {
    width: Math.round(size.width * factor),
    height: Math.round(size.height * factor),
  };
}

function scaledSeedPosition(
  position: { x: number; y: number } | null,
  previousScale: number,
  nextScale: number,
): { x: number; y: number } | null {
  if (!position || previousScale === nextScale) return position;
  const previous = scaledSize(SEED_SIZE, previousScale);
  const next = scaledSize(SEED_SIZE, nextScale);
  const display = screen.getDisplayNearestPoint({
    x: position.x + Math.round(previous.width / 2),
    y: position.y + Math.round(previous.height / 2),
  });
  const workArea = display.workArea;
  const anchorRight = position.x + previous.width / 2 > workArea.x + workArea.width / 2;
  const anchorBottom = position.y + previous.height / 2 > workArea.y + workArea.height / 2;
  const x = anchorRight ? position.x + previous.width - next.width : position.x;
  const y = anchorBottom ? position.y + previous.height - next.height : position.y;
  return {
    x: clamp(x, workArea.x, workArea.x + workArea.width - next.width),
    y: clamp(y, workArea.y, workArea.y + workArea.height - next.height),
  };
}

function visibleSeedControls(value: unknown, settings: DesktopSettings): Record<string, unknown>[] {
  if (!value || typeof value !== "object") return [];
  const snapshot = (value as { snapshot?: unknown }).snapshot;
  if (!snapshot || typeof snapshot !== "object") return [];
  const controls = (snapshot as { controls?: unknown }).controls;
  if (!Array.isArray(controls)) return [];
  return controls.filter((candidate): candidate is Record<string, unknown> => {
    if (!candidate || typeof candidate !== "object") return false;
    const control = candidate as Record<string, unknown>;
    if (control.state !== "active") return false;
    if (control.kind === "mez") return settings.alerts.mezTimersEnabled;
    if (control.kind === "lull") return settings.alerts.lullTimersEnabled;
    return false;
  }).slice(0, CONTROL_SURFACE_MAX_ROWS);
}

function visibleGroupContributors(value: unknown): Record<string, unknown>[] {
  if (!value || typeof value !== "object") return [];
  const snapshot = (value as { snapshot?: unknown }).snapshot;
  if (!snapshot || typeof snapshot !== "object") return [];
  const encounters = (snapshot as { encounters?: unknown }).encounters;
  const groupMembersValue = (snapshot as { groupMembers?: unknown }).groupMembers;
  const groupMembers = new Set(Array.isArray(groupMembersValue)
    ? groupMembersValue.filter((name): name is string => typeof name === "string")
      .map((name) => name.toLocaleLowerCase())
    : []);
  if (!Array.isArray(encounters) || encounters.length === 0) return [];
  const latest = encounters[encounters.length - 1];
  if (!latest || typeof latest !== "object") return [];
  const actors = (latest as { actors?: unknown }).actors;
  if (!Array.isArray(actors)) return [];
  return actors.filter((candidate): candidate is Record<string, unknown> => (
    Boolean(candidate) && typeof candidate === "object" &&
    (candidate as Record<string, unknown>).role === "group" &&
    Number((candidate as Record<string, unknown>).encounterDamage) > 0 &&
    groupMembers.has(String((candidate as Record<string, unknown>).name).toLocaleLowerCase())
  )).sort((left, right) => (
    Number(right.encounterDamage) - Number(left.encounterDamage)
  )).slice(0, GROUP_SURFACE_MAX_ROWS);
}

function controlSurfaceSize(controlRows: number, groupRows: number, scale: number) {
  const controlHeight = controlRows > 0
    ? CONTROL_SURFACE_HEADER_HEIGHT + controlRows * CONTROL_SURFACE_ROW_HEIGHT
    : 0;
  const groupHeight = groupRows > 0
    ? GROUP_SURFACE_HEADER_HEIGHT + groupRows * GROUP_SURFACE_ROW_HEIGHT
    : 0;
  return scaledSize({
    width: CONTROL_SURFACE_WIDTH,
    height: Math.max(1, controlHeight + groupHeight),
  }, scale);
}

function applyDisplayScale(scale: number): void {
  const factor = clamp(scale, 0.9, 1.6);
  mainWindow?.webContents.setZoomFactor(factor);
  alertWindow?.webContents.setZoomFactor(factor);
  controlWindow?.webContents.setZoomFactor(factor);
  if (mainWindow) {
    if (windowAnalysis) setAnalysisMode(true, true);
    else setWindowMode(windowExpanded, true);
  }
  syncControlWindow();
}

function overlayWindows(): BrowserWindow[] {
  return [mainWindow, alertWindow, controlWindow].filter(
    (window): window is BrowserWindow => Boolean(window && !window.isDestroyed()),
  );
}

function trayIcon(): Electron.NativeImage | null {
  // Linux status-notifier hosts do not read .ico, so the PNG leads there.
  const names = process.platform === "linux"
    ? ["loremaster-cog.png", "loremaster.ico"]
    : ["loremaster.ico", "loremaster-cog.png"];
  const candidates = names.flatMap((name) => [
    path.join(app.getAppPath(), "dist", name),
    path.resolve(app.getAppPath(), "..", "loremaster", "assets", name),
  ]);
  for (const candidate of candidates) {
    if (!existsSync(candidate)) continue;
    const image = nativeImage.createFromPath(candidate);
    if (!image.isEmpty()) return image;
  }
  return null;
}

function restoreLoremasterWindow(): void {
  const window = mainWindow;
  if (!window || window.isDestroyed()) {
    createWindow();
    return;
  }
  if (window.isMinimized()) window.restore();
  window.setSkipTaskbar(Boolean(tray));
  window.show();
  window.focus();
  window.moveTop();
  alertWindow?.showInactive();
  positionAlertWindow();
  syncControlWindow();
  applyAlwaysOnTop(engine?.getState().settings.alwaysOnTop ?? defaultSettings.alwaysOnTop);
}

function quitLoremaster(): void {
  app.quit();
}

function ensureTray(): boolean {
  if (tray && !tray.isDestroyed()) return true;
  const icon = trayIcon();
  if (!icon) {
    console.error("Could not create the Loremaster tray icon; using taskbar minimize");
    return false;
  }
  try {
    tray = new Tray(icon);
    tray.setToolTip("Loremaster — click to restore");
    tray.setContextMenu(Menu.buildFromTemplate([
      { label: "Show Loremaster", click: restoreLoremasterWindow },
      { type: "separator" },
      { label: "Quit Loremaster", click: quitLoremaster },
    ]));
    tray.on("click", restoreLoremasterWindow);
    tray.on("double-click", restoreLoremasterWindow);
    return true;
  } catch (error) {
    tray = null;
    console.error("Could not initialize the Loremaster tray icon", error);
    return false;
  }
}

function notifyUser(title: string, body: string): void {
  try {
    if (Notification.isSupported()) new Notification({ title, body, silent: true }).show();
  } catch (error) {
    console.warn("Could not show a Loremaster desktop notification", error);
  }
}

function showTrayMinimizeNotice(): void {
  const title = "Loremaster is still running";
  const body = "Click the tray icon to restore it, or right-click and choose Quit Loremaster.";
  if (process.platform === "win32") {
    try {
      tray?.displayBalloon({ title, content: body, iconType: "info", noSound: true });
    } catch {
      // Some Windows notification policies suppress tray balloons.
    }
    return;
  }
  // Linux status-notifier trays have no balloon API; the desktop notification
  // service is the equivalent surface and no-ops when none is running.
  notifyUser(title, body);
}

function minimizeLoremasterWindow(): void {
  const window = mainWindow;
  if (!window || window.isDestroyed()) return;
  if (ensureTray()) {
    alertWindow?.hide();
    controlWindow?.hide();
    window.hide();
    if (!trayMinimizeNoticeShown) {
      trayMinimizeNoticeShown = true;
      showTrayMinimizeNotice();
    }
    return;
  }
  // A taskbar button is the recovery path if Windows refuses tray creation.
  window.setSkipTaskbar(false);
  window.minimize();
}

function reinforceOverlayZOrder(enabled: boolean): void {
  // Linux stays on "floating": Electron ignores the level argument on X11, where
  // always-on-top is just _NET_WM_STATE_ABOVE, and that alone already keeps the
  // overlays above EQ running under Wine.
  const level = process.platform === "win32" ? "screen-saver" : "floating";
  for (const window of overlayWindows()) {
    try {
      window.setAlwaysOnTop(enabled, level, enabled ? 1 : 0);
      if (enabled && window.isVisible()) window.moveTop();
    } catch (error) {
      console.warn("Could not reinforce Loremaster overlay z-order", error);
    }
  }
}

function clearTopmostReassertions(): void {
  for (const timer of topmostReassertTimers) clearTimeout(timer);
  topmostReassertTimers = [];
}

function scheduleTopmostReassertion(): void {
  clearTopmostReassertions();
  if (!(engine?.getState().settings.alwaysOnTop ?? defaultSettings.alwaysOnTop)) return;
  for (const delay of [60, 240]) {
    const timer = setTimeout(() => {
      topmostReassertTimers = topmostReassertTimers.filter((candidate) => candidate !== timer);
      reinforceOverlayZOrder(true);
    }, delay);
    timer.unref();
    topmostReassertTimers.push(timer);
  }
}

function applyAlwaysOnTop(enabled: boolean): void {
  clearTopmostReassertions();
  reinforceOverlayZOrder(enabled);
  if (enabled) scheduleTopmostReassertion();
}

function startTopmostHeartbeat(): void {
  if (topmostHeartbeatTimer) return;
  topmostHeartbeatTimer = setInterval(() => {
    if (engine?.getState().settings.alwaysOnTop ?? defaultSettings.alwaysOnTop) {
      reinforceOverlayZOrder(true);
    }
  }, 2_000);
  topmostHeartbeatTimer.unref();
}

function syncControlWindow(): void {
  if (!mainWindow || !controlWindow || controlWindow.isDestroyed()) return;
  if (process.env.LOREMASTER_SCREENSHOT_VIEW === "controls") return;
  const settings = engine?.getState().settings ?? defaultSettings;
  const rows = visibleSeedControls(engine?.getState().snapshot, settings);
  const contributors = visibleGroupContributors(engine?.getState().snapshot);
  if (!mainWindow.isVisible() || windowExpanded || (rows.length === 0 && contributors.length === 0)) {
    controlWindow.hide();
    positionAlertWindow();
    return;
  }

  const panelSize = controlSurfaceSize(rows.length, contributors.length, settings.fontScale);
  const anchor = mainWindow.getBounds();
  const workArea = screen.getDisplayMatching(anchor).workArea;
  const gap = Math.max(5, Math.round(6 * settings.fontScale));
  const spaceRight = workArea.x + workArea.width - (anchor.x + anchor.width);
  const spaceLeft = anchor.x - workArea.x;
  const spaceAbove = anchor.y - workArea.y;
  const spaceBelow = workArea.y + workArea.height - (anchor.y + anchor.height);

  let x: number;
  let y: number;
  if (spaceAbove >= panelSize.height + gap) {
    x = anchor.x + Math.round((anchor.width - panelSize.width) / 2);
    y = anchor.y - panelSize.height - gap;
  } else if (spaceRight >= panelSize.width + gap) {
    x = anchor.x + anchor.width + gap;
    y = anchor.y + Math.round((anchor.height - panelSize.height) / 2);
  } else if (spaceLeft >= panelSize.width + gap) {
    x = anchor.x - panelSize.width - gap;
    y = anchor.y + Math.round((anchor.height - panelSize.height) / 2);
  } else {
    x = anchor.x + Math.round((anchor.width - panelSize.width) / 2);
    y = anchor.y + anchor.height + gap;
  }
  x = clamp(x, workArea.x, workArea.x + workArea.width - panelSize.width);
  y = clamp(y, workArea.y, workArea.y + workArea.height - panelSize.height);
  controlWindow.setBounds({ x, y, ...panelSize }, false);
  if (!controlWindow.webContents.isLoadingMainFrame()) controlWindow.showInactive();
  positionAlertWindow();
}

function canonicalSeedAnchor(settings: DesktopSettings, fallback: Electron.Rectangle) {
  const size = scaledSize(SEED_SIZE, settings.fontScale);
  const saved = settings.seedPosition ?? { x: fallback.x, y: fallback.y };
  const display = screen.getDisplayNearestPoint({
    x: saved.x + Math.round(size.width / 2),
    y: saved.y + Math.round(size.height / 2),
  });
  const workArea = display.workArea;
  return {
    workArea,
    bounds: {
      x: clamp(saved.x, workArea.x, workArea.x + workArea.width - size.width),
      y: clamp(saved.y, workArea.y, workArea.y + workArea.height - size.height),
      ...size,
    },
  };
}

function positionAlertWindow(): void {
  if (!mainWindow || !alertWindow || alertWindow.isDestroyed()) return;
  const settings = engine?.getState().settings ?? defaultSettings;
  const alertSize = scaledSize(ALERT_SIZE, settings.fontScale);
  const anchorBounds = mainWindow.getBounds();
  const companionBounds = controlWindow?.isVisible() ? controlWindow.getBounds() : null;
  const companionAbove = Boolean(
    companionBounds && companionBounds.y + companionBounds.height <= anchorBounds.y);
  const workArea = screen.getDisplayMatching(anchorBounds).workArea;
  const gap = 10;
  let anchor = settings.alerts.alertAnchor;
  if (anchor === "auto") {
    const aboveEdge = companionAbove && companionBounds
      ? companionBounds.y
      : anchorBounds.y;
    const above = aboveEdge - workArea.y;
    const below = workArea.y + workArea.height - (anchorBounds.y + anchorBounds.height);
    const right = workArea.x + workArea.width - (anchorBounds.x + anchorBounds.width);
    anchor = above >= alertSize.height + gap && above >= below
      ? "above"
      : right >= alertSize.width + gap ? "right"
        : below >= alertSize.height + gap ? "below" : "left";
  }
  let x = anchorBounds.x + Math.round((anchorBounds.width - alertSize.width) / 2);
  let y = (companionAbove && companionBounds ? companionBounds.y : anchorBounds.y)
    - alertSize.height - gap;
  if (anchor === "below") y = anchorBounds.y + anchorBounds.height + gap;
  if (anchor === "left") {
    x = anchorBounds.x - alertSize.width - gap;
    y = anchorBounds.y + Math.round((anchorBounds.height - alertSize.height) / 2);
  }
  if (anchor === "right") {
    x = anchorBounds.x + anchorBounds.width + gap;
    y = anchorBounds.y + Math.round((anchorBounds.height - alertSize.height) / 2);
  }
  x = clamp(x, workArea.x, workArea.x + workArea.width - alertSize.width);
  y = clamp(y, workArea.y, workArea.y + workArea.height - alertSize.height);
  alertWindow.setBounds({ x, y, ...alertSize }, false);
}

function setWindowMode(expanded: boolean, preserveAnchor = false): void {
  if (!mainWindow) return;
  const current = mainWindow.getBounds();
  const settings = engine?.getState().settings ?? defaultSettings;
  const anchor = canonicalSeedAnchor(settings, current);
  const workArea = anchor.workArea;
  const seedBounds = anchor.bounds;
  const expandedSize = scaledSize(EXPANDED_SIZE, settings.fontScale);
  movingWindowProgrammatically = true;
  windowExpanded = expanded;
  windowAnalysis = false;
  if (expanded) {
    const spaceBelow = workArea.y + workArea.height - (seedBounds.y + seedBounds.height);
    const spaceAbove = seedBounds.y - workArea.y;
    if (!preserveAnchor) {
      expansionDirection = spaceBelow < expandedSize.height - seedBounds.height && spaceAbove > spaceBelow
        ? "up"
        : "down";
    }
    const y = expansionDirection === "up"
      ? seedBounds.y + seedBounds.height - expandedSize.height
      : seedBounds.y;
    const target = {
      x: clamp(seedBounds.x, workArea.x, workArea.x + workArea.width - expandedSize.width),
      y: clamp(y, workArea.y, workArea.y + workArea.height - expandedSize.height),
      ...expandedSize,
    };
    mainWindow.setMinimumSize(Math.round(390 * settings.fontScale), Math.round(500 * settings.fontScale));
    mainWindow.setBounds(target, false);
  } else {
    const target = seedBounds;
    mainWindow.setMinimumSize(118, 64);
    mainWindow.setBounds(target, false);
    engine?.saveSeedPosition({ x: target.x, y: target.y });
  }
  positionAlertWindow();
  syncControlWindow();
  applyAlwaysOnTop(settings.alwaysOnTop);
  setImmediate(() => { movingWindowProgrammatically = false; });
}

function setAnalysisMode(active: boolean, preserveAnchor = false): void {
  if (!active) {
    setWindowMode(true, preserveAnchor);
    return;
  }
  if (!mainWindow) return;
  const current = mainWindow.getBounds();
  const settings = engine?.getState().settings ?? defaultSettings;
  const anchor = canonicalSeedAnchor(settings, current);
  const workArea = anchor.workArea;
  const seedBounds = anchor.bounds;
  const requested = scaledSize(ANALYSIS_SIZE, Math.min(settings.fontScale, 1.35));
  const availableWidth = Math.max(480, workArea.width - 16);
  const availableHeight = Math.max(440, workArea.height - 16);
  const targetSize = {
    width: Math.min(Math.max(780, requested.width), availableWidth),
    height: Math.min(Math.max(620, requested.height), availableHeight),
  };
  const spaceBelow = workArea.y + workArea.height - (seedBounds.y + seedBounds.height);
  const spaceAbove = seedBounds.y - workArea.y;
  if (!preserveAnchor) {
    expansionDirection = spaceBelow < targetSize.height - seedBounds.height && spaceAbove > spaceBelow
      ? "up"
      : "down";
  }
  const y = expansionDirection === "up"
    ? seedBounds.y + seedBounds.height - targetSize.height
    : seedBounds.y;
  const target = {
    x: clamp(seedBounds.x, workArea.x, workArea.x + workArea.width - targetSize.width),
    y: clamp(y, workArea.y, workArea.y + workArea.height - targetSize.height),
    ...targetSize,
  };
  movingWindowProgrammatically = true;
  windowExpanded = true;
  windowAnalysis = true;
  mainWindow.setMinimumSize(
    Math.min(Math.round(760 * settings.fontScale), target.width),
    Math.min(Math.round(560 * settings.fontScale), target.height),
  );
  mainWindow.setBounds(target, false);
  positionAlertWindow();
  syncControlWindow();
  applyAlwaysOnTop(settings.alwaysOnTop);
  setImmediate(() => { movingWindowProgrammatically = false; });
}

function createAlertWindow(): void {
  const settings = engine?.getState().settings ?? defaultSettings;
  const alertSize = scaledSize(ALERT_SIZE, settings.fontScale);
  alertWindow = new BrowserWindow({
    ...alertSize,
    frame: false,
    transparent: true,
    show: false,
    focusable: false,
    skipTaskbar: true,
    resizable: false,
    alwaysOnTop: settings.alwaysOnTop,
    backgroundColor: "#00000000",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      backgroundThrottling: false,
    },
  });
  // Electron implements this with the X11 input-shape extension on Linux, so no
  // extra XFixes plumbing is needed; only the `forward` option is Windows/macOS.
  alertWindow.setIgnoreMouseEvents(true);
  applyAlwaysOnTop(settings.alwaysOnTop);
  const developmentUrl = process.env.VITE_DEV_SERVER_URL;
  const rendererReady = developmentUrl
    ? alertWindow.loadURL(`${developmentUrl}?alert=1`)
    : alertWindow.loadFile(path.join(app.getAppPath(), "dist", "index.html"), { query: { alert: "1" } });
  void rendererReady.then(() => {
    alertWindow?.webContents.setZoomFactor(settings.fontScale);
    positionAlertWindow();
    alertWindow?.showInactive();
    scheduleTopmostReassertion();
    if (process.env.LOREMASTER_SCREENSHOT_VIEW === "alert" && process.env.LOREMASTER_SCREENSHOT_PATH) {
      alertWindow?.webContents.send("alerts:test", {
        id: "visual-test", severity: "info", title: "TELL · AROMEK",
        target: "Sometimes it feels like maybe I should wait for the next pull before changing stance.",
      });
      setTimeout(() => {
        void alertWindow?.webContents.capturePage().then((image) => {
          if (image && process.env.LOREMASTER_SCREENSHOT_PATH) {
            writeFileSync(process.env.LOREMASTER_SCREENSHOT_PATH, image.toPNG());
          }
          app.quit();
        });
      }, 300);
    }
  });
  alertWindow.on("closed", () => { alertWindow = null; });
}

function createControlWindow(): void {
  const settings = engine?.getState().settings ?? defaultSettings;
  const initialSize = controlSurfaceSize(1, 0, settings.fontScale);
  controlWindow = new BrowserWindow({
    ...initialSize,
    frame: false,
    transparent: true,
    show: false,
    focusable: false,
    skipTaskbar: true,
    resizable: false,
    alwaysOnTop: settings.alwaysOnTop,
    backgroundColor: "#00000000",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      backgroundThrottling: false,
    },
  });
  controlWindow.setIgnoreMouseEvents(true);
  applyAlwaysOnTop(settings.alwaysOnTop);
  const developmentUrl = process.env.VITE_DEV_SERVER_URL;
  const rendererReady = developmentUrl
    ? controlWindow.loadURL(`${developmentUrl}?controls=1`)
    : controlWindow.loadFile(path.join(app.getAppPath(), "dist", "index.html"), { query: { controls: "1" } });
  void rendererReady.then(() => {
    controlWindow?.webContents.setZoomFactor(settings.fontScale);
    syncControlWindow();
    scheduleTopmostReassertion();
    if (process.env.LOREMASTER_SCREENSHOT_VIEW === "controls" && process.env.LOREMASTER_SCREENSHOT_PATH) {
      const fixtureEvent = {
        protocolVersion: 1,
        sequence: 4,
        occurredAt: new Date().toISOString(),
        eventType: "engine.snapshot",
        snapshot: {
          protocolVersion: 1,
          sequence: 4,
          observedAt: new Date().toISOString(),
          character: { name: "Spin", level: 50, composition: "PAL/MNK/ENC", zone: "The Plane of Sky" },
          combat: { fightDps: 328 },
          groupMembers: ["Aromek", "Verdume", "Lilith"],
          encounters: [{
            active: true,
            actors: [
              { name: "Aromek", role: "group", encounterDamage: 48210, encounterDps: 412 },
              { name: "Verdume", role: "group", encounterDamage: 35180, encounterDps: 301 },
              { name: "Lilith", role: "group", encounterDamage: 18490, encounterDps: 158 },
              { name: "Nearby", role: "observed", encounterDamage: 99999, encounterDps: 999 },
            ],
          }],
          controls: screenshotControls,
        },
      };
      const size = controlSurfaceSize(screenshotControls.length, 3, settings.fontScale);
      controlWindow?.setBounds({ x: 80, y: 80, ...size }, false);
      setTimeout(() => {
        controlWindow?.webContents.send("engine:snapshot", fixtureEvent);
        controlWindow?.showInactive();
      }, 300);
      setTimeout(() => {
        void controlWindow?.webContents.capturePage().then((image) => {
          if (image && process.env.LOREMASTER_SCREENSHOT_PATH) {
            writeFileSync(process.env.LOREMASTER_SCREENSHOT_PATH, image.toPNG());
          }
          app.quit();
        });
      }, 800);
    }
  });
  controlWindow.on("closed", () => { controlWindow = null; });
}

function createWindow(): void {
  const settings = engine?.getState().settings ?? defaultSettings;
  const seedSize = scaledSize(SEED_SIZE, settings.fontScale);
  mainWindow = new BrowserWindow({
    ...seedSize,
    ...(settings.seedPosition ?? {}),
    minWidth: 118,
    minHeight: 64,
    maxWidth: 1800,
    maxHeight: 1300,
    resizable: true,
    frame: false,
    thickFrame: false,
    transparent: true,
    show: false,
    alwaysOnTop: settings.alwaysOnTop,
    skipTaskbar: true,
    backgroundColor: "#00000000",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      backgroundThrottling: false,
    },
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("https://")) void shell.openExternal(url);
    return { action: "deny" };
  });

  const developmentUrl = process.env.VITE_DEV_SERVER_URL;
  const rendererReady = developmentUrl
    ? mainWindow.loadURL(developmentUrl)
    : mainWindow.loadFile(path.join(app.getAppPath(), "dist", "index.html"));
  // The window is created hidden and only revealed here, so anything that
  // rejects or throws on the way to showInactive() used to leave a tray icon
  // and no window, with nothing logged -- indistinguishable from a hang. Load
  // failures and setup failures are now reported, and the window is shown
  // regardless, so a partially configured window still beats an invisible one.
  void rendererReady.catch((error) => {
    console.error("[Loremaster] renderer failed to load", error);
  }).then(() => {
    try {
      mainWindow?.webContents.on("will-navigate", (event) => event.preventDefault());
      mainWindow?.webContents.setZoomFactor(settings.fontScale);
      setWindowMode(false);
    } catch (error) {
      console.error("[Loremaster] window setup failed; showing anyway", error);
    }
    mainWindow?.showInactive();
    console.log("[Loremaster] window shown",
      JSON.stringify({
        visible: mainWindow?.isVisible(),
        bounds: mainWindow?.getBounds(),
      }));
    createAlertWindow();
    createControlWindow();
    applyAlwaysOnTop(settings.alwaysOnTop);
    const topmostProbePath = process.env.LOREMASTER_TOPMOST_PROBE_PATH;
    if (topmostProbePath) {
      const rawProbeScale = Number(process.env.LOREMASTER_TOPMOST_PROBE_SCALE || 1.15);
      const requestedScale = clamp(Number.isFinite(rawProbeScale) ? rawProbeScale : 1.15, 0.9, 1.6);
      engine?.updateDesktopSettings({ alwaysOnTop: true, fontScale: requestedScale });
      setTimeout(() => {
        const report = {
          requestedScale,
          configuredScale: engine?.getState().settings.fontScale,
          windows: {
            main: Boolean(mainWindow?.isAlwaysOnTop()),
            alert: Boolean(alertWindow?.isAlwaysOnTop()),
            controls: Boolean(controlWindow?.isAlwaysOnTop()),
          },
          mainBounds: mainWindow?.getBounds(),
        };
        writeFileSync(topmostProbePath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
        app.quit();
      }, 500);
    }
    const positionProbePath = process.env.LOREMASTER_POSITION_PROBE_PATH;
    const positionProbeWindow = mainWindow;
    if (positionProbePath && positionProbeWindow) {
      setTimeout(() => {
        const initialSeed = positionProbeWindow.getBounds();
        setWindowMode(true);
        const hud = positionProbeWindow.getBounds();
        setAnalysisMode(true);
        const analysis = positionProbeWindow.getBounds();
        setAnalysisMode(false);
        const hudAfterAnalysis = positionProbeWindow.getBounds();
        setWindowMode(false);
        const finalSeed = positionProbeWindow.getBounds();
        writeFileSync(positionProbePath, `${JSON.stringify({
          scale: engine?.getState().settings.fontScale,
          initialSeed,
          hud,
          analysis,
          hudAfterAnalysis,
          finalSeed,
          savedSeedPosition: engine?.getState().settings.seedPosition,
        }, null, 2)}\n`, "utf8");
        app.quit();
      }, 350);
    }
    const trayProbePath = process.env.LOREMASTER_TRAY_PROBE_PATH;
    if (trayProbePath && mainWindow) {
      setTimeout(() => {
        minimizeLoremasterWindow();
        const minimized = {
          trayAvailable: Boolean(tray && !tray.isDestroyed()),
          mainVisible: Boolean(mainWindow?.isVisible()),
          alertVisible: Boolean(alertWindow?.isVisible()),
          controlsVisible: Boolean(controlWindow?.isVisible()),
        };
        restoreLoremasterWindow();
        const restored = {
          mainVisible: Boolean(mainWindow?.isVisible()),
          mainMinimized: Boolean(mainWindow?.isMinimized()),
        };
        writeFileSync(trayProbePath, `${JSON.stringify({ minimized, restored }, null, 2)}\n`, "utf8");
        quitLoremaster();
      }, 500);
    }
    const screenshotPath = process.env.LOREMASTER_SCREENSHOT_PATH;
    if (screenshotPath && mainWindow && !["alert", "controls"].includes(process.env.LOREMASTER_SCREENSHOT_VIEW ?? "")) {
      const screenshotView = process.env.LOREMASTER_SCREENSHOT_VIEW;
      void (screenshotView?.startsWith("seed")
        ? Promise.resolve()
        : mainWindow.webContents.executeJavaScript(
          "document.querySelector('.seed-action')?.click()",
        )).then(() => new Promise((resolve) => setTimeout(resolve, screenshotView?.startsWith("seed") ? 250 : 500)))
        .then(() => screenshotView === "seed-attack"
          ? mainWindow?.webContents.executeJavaScript(
            "document.querySelector('.rune-seed')?.classList.add('attacking')")
          : undefined)
        .then(() => screenshotView === "settings"
          ? mainWindow?.webContents.executeJavaScript(
            "document.querySelector('.masthead-actions button')?.click()")
          : screenshotView === "analysis"
            ? mainWindow?.webContents.executeJavaScript(
              "document.querySelector('button[aria-label=\"Open full combat breakdown\"]')?.click()")
          : screenshotView === "breakdown"
            ? mainWindow?.webContents.executeJavaScript(`
              document.querySelector('.encounter-nav button:not(:disabled)')?.click();
              const details = document.querySelector('.breakdown-card');
              if (details) { details.open = true; details.scrollIntoView({ block: 'start' }); }
            `)
          : undefined)
        .then(() => new Promise((resolve) => setTimeout(resolve, 250)))
        .then(() => mainWindow?.webContents.capturePage())
        .then((image) => {
          if (image) writeFileSync(screenshotPath, image.toPNG());
          app.quit();
        }).catch((error: unknown) => {
          console.error("Loremaster screenshot capture failed", error);
          app.exit(1);
        });
    }
  }).catch((error: unknown) => {
    console.error("Loremaster renderer failed to load", error);
    app.exit(1);
  });
  mainWindow.on("closed", () => {
    alertWindow?.close();
    controlWindow?.close();
    mainWindow = null;
  });
  mainWindow.on("show", scheduleTopmostReassertion);
  mainWindow.on("restore", () => {
    if (tray) mainWindow?.setSkipTaskbar(true);
    scheduleTopmostReassertion();
  });
  mainWindow.on("focus", scheduleTopmostReassertion);
  mainWindow.on("blur", scheduleTopmostReassertion);
  mainWindow.on("resize", scheduleTopmostReassertion);
  mainWindow.on("move", () => {
    positionAlertWindow();
    syncControlWindow();
    if (!windowExpanded && !movingWindowProgrammatically && mainWindow) {
      const bounds = mainWindow.getBounds();
      engine?.saveSeedPosition({ x: bounds.x, y: bounds.y });
    }
  });
}

function registerLockoutScanHotkey(): void {
  let registered = false;
  try {
    registered = globalShortcut.register("CommandOrControl+Shift+Z", () => engine?.scanAltZLockouts());
  } catch (error) {
    // Some X11 setups reject the grab outright rather than returning false.
    console.error("Could not register the Ctrl+Shift+Z Alt+Z lockout scan hotkey", error);
  }
  if (registered) return;
  console.error("Could not register the Ctrl+Shift+Z Alt+Z lockout scan hotkey");
  notifyUser(
    "Loremaster hotkey unavailable",
    "Ctrl+Shift+Z is already claimed by another app, so Alt+Z lockout scanning is off."
      + " Free that shortcut and restart Loremaster, or tick raid lockouts by hand.",
  );
}

ipcMain.handle("runtime:metrics", () => ({
  coldStartMs: Math.round(performance.now() - processStartedAt),
  residentMemoryMb: Math.round(process.memoryUsage().rss / 1024 / 1024),
  platform: process.platform,
}));

ipcMain.handle("engine:get-state", () => engine?.getState() ?? {
  health: defaultHealth, snapshot: null,
  settings: defaultSettings,
  gearPlan: emptyGearPlan(),
});
ipcMain.handle("engine:choose-log-folder", async () => {
  if (!mainWindow) return null;
  const result = await dialog.showOpenDialog(mainWindow, {
    title: "Choose your EverQuest Legends folder or Logs folder",
    properties: ["openDirectory"],
  });
  if (result.canceled || result.filePaths.length !== 1) return null;
  engine?.setLogPath(result.filePaths[0]);
  return result.filePaths[0];
});
ipcMain.handle("engine:set-log-path", (_event, value: unknown) => {
  if (typeof value !== "string" || value.length > 4096) return false;
  engine?.setLogPath(value);
  return true;
});
ipcMain.handle("engine:set-raid-difficulty", (_event, value: unknown) => {
  if (value !== null && (!Number.isInteger(value) || Number(value) < 0 || Number(value) > 4)) return false;
  engine?.setRaidDifficulty(value === null ? null : Number(value));
  return true;
});
ipcMain.handle("engine:set-raid-completion", (_event, target: unknown, difficulty: unknown, completed: unknown) => {
  if (typeof target !== "string" || target.length > 128 || !Number.isInteger(difficulty) || Number(difficulty) < 0 || Number(difficulty) > 4 || typeof completed !== "boolean") return false;
  engine?.setRaidCompletion(target, Number(difficulty), completed);
  return true;
});
ipcMain.on("engine:reset", () => engine?.reset());
ipcMain.on("alerts:test", () => {
  positionAlertWindow();
  alertWindow?.webContents.send("alerts:test", {
    id: `test-${Date.now()}`,
    severity: "info",
    title: "LOREMASTER ALERT READY",
    target: "Placement and sound are working",
  });
});

ipcMain.handle("settings:update", (_event, value: unknown) => {
  if (!value || typeof value !== "object" || !engine) return null;
  const raw = value as Record<string, unknown>;
  const patch: Parameters<EngineSupervisor["updateDesktopSettings"]>[0] = {};
  if (typeof raw.alwaysOnTop === "boolean") patch.alwaysOnTop = raw.alwaysOnTop;
  if (Number.isFinite(Number(raw.fontScale))) patch.fontScale = clamp(Number(raw.fontScale), 0.9, 1.6);
  if (typeof raw.composition === "string") patch.composition = raw.composition.slice(0, 48);
  if (typeof raw.splitCharmedPetDps === "boolean") patch.splitCharmedPetDps = raw.splitCharmedPetDps;
  if (typeof raw.stanceAdvisorEnabled === "boolean") patch.stanceAdvisorEnabled = raw.stanceAdvisorEnabled;
  if (raw.alerts && typeof raw.alerts === "object") {
    const candidate = raw.alerts as Record<string, unknown>;
    const alerts: Partial<AlertSettings> = {};
    const booleanKeys: (keyof AlertSettings)[] = [
      "alertsEnabled", "alertSound", "alertCharmBreak", "alertTells", "alertSummon",
      "alertDeath", "alertBigHit", "alertNameCalled", "mezTimersEnabled", "mezTimerSound",
      "lullTimersEnabled", "lullTimerSound",
    ];
    for (const key of booleanKeys) if (typeof candidate[key] === "boolean") Object.assign(alerts, { [key]: candidate[key] });
    if (["auto", "above", "below", "left", "right"].includes(String(candidate.alertAnchor))) {
      alerts.alertAnchor = candidate.alertAnchor as AlertAnchor;
    }
    const numericRanges: Record<string, [number, number]> = {
      alertSeconds: [1, 15], bigHitThreshold: [1, 999999], mezWarningSeconds: [3, 30], lullWarningSeconds: [3, 30],
    };
    for (const [key, [low, high]] of Object.entries(numericRanges)) {
      const numeric = Number(candidate[key]);
      if (Number.isFinite(numeric)) Object.assign(alerts, { [key]: clamp(Math.round(numeric), low, high) });
    }
    patch.alerts = alerts;
  }
  return engine.updateDesktopSettings(patch);
});

ipcMain.handle("gear:choose-build", async () => {
  if (!mainWindow || !engine) return null;
  const result = await dialog.showOpenDialog(mainWindow, {
    title: "Import EQ Legends Tools character build",
    properties: ["openFile"],
    filters: [{ name: "EQ Legends Tools character JSON", extensions: ["json"] }],
  });
  if (result.canceled || result.filePaths.length !== 1) return null;
  await engine.setBisBuildPath(result.filePaths[0]);
  return result.filePaths[0];
});
ipcMain.handle("gear:choose-inventory", async () => {
  if (!mainWindow || !engine) return null;
  const result = await dialog.showOpenDialog(mainWindow, {
    title: "Import EverQuest /outputfile inventory",
    properties: ["openFile"],
    filters: [{ name: "EverQuest inventory", extensions: ["txt"] }],
  });
  if (result.canceled || result.filePaths.length !== 1) return null;
  engine.setInventoryPath(result.filePaths[0]);
  return result.filePaths[0];
});
ipcMain.handle("gear:refresh", () => engine?.refreshGearCatalog() ?? false);
ipcMain.handle("external:open", async (_event, value: unknown) => {
  if (typeof value !== "string") return false;
  try {
    const url = new URL(value);
    const allowedHosts = new Set(["eqlegendstools.com", "www.eqlegendstools.com", "github.com"]);
    if (url.protocol !== "https:" || !allowedHosts.has(url.hostname)) return false;
    await shell.openExternal(url.toString());
    return true;
  } catch {
    return false;
  }
});
ipcMain.handle("updates:check", async () => {
  const currentVersion = app.getVersion();
  try {
    const response = await fetch("https://api.github.com/repos/itsspin/spinips/releases/latest", {
      headers: {
        Accept: "application/vnd.github+json",
        "User-Agent": `Loremaster/${currentVersion}`,
        "X-GitHub-Api-Version": "2022-11-28",
      },
    });
    if (!response.ok) throw new Error(`GitHub returned HTTP ${response.status}`);
    const value = await response.json() as Record<string, unknown>;
    const latestVersion = String(value.tag_name ?? "").replace(/^v/i, "");
    const releaseUrl = String(value.html_url ?? "https://github.com/itsspin/spinips/releases/latest");
    return {
      ok: true,
      currentVersion,
      latestVersion,
      updateAvailable: Boolean(latestVersion && latestVersion !== currentVersion),
      releaseUrl,
      detail: latestVersion === currentVersion
        ? "Loremaster is up to date."
        : `Release ${latestVersion || "latest"} is available on GitHub.`,
    };
  } catch (error) {
    return {
      ok: false,
      currentVersion,
      latestVersion: "",
      updateAvailable: false,
      releaseUrl: "https://github.com/itsspin/spinips/releases/latest",
      detail: error instanceof Error ? error.message : String(error),
    };
  }
});

ipcMain.on("window:set-mode", (_event, expanded: boolean) => {
  setWindowMode(Boolean(expanded));
});
ipcMain.on("window:set-analysis", (_event, active: boolean) => {
  setAnalysisMode(Boolean(active));
});

ipcMain.on("window:minimize", minimizeLoremasterWindow);
ipcMain.on("window:close", quitLoremaster);

app.whenReady().then(() => {
  if (!ownsSingleInstance) return;
  engine = new EngineSupervisor();
  engine.start();
  createWindow();
  ensureTray();
  registerLockoutScanHotkey();
  startTopmostHeartbeat();
  screen.on("display-metrics-changed", scheduleTopmostReassertion);
  const smokeExitMs = Number(process.env.LOREMASTER_SMOKE_EXIT_MS || 0);
  if (Number.isFinite(smokeExitMs) && smokeExitMs >= 250) {
    setTimeout(() => app.quit(), smokeExitMs);
  }
});
app.on("before-quit", () => {
  globalShortcut.unregisterAll();
  clearTopmostReassertions();
  if (topmostHeartbeatTimer) clearInterval(topmostHeartbeatTimer);
  topmostHeartbeatTimer = null;
  tray?.destroy();
  tray = null;
  engine?.stop();
});
app.on("window-all-closed", () => app.quit());
app.on("second-instance", restoreLoremasterWindow);
app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
  else restoreLoremasterWindow();
});
