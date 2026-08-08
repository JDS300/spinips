import { useEffect, useMemo, useRef, useState } from "react";
import {
  PROTOCOL_VERSION,
  isEngineHealth,
  isEngineSnapshotEvent,
  isGearPlanView,
  type ControlTimerView,
  type DesktopSettings,
  type EngineHealth,
  type EngineSnapshotEvent,
  type GearPlanView,
} from "./protocol";

const roman = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"];
const raidDifficulties = [0, 1, 2, 3, 4] as const;
const cogSource = "./loremaster-cog.png";
const eqToolsUrl = "https://eqlegendstools.com/";
const eqToolsCharSheetUrl = "https://eqlegendstools.com/char-sheet/";

const defaultDesktopSettings: DesktopSettings = {
  logPath: "", raidDifficulty: null, bisBuildPath: "", inventoryPath: "",
  alwaysOnTop: true, fontScale: 1.1, splitCharmedPetDps: false, seedPosition: null,
  alerts: {
    alertsEnabled: true, alertSound: true, alertSeconds: 5, alertAnchor: "auto",
    alertCharmBreak: true, alertTells: true, alertSummon: true, alertDeath: true,
    alertBigHit: true, alertNameCalled: true, bigHitThreshold: 800,
    mezTimersEnabled: true, mezTimerSound: false, mezWarningSeconds: 10,
    lullTimersEnabled: true, lullTimerSound: false, lullWarningSeconds: 12,
  },
};

const emptyGearPlan: GearPlanView = {
  status: "empty", detail: "Import an EQ Legends Tools character build to begin.",
  buildName: "", classes: [], exportedAt: "", buildPath: "", inventoryPath: "",
  catalogUpdatedAt: "", goals: [], equippedGoalCount: 0, bagUpgradeCount: 0,
  ownedGoalCount: 0, missingGoalCount: 0, routes: [],
};

const emptyEvent: EngineSnapshotEvent = {
  protocolVersion: PROTOCOL_VERSION,
  sequence: 0,
  occurredAt: new Date(0).toISOString(),
  eventType: "engine.snapshot",
  snapshot: {
    protocolVersion: PROTOCOL_VERSION,
    sequence: 0,
    observedAt: new Date(0).toISOString(),
    character: { name: "?", level: 0, composition: "", zone: "" },
    combat: {
      active: false, encounterName: "", fightDps: 0, sessionDps: 0,
      personalDamage: 0, charmedPetDamage: 0, summonedPetDamage: 0,
      fightSeconds: 0, fightDamage: 0, fightPersonalDamage: 0,
      fightCharmedPetDamage: 0, fightSummonedPetDamage: 0,
      damageTaken: 0, healingDone: 0, kills: 0, crits: 0, misses: 0,
    },
    breakdown: { sources: [], targets: [], actors: [] },
    controls: [], hiddenControlRows: 0, controlNoticeCount: 0,
    controlAmbiguityCount: 0,
  },
};

const initialHealth: EngineHealth = {
  state: "starting",
  detail: "Starting the local parser engine",
  configuredPath: "",
  activeLogPath: "",
  character: "?",
  server: "?",
};

function formatDps(value: number): string {
  return value >= 1000 ? `${(value / 1000).toFixed(value >= 10000 ? 0 : 1)}k` : String(Math.round(value));
}

function formatDuration(value: number): string {
  const seconds = Math.max(0, Math.floor(value));
  const minutes = Math.floor(seconds / 60);
  const remainder = String(seconds % 60).padStart(2, "0");
  return minutes > 0 ? `${minutes}:${remainder}` : `${seconds}s`;
}

function spellLabel(control: ControlTimerView): string {
  const rank = control.rank > 0 ? roman[control.rank] ?? String(control.rank) : "";
  return `${control.spell}${rank ? ` ${rank}` : ""}`;
}

function phaseLabel(control: ControlTimerView): string {
  if (control.state !== "active") return `? ${control.state.toUpperCase()}`;
  if (control.lastTick) return "!! LAST TICK";
  if (control.urgency === "critical") return "!! CRITICAL";
  if (control.urgency === "warning") return "! WARNING";
  return "SAFE";
}

function ControlRow({ control }: { control: ControlTimerView }) {
  const progress = control.durationSeconds > 0
    ? Math.max(0, Math.min(1, control.safeRemainingSeconds / control.durationSeconds))
    : 0;
  const detail = control.state === "active"
    ? `${control.kind.toUpperCase()} · ${spellLabel(control)} · ${control.confidence.toUpperCase()}`
    : `${control.kind.toUpperCase()} · ${spellLabel(control)} · ${control.ambiguity}`;
  return (
    <article
      className={`control-row ${control.kind} ${control.state} ${control.urgency}`}
      aria-label={`${control.kind} ${control.target} ${phaseLabel(control)}`}
    >
      <span className="control-accent" aria-hidden="true" />
      <div className="control-copy">
        <strong>{control.target}{control.count > 1 ? ` ×${control.count} · earliest` : ""}</strong>
        <small>{detail}</small>
      </div>
      <div className="control-time">
        <strong>{control.state === "active" ? `${Math.ceil(control.safeRemainingSeconds)}s` : "—"}</strong>
        <small>{phaseLabel(control)}</small>
      </div>
      {control.state === "active" && (
        <span className="control-meter" aria-hidden="true">
          <span style={{ transform: `scaleX(${progress})` }} />
        </span>
      )}
    </article>
  );
}

