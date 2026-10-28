import { spawn, type ChildProcess } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

export interface RunningHost {
  guestLink: string;
  hostLink: string;
  stop: () => Promise<void>;
}

const ROOT = resolve(import.meta.dirname, "../../..");

function freePort(): Promise<number> {
  return new Promise((resolvePort, reject) => {
    const probe = createServer();
    probe.listen(0, "127.0.0.1", () => {
      const address = probe.address();
      probe.close(() => (typeof address === "object" && address ? resolvePort(address.port) : reject(new Error("no port"))));
    });
  });
}

export interface RunningRelay {
  port: number;
  url: string;
  stop: () => Promise<void>;
}

export async function startRelay(port?: number): Promise<RunningRelay> {
  const chosen = port ?? (await freePort());
  const child: ChildProcess = spawn("uv", ["run", "plural-host", "relay", "--port", String(chosen)], {
    cwd: ROOT,
    env: { ...process.env, PORT: "", PLURAL_RELAY_BIND: "" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let output = "";
  child.stdout?.on("data", (chunk: Buffer) => (output += chunk.toString()));
  child.stderr?.on("data", (chunk: Buffer) => (output += chunk.toString()));
  const deadline = Date.now() + 30_000;
  for (;;) {
    try {
      const response = await fetch(`http://127.0.0.1:${chosen}/healthz`);
      if (response.ok) {
        break;
      }
    } catch {
      if (Date.now() > deadline) {
        throw new Error(`relay did not start: ${output}`);
      }
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 100));
  }
  return {
    port: chosen,
    url: `ws://127.0.0.1:${chosen}`,
    stop: () =>
      new Promise<void>((done) => {
        if (child.exitCode !== null) {
          done();
          return;
        }
        child.once("exit", () => done());
        child.kill("SIGTERM");
      }),
  };
}

export async function startHost(
  mode: "open" | "review" = "open",
  relayUrl?: string,
): Promise<RunningHost> {
  const directory = mkdtempSync(join(tmpdir(), "plural-ts-"));
  const workspace = join(directory, "ws");
  mkdirSync(workspace);
  writeFileSync(join(workspace, "notes.txt"), "alpha\nbeta\n");
  const port = await freePort();
  const child: ChildProcess = spawn(
    "uv",
    [
      "run",
      "plural-host",
      "host",
      "--json",
      "--workspace",
      workspace,
      "--port",
      String(port),
      "--prompts",
      mode,
      ...(relayUrl ? ["--relay", relayUrl] : []),
    ],
    {
      cwd: ROOT,
      env: { ...process.env, PLURAL_DATA_DIR: join(directory, "data"), PLURAL_PROVIDER: "fake" },
      stdio: ["pipe", "pipe", "pipe"],
    },
  );
  let output = "";
  const ready = await new Promise<{ guest_link: string; host_link: string }>((resolveReady, reject) => {
    const timer = setTimeout(() => reject(new Error(`host did not start: ${output}`)), 30_000);
    child.stdout?.on("data", (chunk: Buffer) => {
      output += chunk.toString();
      const line = output.split("\n").find((candidate) => candidate.startsWith("{"));
      if (line) {
        clearTimeout(timer);
        resolveReady(JSON.parse(line));
      }
    });
    child.stderr?.on("data", (chunk: Buffer) => {
      output += chunk.toString();
    });
    child.on("exit", (code) => reject(new Error(`host exited with ${code}: ${output}`)));
  });
  return {
    guestLink: ready.guest_link,
    hostLink: ready.host_link,
    stop: () =>
      new Promise<void>((done) => {
        child.removeAllListeners("exit");
        child.once("exit", () => done());
        child.kill("SIGTERM");
      }),
  };
}
