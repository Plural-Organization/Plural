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

export async function startHost(mode: "open" | "review" = "open"): Promise<RunningHost> {
  const directory = mkdtempSync(join(tmpdir(), "plural-ts-"));
  const workspace = join(directory, "ws");
  mkdirSync(workspace);
  writeFileSync(join(workspace, "notes.txt"), "alpha\nbeta\n");
  const port = await freePort();
  const child: ChildProcess = spawn(
    "uv",
    ["run", "plural", "host", "--headless", "--workspace", workspace, "--port", String(port), "--prompts", mode],
    {
      cwd: ROOT,
      env: { ...process.env, PLURAL_DATA_DIR: join(directory, "data"), COLUMNS: "500", PLURAL_PROVIDER: "fake" },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  let output = "";
  const links = await new Promise<string[]>((resolveLinks, reject) => {
    const timer = setTimeout(() => reject(new Error(`host did not start: ${output}`)), 30_000);
    const onData = (chunk: Buffer) => {
      output += chunk.toString();
      const found = output.match(/ws:\/\/\S+/g);
      if (found && found.length >= 2) {
        clearTimeout(timer);
        resolveLinks(found);
      }
    };
    child.stdout?.on("data", onData);
    child.stderr?.on("data", onData);
    child.on("exit", (code) => reject(new Error(`host exited with ${code}: ${output}`)));
  });
  const [guestLink, hostLink] = links as [string, string];
  return {
    guestLink,
    hostLink,
    stop: () =>
      new Promise<void>((done) => {
        child.removeAllListeners("exit");
        child.once("exit", () => done());
        child.kill("SIGTERM");
      }),
  };
}
