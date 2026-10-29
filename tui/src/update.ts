import { spawn } from "node:child_process";
import { basename, dirname } from "node:path";

export const RELEASES_API = "https://api.github.com/repos/Plural-Organization/Plural/releases/latest";
export const INSTALLER_URL = "https://raw.githubusercontent.com/Plural-Organization/Plural/main/install.sh";

export function parseVersion(text: string): number[] | null {
  const match = /^v?(\d+)\.(\d+)\.(\d+)/.exec(text.trim());
  return match === null ? null : [Number(match[1]), Number(match[2]), Number(match[3])];
}

export function compareVersions(left: string, right: string): number {
  const a = parseVersion(left);
  const b = parseVersion(right);
  if (a === null || b === null) {
    throw new Error(`cannot compare ${left} with ${right}`);
  }
  for (let index = 0; index < 3; index += 1) {
    const difference = (a[index] as number) - (b[index] as number);
    if (difference !== 0) {
      return Math.sign(difference);
    }
  }
  return 0;
}

export function isInstalledBinary(execPath: string): boolean {
  const name = basename(execPath).toLowerCase();
  return name.startsWith("plural") && !name.startsWith("plural-host");
}

export async function latestVersion(fetcher: typeof fetch = fetch): Promise<string> {
  const response = await fetcher(RELEASES_API, { headers: { Accept: "application/vnd.github+json", "User-Agent": "plural-update" }, signal: AbortSignal.timeout(15_000) });
  if (!response.ok) {
    throw new Error(`GitHub answered ${response.status} when asking for the latest release`);
  }
  const payload = (await response.json()) as { tag_name?: unknown };
  if (typeof payload.tag_name !== "string" || parseVersion(payload.tag_name) === null) {
    throw new Error("the latest release has no version number");
  }
  return payload.tag_name.replace(/^v/, "");
}

export function skewNote(client: string, host: string): string | null {
  if (parseVersion(client) === null || parseVersion(host) === null || compareVersions(host, client) >= 0) {
    return null;
  }
  return `the host (plural-host ${host}) is older than this plural ${client}, so some commands will not work. Run plural update, or: uv tool install --force --refresh plural-agent==${client}`;
}

export type Installer = (environment: Record<string, string>) => Promise<number>;

export function runInstaller(url: string = INSTALLER_URL, stdio: "inherit" | "ignore" = "inherit"): Installer {
  return (environment) =>
    new Promise((resolve) => {
      const fetchAndRun = 'script="$(mktemp)" && curl -fsSL "$PLURAL_INSTALLER" -o "$script" && sh "$script"; code=$?; rm -f "$script"; exit $code';
      const child = spawn("sh", ["-c", fetchAndRun], {
        stdio,
        env: { ...process.env, ...environment, PLURAL_INSTALLER: url },
      });
      child.on("error", () => resolve(127));
      child.on("close", (code) => resolve(code ?? 1));
    });
}

export interface UpdateDeps {
  current: string;
  execPath: string;
  fetcher?: typeof fetch;
  install?: Installer;
  out: { write: (text: string) => void };
  err: { write: (text: string) => void };
}

export async function runUpdate(options: { check: boolean }, deps: UpdateDeps): Promise<number> {
  const { current, execPath, out, err } = deps;
  let latest: string;
  try {
    latest = await latestVersion(deps.fetcher);
  } catch (error) {
    err.write(`could not look up the latest version: ${error instanceof Error ? error.message : String(error)}\n`);
    return 1;
  }
  if (compareVersions(latest, current) <= 0) {
    out.write(`plural ${current} is up to date\n`);
    return 0;
  }
  if (options.check) {
    out.write(`plural ${latest} is available, you have ${current}. Run plural update\n`);
    return 0;
  }
  if (!isInstalledBinary(execPath)) {
    err.write(`plural ${latest} is available, but this copy runs from source or from a package manager, so it cannot replace itself. Update it the way you installed it.\n`);
    return 1;
  }
  out.write(`updating plural ${current} → ${latest}\n`);
  const code = await (deps.install ?? runInstaller())({ PLURAL_VERSION: latest, PLURAL_INSTALL_DIR: dirname(execPath) });
  if (code !== 0) {
    err.write(`the update did not finish (exit ${code}). Run plural update again, it continues where it stopped\n`);
    return 1;
  }
  out.write(`plural ${latest} is installed. Start plural again to use it\n`);
  return 0;
}

export type UpdateState =
  | { phase: "ready"; version: string }
  | { phase: "installing"; version: string }
  | { phase: "installed"; version: string }
  | { phase: "failed"; version: string; code: number };

export interface UpdaterDeps {
  current: string;
  execPath: string;
  fetcher?: typeof fetch;
  install?: Installer;
}

export class Updater {
  private current: UpdateState | null = null;
  private readonly listeners = new Set<(state: UpdateState | null) => void>();

  constructor(private readonly deps: UpdaterDeps) {}

  get state(): UpdateState | null {
    return this.current;
  }

  subscribe(listener: (state: UpdateState | null) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private set(state: UpdateState): void {
    this.current = state;
    this.listeners.forEach((listener) => listener(state));
  }

  async check(): Promise<void> {
    if (!isInstalledBinary(this.deps.execPath) || process.env.PLURAL_NO_UPDATE_CHECK) {
      return;
    }
    try {
      const latest = await latestVersion(this.deps.fetcher);
      if (compareVersions(latest, this.deps.current) > 0) {
        this.set({ phase: "ready", version: latest });
      }
    } catch {
      return;
    }
  }

  async install(): Promise<void> {
    const state = this.current;
    if (state === null || (state.phase !== "ready" && state.phase !== "failed")) {
      return;
    }
    this.set({ phase: "installing", version: state.version });
    const code = await (this.deps.install ?? runInstaller(INSTALLER_URL, "ignore"))({
      PLURAL_VERSION: state.version,
      PLURAL_INSTALL_DIR: dirname(this.deps.execPath),
    });
    this.set(code === 0 ? { phase: "installed", version: state.version } : { phase: "failed", version: state.version, code });
  }
}
