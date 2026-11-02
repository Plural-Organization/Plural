import type { ChildProcess, StdioOptions } from "node:child_process";
import { promises as dns } from "node:dns";
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
  answering: (url: string) => Promise<boolean>;
  teamsFile: () => string;
}

const STARTUP_MS = 15_000;
const TUNNEL_MS = 60_000;
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

const published = new Set<string>();

export type Lookup = (host: string) => Promise<"found" | "missing" | "unknown">;

// Asks the zone's own name servers, which cache nothing. A quick tunnel's name exists only seconds after
// its address is printed, and any resolver asked before then (the system's, the router's, even 1.1.1.1)
// keeps the "no such name" for a minute, past the wait.
const authoritative: Lookup = async (host) => {
  let servers: string[];
  try {
    const names = await dns.resolveNs(host.slice(host.indexOf(".") + 1));
    servers = (await Promise.all(names.map((name) => dns.resolve4(name).catch(() => [] as string[])))).flat();
  } catch {
    // Not a zone of its own (a custom or reserved domain, or no dot at all): nothing to ask.
    return "unknown";
  }
  if (servers.length === 0) {
    return "unknown";
  }
  const resolver = new dns.Resolver({ timeout: 2000, tries: 1 });
  resolver.setServers(servers);
  try {
    await resolver.resolve4(host);
    return "found";
  } catch (error) {
    const code = (error as { code?: string }).code;
    return code === "ENOTFOUND" || code === "ENODATA" ? "missing" : "unknown";
  }
};

// True once the name exists, so the system resolver is not asked before; where the name servers cannot
// be reached, it is left to the system resolver as before.
export async function resolvable(host: string, lookup: Lookup = authoritative): Promise<boolean> {
  if (published.has(host)) {
    return true;
  }
  const answer = await lookup(host);
  if (answer === "found") {
    published.add(host);
  }
  // An unknown answer is asked again on the next poll, so one slow reply does not end the wait for good.
  return answer !== "missing";
}

async function healthy(url: string): Promise<boolean> {
  const http = url.replace(/^ws/, "http");
  if (!(await resolvable(new URL(http).hostname))) {
    return false;
  }
  try {
    const response = await fetch(`${http}/healthz`, { signal: AbortSignal.timeout(3000) });
    return response.ok;
  } catch {
    return false;
  }
}

export const DEFAULT_DEPS: TeamHostDeps = {
  freePort,
  run: runHostCommand,
  startTunnel: (kind, port) => startTunnel(kind, port),
  listening: accepting,
  answering: healthy,
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
    step("waiting for the tunnel to answer…");
    await untilAnswering(deps, tunnel.url, () => relayLost);
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

async function untilAnswering(deps: TeamHostDeps, url: string, gone: () => string | null): Promise<void> {
  const deadline = Date.now() + TUNNEL_MS;
  while (Date.now() < deadline) {
    const reason = gone();
    if (reason !== null) {
      throw new HostUnavailable(reason);
    }
    if (await deps.answering(url)) {
      return;
    }
    await pause(POLL_MS * 10);
  }
  throw new HostUnavailable("the tunnel did not start answering in time, try again");
}