function CogMark({ compact = false }: { compact?: boolean }) {
  return <span className={`brand-cog ${compact ? "compact" : ""}`} aria-hidden="true">
    <img src={cogSource} alt="" />
  </span>;
}

function RuneSeed({ event, health, onExpand }: {
  event: EngineSnapshotEvent;
  health: EngineHealth;
  onExpand: () => void;
}) {
  const { combat } = event.snapshot;
  const urgent = health.state === "error" || Boolean(event.snapshot.alerts?.length) || event.snapshot.controls.some((control) =>
    control.state !== "active" || control.urgency !== "safe");
  return (
    <div className={`rune-seed ${urgent ? "urgent" : ""}`}>
      <span className="seed-drag" aria-hidden="true" />
      <button className="seed-action" onClick={onExpand} type="button"
        aria-label={`${formatDps(combat.fightDps)} DPS${urgent ? ", urgent signal" : ""}`}>
        <CogMark compact />
        <span className="seed-metric"><strong>{formatDps(combat.fightDps)}</strong><small>DPS</small></span>
      </button>
      {urgent && <span className="seed-alert" aria-label="urgent signal">!</span>}
    </div>
  );
}

function SeedControlRow({ control }: { control: ControlTimerView }) {
  const progress = control.durationSeconds > 0
    ? Math.max(0, Math.min(1, control.safeRemainingSeconds / control.durationSeconds))
    : 0;
  const seconds = Math.ceil(control.safeRemainingSeconds > 0
    ? control.safeRemainingSeconds
    : control.remainingSeconds);
  return <article className={`seed-control-row ${control.kind} ${control.urgency}`}>
    <i className="seed-control-accent" aria-hidden="true" />
    <span className="seed-control-copy">
      <strong>{control.target}{control.count > 1 ? ` ×${control.count}` : ""}</strong>
      <small>{control.kind.toUpperCase()} · {spellLabel(control)}</small>
    </span>
    <span className="seed-control-time">
      <strong>{seconds}s</strong>
      <small>{phaseLabel(control)}</small>
    </span>
    <i className="seed-control-meter" aria-hidden="true"><i style={{ transform: `scaleX(${progress})` }} /></i>
  </article>;
}

function SeedControlSurface() {
  const [event, setEvent] = useState(emptyEvent);
  const [settings, setSettings] = useState(defaultDesktopSettings);
  useEffect(() => {
    document.body.classList.add("control-window");
    const desktop = window.loremasterDesktop;
    if (!desktop) return () => document.body.classList.remove("control-window");
    void desktop.getEngineState().then((state) => {
      if (isEngineSnapshotEvent(state.snapshot)) setEvent(state.snapshot);
      setSettings(state.settings);
    });
    const removeSnapshot = desktop.onSnapshot((value) => {
      if (isEngineSnapshotEvent(value)) setEvent(value);
    });
    const removeSettings = desktop.onSettings((value) => {
      if (value && typeof value === "object") setSettings(value as DesktopSettings);
    });
    return () => {
      removeSnapshot();
      removeSettings();
      document.body.classList.remove("control-window");
    };
  }, []);

  const controls = event.snapshot.controls.filter((control) =>
    control.state === "active" &&
    (control.kind === "mez" ? settings.alerts.mezTimersEnabled : settings.alerts.lullTimersEnabled),
  ).slice(0, 6);
  if (controls.length === 0) return <div className="seed-control-surface empty" />;
  return <section className="seed-control-surface" aria-live="polite" aria-label="Active mez and lull timers">
    <header><span><i /> CONTROL</span><strong>{controls.length} ACTIVE · MEZ / LULL</strong></header>
    <div>{controls.map((control, index) => <SeedControlRow
      key={`${control.kind}-${control.target}-${control.landedAt}-${index}`}
      control={control}
    />)}</div>
  </section>;
}

function SettingsToggle({ checked, label, detail, onChange }: {
  checked: boolean; label: string; detail?: string; onChange: (checked: boolean) => void;
}) {
  return <label className="settings-toggle"><span><b>{label}</b>{detail && <small>{detail}</small>}</span>
    <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} /><i /></label>;
}

