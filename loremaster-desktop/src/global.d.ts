import type { DesktopSettings, EngineHealth, EngineSnapshotEvent, GearPlanView } from "./protocol";

export {};

declare global {
  interface Window {
    loremasterDesktop?: {
      getRuntimeMetrics: () => Promise<{
        coldStartMs: number;
        residentMemoryMb: number;
        platform: string;
      }>;
      getEngineState: () => Promise<{
        health: EngineHealth;
        snapshot: EngineSnapshotEvent | null;
        settings: DesktopSettings;
        gearPlan: GearPlanView;
      }>;
      chooseLogFolder: () => Promise<string | null>;
      setLogPath: (value: string) => Promise<boolean>;
      setRaidDifficulty: (value: number | null) => Promise<boolean>;
      setRaidCompletion: (target: string, difficulty: number, completed: boolean) => Promise<boolean>;
      updateSettings: (value: Partial<Omit<DesktopSettings, "alerts">> & { alerts?: Partial<DesktopSettings["alerts"]> }) => Promise<DesktopSettings | null>;
      chooseBisBuild: () => Promise<string | null>;
      chooseInventory: () => Promise<string | null>;
      refreshGearData: () => Promise<boolean>;
      openExternal: (value: string) => Promise<boolean>;
      checkForUpdates: () => Promise<{
        ok: boolean;
        currentVersion: string;
        latestVersion: string;
        updateAvailable: boolean;
        releaseUrl: string;
        detail: string;
      }>;
      resetEngine: () => void;
      testAlert: () => void;
      onSnapshot: (callback: (event: unknown) => void) => () => void;
      onHealth: (callback: (health: unknown) => void) => () => void;
      onGearPlan: (callback: (gearPlan: unknown) => void) => () => void;
      onSettings: (callback: (settings: unknown) => void) => () => void;
      onTestAlert: (callback: (alert: unknown) => void) => () => void;
      setExpanded: (expanded: boolean) => void;
      setAnalysis: (active: boolean) => void;
      minimizeWindow: () => void;
      closeWindow: () => void;
    };
  }
}
