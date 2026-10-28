import { spawn, type ChildProcess, type SpawnOptions } from "node:child_process";

export type TunnelKind = "cloudflared" | "ngrok";

export const TUNNEL_KINDS: readonly TunnelKind[] = ["cloudflared", "ngrok"];

export function isTunnelKind(value: unknown): value is TunnelKind {
  return typeof value === "string" && (TUNNEL_KINDS as readonly string[]).includes(value);
}

export class TunnelUnavailable extends Error {}

export interface Tunnel {
  url: string;
  stop: () => Promise<void>;
}

export type Spawner = (command: string, args: string[], options: SpawnOptions) => ChildProcess;

const INSTALL: Record<TunnelKind, string> = {
  cloudflared: "install it from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/ (macOS: brew install cloudflared)",
  ngrok: "install it from https://ngrok.com/download and run ngrok config add-authtoken <token> once (macOS: brew install ngrok)",
};

export function tunnelArgs(kind: TunnelKind, port: number): string[] {
  const origin = `127.0.0.1:${port}`;
  return kind === "cloudflared"
    ? ["tunnel", "--no-autoupdate", "--url", `http://${origin}`]
    : ["http", origin, "--log", "stdout", "--log-format", "json"];
}

export function toWebSocket(address: string): string {
  const url = new URL(address);
  return `${url.protocol === "http:" ? "ws:" : "wss:"}//${url.host}`;
}

export function findAddress(kind: TunnelKind, line: string): string | null {
  if (kind === "cloudflared") {
    return /https:\/\/[a-z0-9-]+\.trycloudflare\.com/.exec(line)?.[0] ?? null;
  }
  try {
    const entry = JSON.parse(line) as Record<string, unknown>;
    return entry["msg"] === "started tunnel" && typeof entry["url"] === "string" ? entry["url"] : null;
  } catch {
    return null;
  }
}

function lastLines(text: string): string {
  return text.trim().split("\n").slice(-6).join("\n");
}

export function startTunnel(
  kind: TunnelKind,
  port: number,
  options: { timeoutMs?: number; spawner?: Spawner } = {},
): Promise<Tunnel> {
  const spawner = options.spawner ?? spawn;
  const timeoutMs = options.timeoutMs ?? 30_000;
  const child = spawner(kind, tunnelArgs(kind, port), { stdio: ["ignore", "pipe", "pipe"] });
  const reap = (): void => {
    child.kill("SIGTERM");
  };
  process.once("exit", reap);
  const stop = (): Promise<void> =>
    new Promise((resolve) => {
      process.removeListener("exit", reap);
      if (child.exitCode !== null || child.signalCode !== null) {
        resolve();
        return;
      }
      const force = setTimeout(() => child.kill("SIGKILL"), 3000);
      child.once("exit", () => {
        clearTimeout(force);
        resolve();
      });
      child.kill("SIGTERM");
    });
  return new Promise((resolve, reject) => {
    let seen = "";
    let pending = "";
    let settled = false;
    const finish = (action: () => void): void => {
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        action();
      }
    };
    const fail = (message: string): void =>
      finish(() => {
        void stop();
        reject(new TunnelUnavailable(message));
      });
    const timer = setTimeout(() => fail(`${kind} did not give an address in time\n${lastLines(seen)}`), timeoutMs);
    const read = (chunk: Buffer): void => {
      const text = chunk.toString();
      seen = (seen + text).slice(-4000);
      pending += text;
      const lines = pending.split("\n");
      pending = lines.pop() ?? "";
      for (const line of lines) {
        const address = findAddress(kind, line);
        if (address !== null) {
          finish(() => resolve({ url: toWebSocket(address), stop }));
          return;
        }
      }
    };
    child.stdout?.on("data", read);
    child.stderr?.on("data", read);
    child.on("error", (error: NodeJS.ErrnoException) =>
      fail(error.code === "ENOENT" ? `${kind} was not found: ${INSTALL[kind]}` : String(error)),
    );
    child.on("exit", (code) => fail(`${kind} exited with code ${code} before it gave an address\n${lastLines(seen)}`));
  });
}
