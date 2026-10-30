import type { ChildProcess, StdioOptions } from "node:child_process";
import { mkdirSync } from "node:fs";
import { connect } from "node:net";
import { homedir } from "node:os";
import { join } from "node:path";
import { freePort, HostUnavailable, runHostCommand } from "./host-process";
import { UsageError } from "./options";
import { parseTunnelKind, startTunnel, type Tunnel, type TunnelKind } from "./tunnel";

export interface TeamHostRequest {
  name: string;
  tunnel: string;
  member: string | null;
}

export interface TeamHostDeps {
  freePort: () => Promise<number>;
  run: (args: string[], stdio?: StdioOptions) => ChildProcess;
  startTunnel: (kind: TunnelKind, port: number) => Promise<Tunnel>;
  listening: (port: number) => Promise<boolean>;
  teamsFile: () => string;
}

export interface TeamHostIo {
  out: (text: string) => void;
  signal: AbortSignal;
}

const STARTUP_MS = 15_000;
const POLL_MS = 100;

export function relayArgs(port: number, teams: string): string[] {
  return ["relay", "--teams", teams, "--port", String(port), "--proxy-hops", "1"];
}

export function createArgs(request: TeamHostRequest, relay: string): string[] {
  return ["team", "create", request.name, "--relay", relay, ...(request.member === null ? [] : ["--as", request.member])];
}

function dataDirectory(): string {
  return process.env["PLURAL_DATA_DIR"] ?? join(homedir(), ".plural");
}

function accepting(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const socket = connect({ host: "127.0.0.1", port });
    socket.once("connect", () => {
      socket.destroy();
      resolve(true);
    });
    socket.once("error", () => resolve(false));
  });
}

export const DEFAULT_DEPS: TeamHostDeps = {
  freePort,
  run: runHostCommand,
  startTunnel: (kind, port) => startTunnel(kind, port),
  listening: accepting,
  teamsFile: () => {
    mkdirSync(dataDirectory(), { recursive: true, mode: 0o700 });
    return join(dataDirectory(), "teams.db");
  },
};

const pause = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

function exited(child: ChildProcess): boolean {
  return child.exitCode !== null || child.signalCode !== null;
}

async function terminate(child: ChildProcess): Promise<void> {
  if (exited(child)) {
    return;
  }
  await new Promise<void>((resolve) => {
    const force = setTimeout(() => child.kill("SIGKILL"), 3000);
    child.once("exit", () => {
      clearTimeout(force);
      resolve();
    });
    child.kill("SIGTERM");
  });
}

export async function hostTeam(request: TeamHostRequest, io: TeamHostIo, deps: TeamHostDeps = DEFAULT_DEPS): Promise<number> {
  const kind = parseTunnelKind(request.tunnel);
  if (kind === null) {
    throw new UsageError("--tunnel takes cloudflared or ngrok");
  }
  const port = await deps.freePort();
  const relay = deps.run(relayArgs(port, deps.teamsFile()), ["ignore", "ignore", "pipe"]);
  const reap = (): void => {
    relay.kill("SIGTERM");
  };
  process.once("exit", reap);
  let errors = "";
  relay.stderr?.on("data", (chunk: Buffer) => {
    errors = (errors + chunk.toString()).slice(-2000);
  });
  let relayLost: string | null = null;
  let tunnel: Tunnel | null = null;
  try {
    const ended = new Promise<string>((resolve) => {
      relay.on("exit", (code) => {
        relayLost = `the relay exited with code ${code}\n${errors}`.trim();
        resolve(relayLost);
      });
      io.signal.addEventListener("abort", () => resolve(""));
    });
    await untilListening(deps, port, () => relayLost, io.signal);
    if (io.signal.aborted) {
      return 0;
    }
    tunnel = await deps.startTunnel(kind, port);
    if (io.signal.aborted) {
      return 0;
    }
    const live = tunnel;
    const tunnelEnded = new Promise<string>((resolve) => live.onExit(resolve));
    const created = deps.run(createArgs(request, tunnel.url));
    const code = await new Promise<number>((resolve) => created.on("exit", (status) => resolve(status ?? 1)));
    if (code !== 0) {
      return code;
    }
    io.out(
      `\nThe team's relay runs in this window behind ${kind}. Leave it open, ctrl+c stops it.\n` +
        `Start your own session in another terminal: plural --team\n`,
    );
    const reason = await Promise.race([ended, tunnelEnded.then((text) => `the ${kind} tunnel stopped: ${text}`)]);
    if (reason !== "") {
      io.out(`${reason}\n`);
      return 1;
    }
    return 0;
  } finally {
    process.removeListener("exit", reap);
    await tunnel?.stop();
    await terminate(relay);
  }
}

async function untilListening(deps: TeamHostDeps, port: number, gone: () => string | null, signal: AbortSignal): Promise<void> {
  const deadline = Date.now() + STARTUP_MS;
  while (Date.now() < deadline && !signal.aborted) {
    const reason = gone();
    if (reason !== null) {
      throw new HostUnavailable(reason);
    }
    if (await deps.listening(port)) {
      return;
    }
    await pause(POLL_MS);
  }
  if (!signal.aborted) {
    throw new HostUnavailable("the relay did not start in time");
  }
}