function SettingsPanel({ health, raidDifficulty, settings, onSettings, onRaidDifficulty, onClose }: {
  health: EngineHealth;
  raidDifficulty: number | null;
  settings: DesktopSettings;
  onSettings: (settings: DesktopSettings) => void;
  onRaidDifficulty: (value: number | null) => void;
  onClose: () => void;
}) {
  const [manualPath, setManualPath] = useState(health.configuredPath);
  const [draft, setDraft] = useState(settings);
  const [updateInfo, setUpdateInfo] = useState<Awaited<ReturnType<NonNullable<typeof window.loremasterDesktop>["checkForUpdates"]>> | null>(null);
  const [checkingUpdate, setCheckingUpdate] = useState(false);
  const chooseFolder = async () => {
    const selected = await window.loremasterDesktop?.chooseLogFolder();
    if (selected) setManualPath(selected);
  };
  const saveManual = async () => {
    await window.loremasterDesktop?.setLogPath(manualPath.trim());
    onClose();
  };
  const checkForUpdates = async () => {
    setCheckingUpdate(true);
    try {
      const result = await window.loremasterDesktop?.checkForUpdates();
      if (result) setUpdateInfo(result);
    } finally {
      setCheckingUpdate(false);
    }
  };
  const patchDraft = (value: Partial<DesktopSettings>) => setDraft((current) => ({ ...current, ...value }));
  const patchAlerts = (value: Partial<DesktopSettings["alerts"]>) => setDraft((current) => ({
    ...current, alerts: { ...current.alerts, ...value },
  }));
  const savePreferences = async () => {
    const saved = await window.loremasterDesktop?.updateSettings({
      alwaysOnTop: draft.alwaysOnTop,
      fontScale: draft.fontScale,
      splitCharmedPetDps: draft.splitCharmedPetDps,
      alerts: draft.alerts,
    });
    if (saved) onSettings(saved);
  };
  const changeFontScale = async (delta: number) => {
    const fontScale = Math.max(0.9, Math.min(1.4, Math.round((draft.fontScale + delta) * 20) / 20));
    setDraft((current) => ({ ...current, fontScale }));
    const saved = await window.loremasterDesktop?.updateSettings({ fontScale });
    if (saved) onSettings(saved);
  };
  return (
    <section className="settings-panel" aria-label="Loremaster settings">
      <header><div><small>CONFIGURATION</small><h2>ENGINE + LOGS</h2></div><button onClick={onClose}>DONE</button></header>
      <article className="settings-card">
        <label htmlFor="eq-path">EVERQUEST DIRECTORY</label>
        <p>Choose the game folder or its Logs folder. Loremaster automatically follows the newest character log.</p>
        <div className="path-row">
          <input id="eq-path" value={manualPath} onChange={(event) => setManualPath(event.target.value)}
            placeholder="Auto-detect common EverQuest locations" />
          <button type="button" onClick={() => void chooseFolder()}>CHANGE</button>
        </div>
        <div className={`engine-status ${health.state}`}><i /><span><b>{health.state.toUpperCase()}</b>{health.detail}</span></div>
        {health.activeLogPath && <code title={health.activeLogPath}>{health.activeLogPath}</code>}
        <div className="settings-actions">
          <button type="button" onClick={() => void saveManual()}>SAVE LOCATION</button>
          <button type="button" onClick={() => { setManualPath(""); void window.loremasterDesktop?.setLogPath(""); }}>USE AUTO-DETECT</button>
        </div>
      </article>
      <article className="settings-card">
        <label>HUD BEHAVIOR</label>
        <p>The Rune Seed stays edge-safe, remembers its location, and can remain visible above EverQuest.</p>
        <SettingsToggle checked={draft.alwaysOnTop} label="Keep Loremaster above EverQuest"
          onChange={(alwaysOnTop) => patchDraft({ alwaysOnTop })} />
        <SettingsToggle checked={draft.splitCharmedPetDps} label="Split self and charmed-pet DPS"
          detail="Shows separate live fight rates while preserving the accurate combined total."
          onChange={(splitCharmedPetDps) => patchDraft({ splitCharmedPetDps })} />
        <div className="font-scale-setting">
          <span><b>HUD TEXT SIZE</b><small>Applies immediately to the Seed, expanded HUD, settings, and alerts.</small></span>
          <div><button type="button" aria-label="Decrease HUD text size" onClick={() => void changeFontScale(-0.05)}>A−</button>
            <strong>{Math.round(draft.fontScale * 100)}%</strong>
            <button type="button" aria-label="Increase HUD text size" onClick={() => void changeFontScale(0.05)}>A+</button></div>
        </div>
      </article>
      <article className="settings-card">
        <label>CROWD CONTROL TIMERS</label>
        <p>Only confirmed own-cast control is timed. Warning thresholds use the guaranteed-safe window.</p>
        <SettingsToggle checked={draft.alerts.mezTimersEnabled} label="Show mez timers"
          onChange={(mezTimersEnabled) => patchAlerts({ mezTimersEnabled })} />
        <SettingsToggle checked={draft.alerts.mezTimerSound} label="Sound when mez becomes urgent"
          onChange={(mezTimerSound) => patchAlerts({ mezTimerSound })} />
        <div className="number-setting"><span>MEZ WARNING</span><input type="number" min="3" max="30"
          value={draft.alerts.mezWarningSeconds} onChange={(event) => patchAlerts({ mezWarningSeconds: Number(event.target.value) })} /><b>SEC</b></div>
        <SettingsToggle checked={draft.alerts.lullTimersEnabled} label="Show lull timers"
          onChange={(lullTimersEnabled) => patchAlerts({ lullTimersEnabled })} />
        <SettingsToggle checked={draft.alerts.lullTimerSound} label="Sound when lull becomes urgent"
          onChange={(lullTimerSound) => patchAlerts({ lullTimerSound })} />
        <div className="number-setting"><span>LULL WARNING</span><input type="number" min="3" max="30"
          value={draft.alerts.lullWarningSeconds} onChange={(event) => patchAlerts({ lullWarningSeconds: Number(event.target.value) })} /><b>SEC</b></div>
      </article>
      <article className="settings-card">
        <label>ALERTS + PLACEMENT</label>
        <p>Alerts use a separate click-through surface so they remain readable beside the Seed without stealing input from EQ.</p>
        <SettingsToggle checked={draft.alerts.alertsEnabled} label="Enable alert banners"
          onChange={(alertsEnabled) => patchAlerts({ alertsEnabled })} />
        <SettingsToggle checked={draft.alerts.alertSound} label="Play alert sound"
          onChange={(alertSound) => patchAlerts({ alertSound })} />
        <div className="anchor-picker" role="group" aria-label="Alert location">
          {(["auto", "above", "below", "left", "right"] as const).map((anchor) => <button type="button"
            className={draft.alerts.alertAnchor === anchor ? "selected" : ""} key={anchor}
            onClick={() => patchAlerts({ alertAnchor: anchor })}>{anchor.toUpperCase()}</button>)}
        </div>
        <div className="trigger-grid">
          <SettingsToggle checked={draft.alerts.alertCharmBreak} label="Charm break" onChange={(alertCharmBreak) => patchAlerts({ alertCharmBreak })} />
          <SettingsToggle checked={draft.alerts.alertTells} label="Incoming tells" onChange={(alertTells) => patchAlerts({ alertTells })} />
          <SettingsToggle checked={draft.alerts.alertSummon} label="Summoned" onChange={(alertSummon) => patchAlerts({ alertSummon })} />
          <SettingsToggle checked={draft.alerts.alertDeath} label="Death" onChange={(alertDeath) => patchAlerts({ alertDeath })} />
          <SettingsToggle checked={draft.alerts.alertBigHit} label="Big hit" onChange={(alertBigHit) => patchAlerts({ alertBigHit })} />
          <SettingsToggle checked={draft.alerts.alertNameCalled} label="Name called" onChange={(alertNameCalled) => patchAlerts({ alertNameCalled })} />
        </div>
        <div className="number-setting"><span>BIG HIT</span><input type="number" min="1" max="999999"
          value={draft.alerts.bigHitThreshold} onChange={(event) => patchAlerts({ bigHitThreshold: Number(event.target.value) })} /><b>DMG</b></div>
        <div className="number-setting"><span>BANNER LIFE</span><input type="number" min="1" max="15"
          value={draft.alerts.alertSeconds} onChange={(event) => patchAlerts({ alertSeconds: Number(event.target.value) })} /><b>SEC</b></div>
        <button type="button" onClick={() => window.loremasterDesktop?.testAlert()}>TEST ALERT</button>
        <button className="save-preferences" type="button" onClick={() => void savePreferences()}>SAVE HUD + ALERT SETTINGS</button>
      </article>
      <article className="settings-card">
        <label>ACTIVE RAID DIFFICULTY</label>
        <p>The EQ text log names the defeated boss but not its D0–D4 tier. Select the tier before a raid so automatic lockouts stay accurate.</p>
        <div className="difficulty-picker" role="group" aria-label="Active raid difficulty">
          {raidDifficulties.map((difficulty) => <button
            className={raidDifficulty === difficulty ? "selected" : ""}
            key={difficulty}
            type="button"
            aria-pressed={raidDifficulty === difficulty}
            onClick={() => onRaidDifficulty(difficulty)}
          >D{difficulty}</button>)}
          <button className={raidDifficulty === null ? "selected unset" : "unset"} type="button"
            aria-pressed={raidDifficulty === null} onClick={() => onRaidDifficulty(null)}>UNSET</button>
        </div>
      </article>
      <article className="settings-card">
        <label>BEST-IN-SLOT GEAR PATH</label>
        <p>Build and export your desired character on EQ Legends Tools, then import its JSON here. Run <code className="inline-code">/outputfile inventory</code> in game and import the resulting TXT to find goal pieces already in your bags.</p>
        <div className="gear-import-actions">
          <button type="button" onClick={() => void window.loremasterDesktop?.openExternal(eqToolsCharSheetUrl)}>BUILD ON EQL TOOLS ↗</button>
          <button type="button" onClick={() => void window.loremasterDesktop?.chooseBisBuild()}>IMPORT BUILD JSON</button>
          <button type="button" onClick={() => void window.loremasterDesktop?.chooseInventory()}>IMPORT INVENTORY</button>
          <button type="button" onClick={() => void window.loremasterDesktop?.refreshGearData()}>REFRESH SOURCES</button>
        </div>
        <p className="source-credit">Gear data and character-sheet workflow by <button type="button" onClick={() => void window.loremasterDesktop?.openExternal(eqToolsUrl)}>EQ Legends Tools ↗</button>, created by FlammHammer.</p>
      </article>
      <article className="settings-card compact">
        <label>SESSION</label>
        <p>Reset live encounter and session totals. Weekly boss history remains intact.</p>
        <button type="button" onClick={() => window.loremasterDesktop?.resetEngine()}>RESET SESSION</button>
      </article>
      <article className="settings-card compact update-card">
        <label>UPDATES</label>
        <p>{updateInfo?.detail || "Check the official GitHub release feed for a newer portable Loremaster build."}</p>
        <button type="button" disabled={checkingUpdate} onClick={() => void checkForUpdates()}>{checkingUpdate ? "CHECKING…" : "CHECK GITHUB"}</button>
        {updateInfo?.updateAvailable && <button className="update-ready" type="button"
          onClick={() => void window.loremasterDesktop?.openExternal(updateInfo.releaseUrl)}>GET {updateInfo.latestVersion} ↗</button>}
      </article>
    </section>
  );
}

