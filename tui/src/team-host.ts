import type { ChildProcess, StdioOptions } from "node:child_process";
import { mkdirSync } from "node:fs";
import { connect } from "node:net";
import { join } from "node:path";
import { freePort, HostUnavailable, runHostCommand } from "./host-process";
import { UsageError } from "./options";
import { parseTunnelKind, startTunnel, type Tunnel, type TunnelKind } from "./tunnel";
import { dataDir } from "./paths";

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

const STARTUP_MS = 15_000;
const POLL_MS = 100;

export function relayArgs(port: number, teams: string): string[] {
  return ["relay", "--teams", teams, "--port", String(port), "--proxy-hops", "1"];
}

export function createArgs(request: TeamHostRequest, relay: string): string[] {
  return ["team", "create", request.name, "--relay", relay, "--json", ...(request.member === null ? [] : ["--as", request.member])];
}

export interface TeamHosting {
  team: string;
  relay: string;
  code: string;
  minutes: number;
  joinCommand: string;
  onLost: (listener: (reason: string) => void) => void;
  stop: () => Promise<void>;
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
    mkdirSync(dataDir(), { recursive: true, mode: 0o700 });
    return join(dataDir(), "teams.db");
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

export async function openTeam(
  request: TeamHostRequest,
  step: (text: string) => void = () => undefined,
  deps: TeamHostDeps = DEFAULT_DEPS,
): Promise<TeamHosting> {
  const kind = parseTunnelKind(request.tunnel);
  if (kind === null) {
    throw new UsageError("--tunnel takes cloudflared or ngrok");
  }
  const port = await deps.freePort();
  step("starting the team's relay…");
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
  const listeners: ((reason: string) => void)[] = [];
  let reported: string | null = null;
  const report = (reason: string): void => {
    reported ??= reason;
    for (const listener of listeners) {
      listener(reason);
    }
  };
  relay.on("exit", (code) => {
    relayLost = `the relay exited with code ${code}\n${errors}`.trim();
    report(relayLost);
  });
  let tunnel: Tunnel | null = null;
  const stop = async (): Promise<void> => {
    process.removeListener("exit", reap);
    await tunnel?.stop();
    await terminate(relay);
  };
  try {
    await untilListening(deps, port, () => relayLost);
    step(`opening a ${kind} tunnel…`);
    tunnel = await deps.startTunnel(kind, port);
    tunnel.onExit((reason) => report(`the ${kind} tunnel stopped (${reason.split("\n")[0]})`));
    step("creating the team…");
    const made = await created(deps.run(createArgs(request, tunnel.url), ["ignore", "pipe", "pipe"]));
    return {
      team: made.team,
      relay: tunnel.url,
      code: made.code,
      minutes: made.minutes,
      joinCommand: `plural team join ${made.code} --relay ${tunnel.url}`,
      onLost: (listener) => {
        listeners.push(listener);
        if (reported !== null) {
          listener(reported);
        }
      },
      stop,
    };
  } catch (error) {
    await stop();
    throw error;
  }
}

interface Created {
  team: string;
  code: string;
  minutes: number;
}

function created(child: ChildProcess): Promise<Created> {
  return new Promise((resolve, reject) => {
    let out = "";
    let err = "";
    child.stdout?.on("data", (chunk: Buffer) => {
      out += chunk.toString();
    });
    child.stderr?.on("data", (chunk: Buffer) => {
      err += chunk.toString();
    });
    child.on("error", (error) => reject(new HostUnavailable(String(error))));
    child.on("exit", (status) => {
      if (status !== 0) {
        reject(new HostUnavailable(`could not create the team\n${(out + err).trim()}`));
        return;
      }
      try {
        const printed = JSON.parse(out) as Created;
        resolve({ team: printed.team, code: printed.code, minutes: printed.minutes });
      } catch {
        reject(new HostUnavailable(`could not read the new team\n${(out + err).trim()}`));
      }
    });
  });
}

async function untilListening(deps: TeamHostDeps, port: number, gone: () => string | null): Promise<void> {
  const deadline = Date.now() + STARTUP_MS;
  while (Date.now() < deadline) {
    const reason = gone();
    if (reason !== null) {
      throw new HostUnavailable(reason);
    }
    if (await deps.listening(port)) {
      return;
    }
    await pause(POLL_MS);
  }
  throw new HostUnavailable("the relay did not start in time");
}
