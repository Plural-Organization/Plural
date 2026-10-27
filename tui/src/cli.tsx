#!/usr/bin/env bun
import { userInfo } from "node:os";
import { createCliRenderer } from "@opentui/core";
import { createRoot } from "@opentui/react";
import { parseLink, SessionClient } from "@plural/client";
import pkg from "../package.json" with { type: "json" };
import { App } from "./App";
import { loadKeys, saveKeys } from "./credentials";
import { toConfig } from "./presets";
import { loadSettings, saveSettings } from "./settings";
import { HostUnavailable, runHostCommand, startLocalHost, type HostHandle } from "./host-process";
import { startProgress } from "./lib/progress";

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

const progress = startProgress();

function fail(message: string): never {
  progress.done();
  process.stderr.write(`${message}\n`);
  process.exit(1);
}

async function main(): Promise<void> {
  const [first, ...rest] = process.argv.slice(2);
  if (first === "--version" || first === "-v") {
    process.stdout.write(`${pkg.version}\n`);
    return;
  }
  if (first === "--selftest") {
    const probe = await createCliRenderer({ exitOnCtrlC: false, useMouse: false });
    probe.destroy();
    process.stdout.write("selftest ok\n");
    process.exit(0);
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
    progress.step("starting the host…");
    try {
      host = await startLocalHost(args.includes("--name") ? args : [...args, "--name", name]);
    } catch (error) {
      fail(error instanceof HostUnavailable ? error.message : String(error));
    }
    link = host.hostLink;
    guestLink = host.guestLink;
    room = host.room;
  }

  let parsed;
  try {
    parsed = parseLink(link);
  } catch (error) {
    await host?.stop();
    fail(error instanceof Error ? error.message : String(error));
  }

  const settings = loadSettings();
  const keys = loadKeys();
  const control = host?.control ?? null;
  let startupNote: string | null = null;
  if (control && settings.agent.preset !== "demo") {
    progress.step(`loading the saved model (${settings.agent.preset})…`);
    const applied = await control.configure(toConfig(settings.agent, keys[settings.agent.preset] ?? ""));
    if (!applied.ok) {
      startupNote = `could not use the saved model: ${applied.error ?? "unknown error"}. Open the settings (F2) to fix it.`;
    }
  }
  const client = new SessionClient(parsed, { name, client: { kind: "tui", version: pkg.version } });
  progress.step("opening the session…");
  const renderer = await createCliRenderer({ exitOnCtrlC: false, useMouse: true });
  progress.done();
  const quit = new Promise<void>((resolve) => {
    createRoot(renderer).render(
      <App
        client={client}
        room={room}
        version={pkg.version}
        guestLink={guestLink}
        settings={settings}
        onSettings={saveSettings}
        control={control}
        keys={keys}
        onKeys={(preset, key, remember) => {
          const stored = loadKeys();
          if (remember && key !== "") {
            stored[preset] = key;
          } else {
            delete stored[preset];
          }
          saveKeys(stored);
        }}
        startupNote={startupNote}
        splash
        onQuit={() => {
          resolve();
        }}
      />,
    );
    process.on("SIGTERM", () => resolve());
    process.on("SIGINT", () => resolve());
  });
  await quit;
  renderer.destroy();
  await host?.stop();
  process.exit(0);
}

void main();
