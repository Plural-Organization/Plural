import { describe, expect, test } from "bun:test";
import { EventEmitter } from "node:events";
import type { ChildProcess } from "node:child_process";
import { parseArgs, UsageError } from "../src/options";
import { createArgs, hostTeam, relayArgs, type TeamHostDeps } from "../src/team-host";
import type { Tunnel } from "../src/tunnel";

class FakeProcess extends EventEmitter {
  stderr = new EventEmitter();
  exitCode: number | null = null;
  signalCode: string | null = null;
  signals: string[] = [];

  kill(signal: string): boolean {
    this.signals.push(signal);
    this.finish(0);
    return true;
  }

  finish(code: number): void {
    if (this.exitCode === null) {
      this.exitCode = code;
      queueMicrotask(() => this.emit("exit", code));
    }
  }
}

function harness(options: { createStatus?: number; listening?: boolean } = {}) {
  const started: { args: string[]; child: FakeProcess }[] = [];
  const tunnel = { stopped: false, exit: null as ((reason: string) => void) | null };
  const deps: TeamHostDeps = {
    freePort: async () => 4321,
    teamsFile: () => "/data/teams.db",
    listening: async () => options.listening ?? true,
    run: (args) => {
      const child = new FakeProcess();
      started.push({ args, child });
      if (args[0] === "team") {
        child.finish(options.createStatus ?? 0);
      }
      return child as unknown as ChildProcess;
    },
    startTunnel: async (): Promise<Tunnel> => ({
      url: "wss://calm.example.dev",
      stop: async () => {
        tunnel.stopped = true;
      },
      onExit: (listener) => {
        tunnel.exit = listener;
      },
    }),
  };
  return { deps, started, tunnel };
}

const REQUEST = { name: "kbtu", tunnel: "ngrok", member: null };

describe("plural team create --tunnel", () => {
  test("the arguments become a team host request", () => {
    expect(parseArgs(["team", "create", "kbtu", "--tunnel", "ngrok", "--as", "Vlad"])).toEqual({
      kind: "team_host",
      name: "kbtu",
      tunnel: "ngrok",
      member: "Vlad",
    });
    expect(parseArgs(["team", "create", "kbtu", "--tunnel=cloudflared"])).toMatchObject({ kind: "team_host", tunnel: "cloudflared" });
  });

  test("without a tunnel the host creates the team itself", () => {
    expect(parseArgs(["team", "create", "kbtu", "--relay", "wss://r.example"])).toEqual({
      kind: "passthrough",
      args: ["team", "create", "kbtu", "--relay", "wss://r.example"],
    });
  });

  test("a relay of your own, a missing name and a stray word are refused", () => {
    expect(() => parseArgs(["team", "create", "kbtu", "--tunnel", "ngrok", "--relay", "wss://r.example"])).toThrow(UsageError);
    expect(() => parseArgs(["team", "create", "--tunnel", "ngrok"])).toThrow(UsageError);
    expect(() => parseArgs(["team", "create", "kbtu", "extra", "--tunnel", "ngrok"])).toThrow(UsageError);
    expect(() => parseArgs(["team", "create", "kbtu", "--tunnel", "ngrok", "--nope"])).toThrow(UsageError);
  });

  test("the relay is started behind one proxy and the team is made on the tunnel address", () => {
    expect(relayArgs(4321, "/data/teams.db")).toEqual(["relay", "--teams", "/data/teams.db", "--port", "4321", "--proxy-hops", "1"]);
    expect(createArgs(REQUEST, "wss://calm.example.dev")).toEqual(["team", "create", "kbtu", "--relay", "wss://calm.example.dev"]);
    expect(createArgs({ ...REQUEST, member: "Vlad" }, "wss://x")).toEqual(["team", "create", "kbtu", "--relay", "wss://x", "--as", "Vlad"]);
  });

  test("it runs until ctrl+c, then stops the tunnel and the relay", async () => {
    const { deps, started, tunnel } = harness();
    const stop = new AbortController();
    const out: string[] = [];
    const done = hostTeam(REQUEST, { out: (text) => out.push(text), signal: stop.signal }, deps);
    await Bun.sleep(30);
    expect(started.map((entry) => entry.args[0])).toEqual(["relay", "team"]);
    expect(out.join("")).toContain("plural --team");
    expect(tunnel.stopped).toBe(false);
    stop.abort();
    expect(await done).toBe(0);
    expect(tunnel.stopped).toBe(true);
    expect(started[0]?.child.signals).toEqual(["SIGTERM"]);
  });

  test("a team that cannot be made stops everything and passes the status on", async () => {
    const { deps, tunnel, started } = harness({ createStatus: 1 });
    const code = await hostTeam(REQUEST, { out: () => undefined, signal: new AbortController().signal }, deps);
    expect(code).toBe(1);
    expect(tunnel.stopped).toBe(true);
    expect(started[0]?.child.signals).toEqual(["SIGTERM"]);
  });

  test("a tunnel that drops ends the run", async () => {
    const { deps, tunnel } = harness();
    const out: string[] = [];
    const done = hostTeam(REQUEST, { out: (text) => out.push(text), signal: new AbortController().signal }, deps);
    await Bun.sleep(30);
    tunnel.exit?.("ngrok exited with code 1");
    expect(await done).toBe(1);
    expect(out.join("")).toContain("the ngrok tunnel stopped");
  });

  test("a relay that dies at the start is reported with its own words", async () => {
    const { deps, started } = harness({ listening: false });
    const done = hostTeam(REQUEST, { out: () => undefined, signal: new AbortController().signal }, deps);
    await Bun.sleep(20);
    const relay = started[0]?.child as FakeProcess;
    relay.stderr.emit("data", Buffer.from("address already in use"));
    relay.finish(1);
    await expect(done).rejects.toThrow("address already in use");
  });
});