function playSignal(severity: "danger" | "warn" | "info") {
  try {
    const context = new AudioContext();
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.type = "sine";
    oscillator.frequency.value = severity === "danger" ? 740 : severity === "warn" ? 560 : 440;
    gain.gain.setValueAtTime(0.0001, context.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.16, context.currentTime + 0.015);
    gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + 0.28);
    oscillator.connect(gain).connect(context.destination);
    oscillator.start();
    oscillator.stop(context.currentTime + 0.3);
    oscillator.addEventListener("ended", () => void context.close());
  } catch {
    // The visual alert remains authoritative if an audio device is absent.
  }
}

function AlertSurface() {
  const [event, setEvent] = useState(emptyEvent);
  const [settings, setSettings] = useState(defaultDesktopSettings);
  const [testAlert, setTestAlert] = useState<{ id: string; severity: "danger" | "warn" | "info"; title: string; target: string } | null>(null);
  const sounded = useRef(new Set<string>());
  useEffect(() => {
    document.body.classList.add("alert-window");
    const desktop = window.loremasterDesktop;
    if (!desktop) return () => document.body.classList.remove("alert-window");
    void desktop.getEngineState().then((state) => {
      if (isEngineSnapshotEvent(state.snapshot)) setEvent(state.snapshot);
      setSettings(state.settings);
    });
    const removeSnapshot = desktop.onSnapshot((value) => {
      if (isEngineSnapshotEvent(value)) setEvent(value);
    });
    const removeSettings = desktop.onSettings((value) => {
      if (value && typeof value === "object") setSettings(value as DesktopSettings);
    });
    const removeTest = desktop.onTestAlert((value) => {
      if (!value || typeof value !== "object") return;
      const alert = value as { id?: unknown; severity?: unknown; title?: unknown; target?: unknown };
      if (typeof alert.id !== "string" || typeof alert.title !== "string" || typeof alert.target !== "string") return;
      const severity = ["danger", "warn", "info"].includes(String(alert.severity))
        ? alert.severity as "danger" | "warn" | "info" : "info";
      setTestAlert({ id: alert.id, severity, title: alert.title, target: alert.target });
      setTimeout(() => setTestAlert((current) => current?.id === alert.id ? null : current), 5000);
    });
    return () => { removeSnapshot(); removeSettings(); removeTest(); document.body.classList.remove("alert-window"); };
  }, []);

  const explicit = settings.alerts.alertsEnabled ? event.snapshot.alerts?.[0] : undefined;
  const urgentControl = event.snapshot.controls.find((control) =>
    control.state === "active" && control.urgency !== "safe" &&
    (control.kind === "mez" ? settings.alerts.mezTimersEnabled : settings.alerts.lullTimersEnabled));
  const signal = testAlert ? {
    id: testAlert.id, severity: testAlert.severity, eyebrow: "ALERT PREVIEW",
    title: testAlert.title, detail: testAlert.target, shouldSound: settings.alerts.alertSound,
  } : explicit ? {
    id: explicit.id,
    severity: explicit.severity || "danger" as const,
    eyebrow: explicit.severity === "info" ? "INFORMATION" : "DANGER SIGNAL",
    title: explicit.title,
    detail: explicit.target,
    shouldSound: settings.alerts.alertSound,
  } : urgentControl ? {
    id: `${urgentControl.kind}-${urgentControl.landedAt}-${urgentControl.urgency}`,
    severity: urgentControl.urgency === "critical" ? "danger" as const : "warn" as const,
    eyebrow: `${urgentControl.kind.toUpperCase()} ${phaseLabel(urgentControl)}`,
    title: urgentControl.target,
    detail: `${Math.ceil(urgentControl.safeRemainingSeconds)}s safe · ${spellLabel(urgentControl)}`,
    shouldSound: urgentControl.kind === "mez" ? settings.alerts.mezTimerSound : settings.alerts.lullTimerSound,
  } : null;

  useEffect(() => {
    if (!signal || !signal.shouldSound || sounded.current.has(signal.id)) return;
    sounded.current.add(signal.id);
    playSignal(signal.severity);
  }, [signal]);

  if (!signal) return <div className="alert-surface empty" />;
  return <div className={`alert-surface ${signal.severity}`} role="alert">
    <span className="alert-glyph">!</span><div><small>{signal.eyebrow}</small><strong>{signal.title}</strong><p>{signal.detail}</p></div>
    <i className="alert-sweep" />
  </div>;
}

