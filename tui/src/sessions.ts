import { spawn } from "node:child_process";
import { realpathSync } from "node:fs";
import { hostCommand } from "./host-process";
import { UsageError, type Resume } from "./options";
import pkg from "../package.json" with { type: "json" };

export interface SessionInfo {
  room: string;
  title: string;
  workspace: string | null;
  host_name: string | null;
  team?: string | null;
  created_at: string;
  updated_at: string;
  prompts: number;
  people: number;
}

export function listSessions(workspace?: string): Promise<SessionInfo[]> {
  const [command, ...prefix] = hostCommand();
  const args = [...prefix, "sessions", "--json", ...(workspace === undefined ? [] : ["--workspace", workspace])];
  return new Promise((resolve, reject) => {
    const child = spawn(command as string, args, { stdio: ["ignore", "pipe", "pipe"] });
    let out = "";
    let errors = "";
    child.stdout.on("data", (chunk: Buffer) => (out += chunk.toString()));
    child.stderr.on("data", (chunk: Buffer) => (errors += chunk.toString()));
    child.on("error", (error: NodeJS.ErrnoException) =>
      reject(error.code === "ENOENT" ? new UsageError(`"${command}" was not found. Install the host: uv tool install plural-agent`) : error),
    );
    child.on("close", (code) => {
      if (code !== 0) {
        reject(
          new UsageError(
            /No such command/.test(errors)
              ? `the host (plural-host) is older than this plural ${pkg.version} and cannot list sessions. Run plural update, or: uv tool install --force --refresh plural-agent==${pkg.version}`
              : `could not list the sessions (exit ${code}) ${errors.trim()}`,
          ),
        );
        return;
      }
      try {
        resolve(JSON.parse(out) as SessionInfo[]);
      } catch {
        reject(new UsageError("the host answered with something that is not a list of sessions"));
      }
    });
  });
}

function real(path: string): string {
  try {
    return realpathSync(path);
  } catch {
    return path;
  }
}

export function inFolder(sessions: SessionInfo[], folder: string): SessionInfo[] {
  const wanted = real(folder);
  return sessions.filter((entry) => entry.workspace !== null && real(entry.workspace) === wanted);
}

function describe(entry: SessionInfo): string {
  return `  ${entry.room}  ${entry.title}`;
}

export function resolveSession(request: Exclude<Resume, { kind: "pick" }>, sessions: SessionInfo[], folder: string): SessionInfo {
  if (request.kind === "continue") {
    const latest = inFolder(sessions, folder)[0];
    if (latest === undefined) {
      throw new UsageError("there is no session in this folder to continue. plural -r lists the sessions you can resume");
    }
    return latest;
  }
  const wanted = request.value.trim();
  const lower = wanted.toLowerCase();
  const exact = sessions.find((entry) => entry.room === wanted);
  if (exact !== undefined) {
    return exact;
  }
  const attempts: ((entry: SessionInfo) => boolean)[] = [
    (entry) => entry.room.toLowerCase().startsWith(lower) || entry.room.toLowerCase().startsWith(`r_${lower}`),
    (entry) => entry.title.toLowerCase() === lower,
    (entry) => entry.title.toLowerCase().includes(lower),
  ];
  for (const matches of attempts) {
    const found = sessions.filter(matches);
    if (found.length === 1) {
      return found[0] as SessionInfo;
    }
    if (found.length > 1) {
      throw new UsageError(`“${wanted}” matches ${found.length} sessions, name one of them:\n${found.slice(0, 6).map(describe).join("\n")}`);
    }
  }
  throw new UsageError(`there is no session “${wanted}”. plural -r lists the sessions you can resume`);
}

export function ago(iso: string, now: Date = new Date()): string {
  const seconds = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86_400)}d ago`;
}
