import { copyFileSync, existsSync, mkdirSync, renameSync, rmSync } from "node:fs";
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
  // Copies land here first and only become the marker directory once every
  // file has been copied, via an atomic rename. If a copy fails partway,
  // `directory` never comes into existence, so a later launch retries
  // instead of trusting an incomplete snapshot.
  const staging = path.join(request.backupRoot, `${version}.partial`);
  try {
    // The directory's presence is the marker, so a later launch cannot
    // overwrite the pre-candidate snapshot with already-damaged state.
    if (existsSync(directory)) {
      return { status: "skipped", reason: "already-backed-up" };
    }
    // A crashed earlier attempt may have left a partial staging directory
    // behind; it must not poison this retry.
    rmSync(staging, { recursive: true, force: true });
    mkdirSync(staging, { recursive: true });

    const files: string[] = [];
    for (const name of RC_BACKUP_FILES) {
      const source = path.join(request.userDataDir, name);
      // A fresh install has none of these, which is not a failure.
      if (!existsSync(source)) {
        continue;
      }
      copyFileSync(source, path.join(staging, name));
      files.push(name);
    }
    renameSync(staging, directory);
    return { status: "created", directory, files };
  } catch (error) {
    return {
      status: "failed",
      error: error instanceof Error ? error.message : String(error),
    };
  }
}