function MainApp() {
  const [event, setEvent] = useState<EngineSnapshotEvent>(emptyEvent);
  const [health, setHealth] = useState<EngineHealth>(initialHealth);
  const [expanded, setExpanded] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [raidDifficulty, setRaidDifficulty] = useState<number | null>(null);
  const [settings, setSettings] = useState<DesktopSettings>(defaultDesktopSettings);
  const [runtime, setRuntime] = useState({ coldStartMs: 0, residentMemoryMb: 0 });
  const [gearPlan, setGearPlan] = useState<GearPlanView>(emptyGearPlan);

  useEffect(() => {
    const desktop = window.loremasterDesktop;
    if (!desktop) {
      setHealth({ ...initialHealth, state: "error", detail: "Electron bridge is unavailable" });
      return undefined;
    }
    void desktop.getRuntimeMetrics().then(setRuntime);
    void desktop.getEngineState().then((state) => {
      if (isEngineHealth(state.health)) setHealth(state.health);
      if (isEngineSnapshotEvent(state.snapshot)) setEvent(state.snapshot);
      setRaidDifficulty(state.settings.raidDifficulty);
      setSettings(state.settings);
      if (isGearPlanView(state.gearPlan)) setGearPlan(state.gearPlan);
    });
    const removeSnapshot = desktop.onSnapshot((value) => {
      if (isEngineSnapshotEvent(value)) setEvent(value);
    });
    const removeHealth = desktop.onHealth((value) => {
      if (isEngineHealth(value)) setHealth(value);
    });
    const removeGearPlan = desktop.onGearPlan((value) => {
      if (isGearPlanView(value)) setGearPlan(value);
    });
    const removeSettings = desktop.onSettings((value) => {
      if (value && typeof value === "object") setSettings(value as DesktopSettings);
    });
    return () => { removeSnapshot(); removeHealth(); removeGearPlan(); removeSettings(); };
  }, []);

  const setMode = (next: boolean) => {
    setExpanded(next);
    if (!next) setSettingsOpen(false);
    window.loremasterDesktop?.setExpanded(next);
  };

  const changeRaidDifficulty = (value: number | null) => {
    setRaidDifficulty(value);
    void window.loremasterDesktop?.setRaidDifficulty(value);
  };

  const updateAlertSetting = async (alerts: Partial<DesktopSettings["alerts"]>) => {
    const saved = await window.loremasterDesktop?.updateSettings({ alerts });
    if (saved) setSettings(saved);
  };

  const damageShare = useMemo(() => {
    const total = event.snapshot.combat.personalDamage + event.snapshot.combat.charmedPetDamage;
    return total > 0 ? Math.round(event.snapshot.combat.charmedPetDamage / total * 100) : 0;
  }, [event.snapshot.combat.personalDamage, event.snapshot.combat.charmedPetDamage]);

  if (!expanded) return <RuneSeed event={event} health={health} onExpand={() => setMode(true)} />;

  const { snapshot } = event;
  const weekly = snapshot.weekly;
  return (
    <main className="loremaster-shell">
      <header className="masthead">
        <CogMark />
        <div><p>LOREMASTER</p><small><b className={health.state} /> {health.state.toUpperCase()} · PROTOCOL {event.protocolVersion}</small></div>
        <div className="masthead-actions">
          <button type="button" onClick={() => setSettingsOpen((value) => !value)} aria-label="Open settings">SET</button>
          <button type="button" onClick={() => setMode(false)} aria-label="Collapse to Rune Seed">SEED</button>
          <button type="button" onClick={() => window.loremasterDesktop?.minimizeWindow()} aria-label="Minimize Loremaster">—</button>
          <button type="button" onClick={() => window.loremasterDesktop?.closeWindow()} aria-label="Close Loremaster">×</button>
        </div>
      </header>

      {settingsOpen ? <SettingsPanel health={health} raidDifficulty={raidDifficulty} settings={settings}
        onSettings={setSettings}
        onRaidDifficulty={changeRaidDifficulty} onClose={() => setSettingsOpen(false)} /> : <>
        <section className="context-line">
          <span>{snapshot.character.name !== "?" ? snapshot.character.name : "NO LOG YET"}{snapshot.character.level > 0 ? ` · ${snapshot.character.level}` : ""}{snapshot.character.composition ? ` · ${snapshot.character.composition}` : ""}</span>
          <span>{snapshot.character.zone || health.state}</span>
        </section>

        {health.state !== "live" && <section className={`health-banner ${health.state}`}><i /><div><b>{health.state.toUpperCase()}</b><span>{health.detail}</span></div><button onClick={() => setSettingsOpen(true)}>LOG SETTINGS</button></section>}

        {snapshot.alerts?.map((alert) => <section className={`danger-toast ${alert.severity}`} key={alert.id} role="alert"><span>!</span><div><small>{alert.severity === "info" ? "INFORMATION" : alert.severity === "warn" ? "WARNING" : "DANGER SIGNAL"}</small><strong>{alert.title}{alert.target ? ` · ${alert.target}` : ""}</strong></div></section>)}

        <section className="hero-card">
          <p>{snapshot.combat.encounterName || "Waiting for combat"}</p>
          <div className="hero-metric">
            <strong>{formatDps(snapshot.combat.fightDps)}</strong><span>DPS</span>
            <aside><b>{formatDps(snapshot.combat.sessionDps)}</b><small>SESSION · {formatDuration(snapshot.combat.fightSeconds)} FIGHT</small></aside>
          </div>
          <span className="hero-rule"><i style={{ width: `${Math.min(100, snapshot.combat.fightDps / 5)}%` }} /></span>
          {settings.splitCharmedPetDps && <div className="dps-split" aria-label="Self and pet fight DPS">
            <span><small>SELF</small><b>{formatDps(snapshot.combat.fightSeconds > 0 ? snapshot.combat.fightPersonalDamage / snapshot.combat.fightSeconds : 0)}</b></span>
            <span><small>CHARMED</small><b>{formatDps(snapshot.combat.fightSeconds > 0 ? snapshot.combat.fightCharmedPetDamage / snapshot.combat.fightSeconds : 0)}</b></span>
            {snapshot.combat.fightSummonedPetDamage > 0 && <span><small>SUMMONED</small><b>{formatDps(snapshot.combat.fightSummonedPetDamage / Math.max(1, snapshot.combat.fightSeconds))}</b></span>}
          </div>}
        </section>

        <section className="control-deck" aria-live="polite">
          <header><div><small>PRIORITY</small><h2>MEZ + LULL CONTROL</h2></div><span>{snapshot.controls.filter((row) => row.state === "active").length} TRACKED</span></header>
          <div className="control-list">
            {snapshot.controls.length > 0
              ? snapshot.controls.map((control, rowIndex) => <ControlRow key={`${control.kind}-${control.target}-${rowIndex}`} control={control} />)
              : <p className="quiet-state">No active crowd control · evidence channel clear</p>}
          </div>
          {(snapshot.hiddenControlRows > 0 || snapshot.controlAmbiguityCount > 0) && <footer>
            {snapshot.hiddenControlRows > 0 && <span>+{snapshot.hiddenControlRows} overflow</span>}
            {snapshot.controlAmbiguityCount > 0 && <span>? {snapshot.controlAmbiguityCount} ambiguous result</span>}
          </footer>}
        </section>

        <section className="stat-grid">
          <article><small>PERSONAL</small><strong>{snapshot.combat.personalDamage.toLocaleString()}</strong></article>
          <article><small>CHARMED PET</small><strong>{snapshot.combat.charmedPetDamage.toLocaleString()}</strong></article>
          <article><small>PET SHARE</small><strong>{damageShare}%</strong></article>
        </section>

        <details className="breakdown-card">
          <summary><div><small>ENCOUNTER DETAIL</small><h2>FIGHT BREAKDOWN</h2></div><span>{snapshot.breakdown.sources.length} SOURCES</span></summary>
          <div className="fight-facts">
            <span><small>DAMAGE</small><b>{snapshot.combat.fightDamage.toLocaleString()}</b></span>
            <span><small>TAKEN</small><b>{snapshot.combat.damageTaken.toLocaleString()}</b></span>
            <span><small>HEALING</small><b>{snapshot.combat.healingDone.toLocaleString()}</b></span>
            <span><small>CRIT / MISS</small><b>{snapshot.combat.crits} / {snapshot.combat.misses}</b></span>
          </div>
          <div className="breakdown-columns">
            <section><small>DAMAGE BY ABILITY</small>{snapshot.breakdown.sources.slice(0, 6).map((source) => <article key={source.name}>
              <span><b>{source.name}</b><small>{source.hits} hits · max {source.maximum.toLocaleString()}</small></span><strong>{source.total.toLocaleString()}</strong>
            </article>)}</section>
            <section><small>TARGETS</small>{snapshot.breakdown.targets.slice(0, 6).map((target) => <article key={target.name}>
              <span><b>{target.name}</b></span><strong>{target.total.toLocaleString()}</strong>
            </article>)}</section>
          </div>
          {snapshot.character.composition && <p className="stance-note">ACTIVE COMPOSITION · {snapshot.character.composition}. EQ logs do not expose your active stance, so Loremaster reports evidence rather than guessing a recommendation.</p>}
        </details>

        {weekly && <details className="weekly-card">
          <summary>
            <div><small>RAID RESET · D0–D4</small><h2>{weekly.completedCount} / {weekly.trackedLockoutCount} LOCKOUTS</h2></div>
            <span className={weekly.activeDifficulty == null ? "tier-needed" : ""}>
              {weekly.activeDifficulty == null ? "SET TIER" : `D${weekly.activeDifficulty}`}
            </span>
          </summary>
          {weekly.pendingRaidTarget && <p className="raid-pending"><b>{weekly.pendingRaidTarget}</b> was detected. Pick its tier in Settings to record it.</p>}
          <div className="raid-grid" aria-label="Weekly D0 through D4 raid lockouts">
            <div className="raid-grid-head"><span>RAID TARGET</span>{raidDifficulties.map((difficulty) => <b key={difficulty}>D{difficulty}</b>)}</div>
            {weekly.raids.map((raid) => <div className="raid-grid-row" key={raid.target}>
              <span title={`${raid.target} · ${raid.zone}`}><b>{raid.target}</b><small>{weekly.activeDifficulty != null && raid.bestSeconds[weekly.activeDifficulty] != null
                ? `D${weekly.activeDifficulty} best ${formatDuration(raid.bestSeconds[weekly.activeDifficulty] ?? 0)}`
                : raid.zone}</small></span>
              {raidDifficulties.map((difficulty) => {
                const completed = Boolean(raid.difficulties[difficulty]);
                return <button className={completed ? "done" : ""} key={difficulty} type="button"
                  title={raid.bestSeconds[difficulty] != null ? `Personal best ${formatDuration(raid.bestSeconds[difficulty] ?? 0)}` : "No personal best yet"}
                  aria-label={`${raid.target} D${difficulty}: ${completed ? "complete" : "not complete"}${raid.bestSeconds[difficulty] != null ? `, personal best ${formatDuration(raid.bestSeconds[difficulty] ?? 0)}` : ""}`}
                  aria-pressed={completed}
                  onClick={() => void window.loremasterDesktop?.setRaidCompletion(raid.target, difficulty, !completed)}>
                  {completed ? "✓" : "·"}
                </button>;
              })}
            </div>)}
          </div>
          <p className="raid-reset">Resets {weekly.resetLabel}. Click any cell to correct it manually.</p>
        </details>}

        <details className={`gear-card ${gearPlan.status}`}>
          <summary>
            <div><small>GEAR PATH · BIS</small><h2>{gearPlan.status === "ready" ? `${gearPlan.ownedGoalCount} / ${gearPlan.goals.length} GOALS OWNED` : "IMPORT YOUR BUILD"}</h2></div>
            <span>{gearPlan.bagUpgradeCount > 0 ? `${gearPlan.bagUpgradeCount} BAG UPGRADE${gearPlan.bagUpgradeCount === 1 ? "" : "S"}` : `${gearPlan.missingGoalCount} TO FARM`}</span>
          </summary>
          <p>{gearPlan.detail}</p>
          {gearPlan.bagUpgradeCount > 0 && <section className="bag-upgrades">
            <small>READY TO EQUIP</small>
            {gearPlan.goals.filter((goal) => goal.ownership === "bag").map((goal) => <button key={`${goal.slot}-${goal.itemId}`} type="button"
              onClick={() => void window.loremasterDesktop?.openExternal(goal.itemUrl)}>
              <b>{goal.itemName}</b><span>{goal.slot} · {goal.location}</span>
            </button>)}
          </section>}
          {gearPlan.routes.length > 0 && <section className="farm-routes">
            <small>EFFICIENT FARMING ROUTE · MOST GOALS FIRST</small>
            {gearPlan.routes.slice(0, 6).map((route, index) => <article key={route.zone}>
              <b>{index + 1}</b><div><strong>{route.zone}</strong><span>{route.itemNames.join(" · ")}</span>{route.targets.length > 0 && <small>{route.targets.join(", ")}</small>}</div>
            </article>)}
          </section>}
          <footer className="gear-credit"><button type="button" onClick={() => void window.loremasterDesktop?.openExternal(eqToolsCharSheetUrl)}>OPEN CHARACTER SHEET ↗</button><span>Data credit: EQ Legends Tools · FlammHammer</span></footer>
        </details>

        <section className={`alerts-rail ${settings.alerts.alertsEnabled ? "armed" : "muted"}`}>
          <span><i /> {settings.alerts.alertsEnabled ? "ALERTS ARMED" : "ALERTS MUTED"}</span>
          <button className={settings.alerts.alertCharmBreak ? "active" : ""} type="button"
            onClick={() => void updateAlertSetting({ alertCharmBreak: !settings.alerts.alertCharmBreak })}>CHARM</button>
          <button className={settings.alerts.mezTimersEnabled ? "active" : ""} type="button"
            onClick={() => void updateAlertSetting({ mezTimersEnabled: !settings.alerts.mezTimersEnabled })}>MEZ</button>
          <button className={settings.alerts.lullTimersEnabled ? "active" : ""} type="button"
            onClick={() => void updateAlertSetting({ lullTimersEnabled: !settings.alerts.lullTimersEnabled })}>LULL</button>
        </section>
        <footer className="health-line"><span>{health.activeLogPath ? `LIVE · ${health.character}` : "LOCAL ENGINE · NO NETWORK"}</span><span>{runtime.residentMemoryMb || "—"}MB · {runtime.coldStartMs || "—"}ms start</span></footer>
      </>}
    </main>
  );
}

export default function App() {
  const params = new URLSearchParams(window.location.search);
  if (params.get("alert") === "1") return <AlertSurface />;
  if (params.get("controls") === "1") return <SeedControlSurface />;
  return <MainApp />;
}
