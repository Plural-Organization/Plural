import { describe, expect, test } from "bun:test";
import { EventEmitter } from "node:events";
import type { ChildProcess } from "node:child_process";
import { findAddress, isTunnelKind, startTunnel, toWebSocket, tunnelArgs, TunnelUnavailable, type Spawner } from "../src/tunnel";

class FakeChild extends EventEmitter {
  stdout = new EventEmitter();
  stderr = new EventEmitter();
  exitCode: number | null = null;
  signalCode: string | null = null;
  signals: string[] = [];

  kill(signal: string): boolean {
    this.signals.push(signal);
    this.exitCode = 0;
    queueMicrotask(() => this.emit("exit", 0));
    return true;
  }

  say(stream: "stdout" | "stderr", text: string): void {
    this[stream].emit("data", Buffer.from(text));
  }
}

function spawning(child: FakeChild): { spawner: Spawner; calls: [string, string[]][] } {
  const calls: [string, string[]][] = [];
  return {
    calls,
    spawner: (command, args) => {
      calls.push([command, args]);
      return child as unknown as ChildProcess;
    },
  };
}

const CLOUDFLARED_BANNER = [
  "2026-10-28T10:00:00Z INF Requesting new quick Tunnel on trycloudflare.com...",
  "2026-10-28T10:00:02Z INF +--------------------------------------------------------------------------------------------+",
  "2026-10-28T10:00:02Z INF |  Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):  |",
  "2026-10-28T10:00:02Z INF |  https://calm-river-pencil-demo.trycloudflare.com                                          |",
  "2026-10-28T10:00:02Z INF +--------------------------------------------------------------------------------------------+",
  "",
].join("\n");

const NGROK_STARTED =
  '{"addr":"http://127.0.0.1:7001","lvl":"info","msg":"started tunnel","name":"command_line","obj":"tunnels","t":"2026-10-28T10:00:01Z","url":"https://demo-1234.ngrok-free.app"}\n';

describe("addresses", () => {
  test("cloudflared prints its address inside a banner", () => {
    const found = CLOUDFLARED_BANNER.split("\n").map((line) => findAddress("cloudflared", line));
    expect(found.filter((value) => value !== null)).toEqual(["https://calm-river-pencil-demo.trycloudflare.com"]);
  });

  test("ngrok reports it in the started tunnel record only", () => {
    expect(findAddress("ngrok", NGROK_STARTED.trim())).toBe("https://demo-1234.ngrok-free.app");
    expect(findAddress("ngrok", '{"lvl":"info","msg":"client session established"}')).toBeNull();
    expect(findAddress("ngrok", '{"lvl":"info","msg":"starting web service","url":"http://127.0.0.1:4040"}')).toBeNull();
    expect(findAddress("ngrok", "not json")).toBeNull();
  });

  test("the link uses a secure websocket", () => {
    expect(toWebSocket("https://demo-1234.ngrok-free.app")).toBe("wss://demo-1234.ngrok-free.app");
    expect(toWebSocket("http://localhost:8080")).toBe("ws://localhost:8080");
  });

  test("both tools point at the local port of the host", () => {
    expect(tunnelArgs("cloudflared", 7001)).toEqual(["tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:7001"]);
    expect(tunnelArgs("ngrok", 7001)).toEqual(["http", "127.0.0.1:7001", "--log", "stdout", "--log-format", "json"]);
  });

  test("only known tunnels are accepted", () => {
    expect(isTunnelKind("ngrok")).toBe(true);
    expect(isTunnelKind("localtunnel")).toBe(false);
  });
});

describe("starting a tunnel", () => {
  test("cloudflared: the address comes from the output, split across chunks", async () => {
    const child = new FakeChild();
    const { spawner, calls } = spawning(child);
    const started = startTunnel("cloudflared", 7001, { spawner });
    const half = Math.floor(CLOUDFLARED_BANNER.length * 0.62);
    child.say("stderr", CLOUDFLARED_BANNER.slice(0, half));
    child.say("stderr", CLOUDFLARED_BANNER.slice(half));
    const tunnel = await started;
    expect(tunnel.url).toBe("wss://calm-river-pencil-demo.trycloudflare.com");
    expect(calls[0]?.[0]).toBe("cloudflared");
  });

  test("ngrok: the address comes from the json log", async () => {
    const child = new FakeChild();
    const started = startTunnel("ngrok", 7001, { spawner: spawning(child).spawner });
    child.say("stdout", '{"lvl":"info","msg":"no configuration paths supplied"}\n');
    child.say("stdout", NGROK_STARTED);
    expect((await started).url).toBe("wss://demo-1234.ngrok-free.app");
  });

  test("stopping ends the process once", async () => {
    const child = new FakeChild();
    const started = startTunnel("ngrok", 7001, { spawner: spawning(child).spawner });
    child.say("stdout", NGROK_STARTED);
    const tunnel = await started;
    await tunnel.stop();
    await tunnel.stop();
    expect(child.signals).toEqual(["SIGTERM"]);
  });

  test("a missing program says how to install it", async () => {
    const child = new FakeChild();
    const started = startTunnel("cloudflared", 7001, { spawner: spawning(child).spawner });
    child.emit("error", Object.assign(new Error("spawn cloudflared ENOENT"), { code: "ENOENT" }));
    const error = await started.catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(TunnelUnavailable);
    expect(String(error)).toContain("cloudflared was not found");
    expect(String(error)).toContain("brew install cloudflared");
  });

  test("an exit before the address shows what the tool said", async () => {
    const child = new FakeChild();
    const started = startTunnel("ngrok", 7001, { spawner: spawning(child).spawner });
    child.say("stdout", '{"lvl":"eror","err":"authentication failed: ERR_NGROK_4018"}\n');
    child.emit("exit", 1);
    const error = await started.catch((caught: unknown) => caught);
    expect(String(error)).toContain("exited with code 1");
    expect(String(error)).toContain("ERR_NGROK_4018");
  });

  test("silence ends with a timeout and the process is stopped", async () => {
    const child = new FakeChild();
    const started = startTunnel("cloudflared", 7001, { spawner: spawning(child).spawner, timeoutMs: 30 });
    const error = await started.catch((caught: unknown) => caught);
    expect(String(error)).toContain("did not give an address in time");
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(child.signals).toEqual(["SIGTERM"]);
  });
});
