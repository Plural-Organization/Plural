#!/usr/bin/env node
import { userInfo } from "node:os";
import { render } from "ink";
import { parseLink, SessionClient } from "@plural/client";
import pkg from "../package.json" with { type: "json" };
import { App } from "./App";
import { HostUnavailable, runHostCommand, startLocalHost, type HostHandle } from "./host-process";

const USAGE = `plural ${pkg.version}

usage
  plural [host options]       start a session here and open it
  plural join <link>          join a session
  plural relay|doctor|export  run the host's own commands

host options
  --workspace <dir>   project directory the agent works in
  --prompts open|review   who may prompt directly
  --name <name>       your display name
  --port <n>  --bind <addr>  --relay <url>  --public-url <url>  --room <id>
`;

function option(args: string[], name: string): string | undefined {
  const index = args.indexOf(name);
  return index === -1 ? undefined : args[index + 1];
}

function fail(message: string): never {
  process.stderr.write(`${message}\n`);
  process.exit(1);
}

async function main(): Promise<void> {
  const [first, ...rest] = process.argv.slice(2);
  if (first === "--version" || first === "-v") {
    process.stdout.write(`${pkg.version}\n`);
    return;
  }
  if (first === "--help" || first === "-h") {
    process.stdout.write(USAGE);
    return;
  }
  if (first === "relay" || first === "doctor" || first === "export") {
    const child = runHostCommand([first, ...rest]);
    child.on("exit", (code) => process.exit(code ?? 0));
    return;
  }

  let host: HostHandle | null = null;
  let link: string;
  let guestLink: string | null = null;
  let room: string;
  let name: string;
  let version = pkg.version;
  if (first === "join") {
    const target = rest[0];
    if (!target) {
      fail("usage: plural join <link>");
    }
    link = target;
    room = parseLink(target).room;
    name = option(rest, "--name") ?? userInfo().username;
  } else {
    const args = first === "host" ? rest : process.argv.slice(2);
    name = option(args, "--name") ?? userInfo().username;
    try {
      host = await startLocalHost(args.includes("--name") ? args : [...args, "--name", name]);
    } catch (error) {
      fail(error instanceof HostUnavailable ? error.message : String(error));
    }
    link = host.hostLink;
    guestLink = host.guestLink;
    room = host.room;
    version = pkg.version;
  }

  let parsed;
  try {
    parsed = parseLink(link);
  } catch (error) {
    await host?.stop();
    fail(error instanceof Error ? error.message : String(error));
  }
  const client = new SessionClient(parsed, { name, client: { kind: "tui", version } });
  const instance = render(<App client={client} room={room} version={version} guestLink={guestLink} />, {
    exitOnCtrlC: false,
  });
  const stop = async (): Promise<void> => {
    instance.unmount();
    await host?.stop();
    process.exit(0);
  };
  process.on("SIGTERM", () => void stop());
  process.on("SIGINT", () => void stop());
  await instance.waitUntilExit();
  await host?.stop();
  process.exit(0);
}

void main();
