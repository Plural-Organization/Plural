import { spawn, type ChildProcess } from "node:child_process";
import { createServer } from "node:net";

export interface HostHandle {
  room: string;
  guestLink: string;
  hostLink: string;
  version: string;
  stop: () => Promise<void>;
}

export class HostUnavailable extends Error {}

export function hostCommand(): string[] {
  const configured = process.env["PLURAL_HOST_CMD"];
  return configured ? configured.split(/\s+/).filter(Boolean) : ["plural-host"];
}

export function runHostCommand(args: string[]): ChildProcess {
  const [command, ...prefix] = hostCommand();
  return spawn(command as string, [...prefix, ...args], { stdio: "inherit" });
}

function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const probe = createServer();
    probe.once("error", reject);
    probe.listen(0, "127.0.0.1", () => {
      const address = probe.address();
      probe.close(() => (address && typeof address === "object" ? resolve(address.port) : reject(new Error("no free port"))));
    });
  });
}

export async function startLocalHost(args: string[]): Promise<HostHandle> {
  const [command, ...prefix] = hostCommand();
  const withPort = args.includes("--port") ? args : [...args, "--port", String(await freePort())];
  const child = spawn(command as string, [...prefix, "host", "--json", ...withPort], {
    stdio: ["pipe", "pipe", "pipe"],
  });
  let errors = "";
  child.stderr?.on("data", (chunk: Buffer) => {
    errors += chunk.toString();
  });
  const ready = await new Promise<{ room: string; guest_link: string; host_link: string; version: string }>(
    (resolve, reject) => {
      const timer = setTimeout(() => reject(new HostUnavailable(`the host did not start in time\n${errors}`)), 60_000);
      let buffered = "";
      child.stdout?.on("data", (chunk: Buffer) => {
        buffered += chunk.toString();
        const line = buffered.split("\n").find((candidate) => candidate.startsWith("{"));
        if (line) {
          clearTimeout(timer);
          resolve(JSON.parse(line));
        }
      });
      child.on("error", (error: NodeJS.ErrnoException) => {
        clearTimeout(timer);
        reject(
          error.code === "ENOENT"
            ? new HostUnavailable(`"${command}" was not found. Install the host: uv tool install plural-agent`)
            : error,
        );
      });
      child.on("exit", (code) => {
        clearTimeout(timer);
        reject(new HostUnavailable(`the host exited with code ${code}\n${errors.trim()}`));
      });
    },
  );
  child.removeAllListeners("exit");
  return {
    room: ready.room,
    guestLink: ready.guest_link,
    hostLink: ready.host_link,
    version: ready.version,
    stop: () =>
      new Promise<void>((resolve) => {
        if (child.exitCode !== null) {
          resolve();
          return;
        }
        const kill = setTimeout(() => child.kill("SIGKILL"), 3000);
        child.once("exit", () => {
          clearTimeout(kill);
          resolve();
        });
        child.stdin?.end();
        child.kill("SIGTERM");
      }),
  };
}
