#!/usr/bin/env bun
import { userInfo } from "node:os";
import { createCliRenderer } from "@opentui/core";
import { createRoot } from "@opentui/react";
import { parseLink, SessionClient } from "@plural/client";
import pkg from "../package.json" with { type: "json" };
import { basename } from "node:path";
import { Shell } from "./Shell";
import { loadKeys, saveKeys } from "./credentials";
import { toConfig } from "./presets";
import { loadSettings, saveSettings } from "./settings";
import { freePort, HostUnavailable, runHostCommand, startLocalHost, type HostHandle } from "./host-process";
import { startProgress } from "./lib/progress";
import { ADDRESS_FLAGS, lanAddress, shareLaunch } from "./share";
import { planAgent } from "./agent";
import { Alerts } from "./alerts";
import { fixDashes } from "./args";
import { loadJoined, rejoinLink, rememberJoined } from "./joined";
import { emptyOptions, parseArgs, UsageError, type SessionOptions } from "./options";
import { pickSession } from "./picker";
import { composePrompt, readStdin, runPrint } from "./print";
import { startupCommands } from "./startup";
import { runUpdate, skewNote, Updater } from "./update";
import { fetchSessions, loadTeam, pickTeamSession, TeamWatcher, teamProof, type Team } from "./team";
import { listSessions, resolveSession, type SessionInfo } from "./sessions";
import { parseTunnelKind, startTunnel, TunnelUnavailable, type Tunnel } from "./tunnel";

const USAGE = `plural ${pkg.version}

usage
  plural [prompt]             start a session here and open it
  plural -r [id|title]        resume a session, pick one when none is named
  plural -c                   continue the latest session of this folder
  plural join <link>          join a session
  plural join @name           watch a teammate's session (plural ls lists them)
  plural update [--check]     install the latest version
  plural sessions [--json]    list your sessions
  plural rm <id>              delete a session
  plural relay|doctor|export  run the host's own commands

options
  -r, --resume [id|title]     resume a session
  -c, --continue              continue the latest session of this folder
  -n, --title <title>         name the session
  --workspace <dir>           project directory the agent works in
  --prompts open|review       who may prompt directly
  --name <name>               your display name
  --port <n>  --bind <addr>  --relay <url>  --public-url <url>
  --tunnel cloudflared|ngrok  share through a tunnel, the link carries its address
  -v, --version  -h, --help
`;

const progress = startProgress();

function fail(message: string): never {
  progress.done();
  process.stderr.write(`${message}\n`);
  process.exit(1);
}

function problem(error: unknown): string {
  return error instanceof UsageError || error instanceof HostUnavailable || error instanceof TunnelUnavailable ? error.message : String(error);
}

interface Target {
  link: string;
  room: string;
  guestLink: string | null;
  host: HostHandle | null;
  tunnel: Tunnel | null;
  note: string | null;
  joined: boolean;
  visiting: Team | null;
}

function rejoin(link: string): Target {
  return { link, room: parseLink(link).room, guestLink: null, host: null, tunnel: null, note: null, joined: true, visiting: null };
}

async function visit(spec: string): Promise<Target> {
  const team = loadTeam();
  if (team === null) {
    throw new UsageError("you are not in a team: plural team create or plural team join");
  }
  let card;
  try {
    card = pickTeamSession(await fetchSessions(team), team.profile.member.id, spec);
  } catch (error) {
    throw new UsageError(error instanceof Error ? error.message : String(error));
  }
  const endpoint = card.endpoints[0];
  if (endpoint === undefined) {
    throw new UsageError(`${card.owner}'s session has no address to join`);
  }
  return {
    link: endpoint.url,
    room: card.room,
    guestLink: null,
    host: null,
    tunnel: null,
    note: `watching ${card.owner} · ${card.repo}${card.branch ? ` · ${card.branch}` : ""}. You can read; ask them if you want to write`,
    joined: false,
    visiting: team,
  };
}

async function resume(options: SessionOptions): Promise<{ hostArgs: string[]; join: string | null }> {
  const request = options.resume;
  if (request === null) {
    return { hostArgs: options.hostArgs, join: null };
  }
  const given = options.hostArgs.indexOf("--workspace");
  const folder = given === -1 ? process.cwd() : (options.hostArgs[given + 1] as string);
  const sessions = await listSessions();
  const joined = loadJoined();
  let info: SessionInfo;
  if (request.kind === "pick") {
    if (!process.stdin.isTTY || !process.stdout.isTTY) {
      fail(sessions.length === 0 ? "no sessions yet" : sessions.map((entry) => `${entry.room}  ${entry.title}`).join("\n"));
    }
    const chosen = await pickSession(sessions, joined, folder);
    if (chosen === null) {
      process.exit(0);
    }
    if (chosen.kind === "joined") {
      return { hostArgs: options.hostArgs, join: rejoinLink(chosen.room) };
    }
    info = chosen.info;
  } else {
    try {
      info = resolveSession(request, sessions, folder);
    } catch (error) {
      const wanted = request.kind === "id" ? request.value.toLowerCase() : "";
      const room = wanted === "" ? undefined : joined.find((entry) => entry.room.toLowerCase().startsWith(wanted));
      if (room === undefined) {
        throw error;
      }
      return { hostArgs: options.hostArgs, join: rejoinLink(room) };
    }
  }
  const hostArgs = [...options.hostArgs, "--room", info.room];
  if (info.workspace !== null && !hostArgs.includes("--workspace")) {
    hostArgs.push("--workspace", info.workspace);
  }
  return { hostArgs, join: null };
}

async function start(options: SessionOptions, joinLink: string | null, name: string): Promise<Target> {
  if (joinLink !== null) {
    return joinLink.startsWith("@") ? await visit(joinLink) : rejoin(joinLink);
  }
  const kind = options.tunnel === null ? null : parseTunnelKind(options.tunnel);
  if (options.tunnel !== null && kind === null) {
    throw new UsageError("--tunnel takes cloudflared or ngrok");
  }
  const found = await resume(options);
  if (found.join !== null) {
    return rejoin(found.join);
  }
  const plain = found.hostArgs;
  if (kind !== null && ["--relay", "--public-url", "--bind"].some((flag) => plain.includes(flag))) {
    throw new UsageError("--tunnel cannot be combined with --relay, --public-url or --bind");
  }
  const named = [...plain, "--name", name];
  const portFlag = plain.indexOf("--port");
  const port = (portFlag === -1 ? 0 : Number(plain[portFlag + 1])) || (await freePort());
  const sharing = plain.includes("--team") ? loadTeam() : null;
  if (plain.includes("--team") && sharing === null) {
    throw new UsageError("you are not in a team: plural team create or plural team join");
  }
  let launch = shareLaunch(loadSettings(), named, port, lanAddress());
  if (sharing !== null && kind === null && !plain.some((flag) => ADDRESS_FLAGS.includes(flag))) {
    launch = { args: [...named, "--relay", sharing.profile.relay], note: `showing this session to ${sharing.profile.team_name}` };
  }
  let tunnel: Tunnel | null = null;
  if (kind !== null) {
    progress.step(`opening a ${kind} tunnel…`);
    tunnel = await startTunnel(kind, port);
    launch = {
      args: [...named, "--port", String(port), "--public-url", tunnel.url],
      note: `sharing through ${kind}: the invite links work while plural is running`,
    };
  }
  progress.step("starting the host…");
  try {
    const host = await startLocalHost(launch.args);
    return { link: host.hostLink, room: host.room, guestLink: host.guestLink, host, tunnel, note: launch.note, joined: false, visiting: null };
  } catch (error) {
    await tunnel?.stop();
    throw error;
  }
}

async function printOnce(options: SessionOptions, name: string): Promise<void> {
  if (options.tunnel !== null) {
    fail("--tunnel shares a session with people, -p runs alone. Drop one of them");
  }
  const prompt = composePrompt(options.prompt, await readStdin());
  if (prompt === "") {
    fail("-p needs a prompt: plural -p \"your question\", or pipe text into it");
  }
  let plan;
  let commands;
  try {
    plan = planAgent(loadSettings(), loadKeys(), options);
    commands = startupCommands(options);
  } catch (error) {
    fail(problem(error));
  }
  if (plan.problem !== null) {
    fail(`${plan.problem}. Run plural once to set a model up, or pass --provider and set its key in the environment`);
  }
  Object.assign(process.env, plan.env);
  let target: Target;
  try {
    target = await start(options, null, name);
  } catch (error) {
    fail(problem(error));
  }
  const host = target.host;
  const skew = host === null ? null : skewNote(pkg.version, host.version);
  if (skew !== null) {
    process.stderr.write(`warning: ${skew}\n`);
  }
  if (host !== null && plan.choice !== null) {
    const applied = await host.control.configure(toConfig(plan.choice, plan.key));
    if (!applied.ok) {
      await host.stop();
      fail(`could not use the model: ${applied.error ?? "unknown error"}`);
    }
  }
  const client = new SessionClient(parseLink(target.link), { name, client: { kind: "cli", version: pkg.version } });
  const interrupt = (): void => {
    client.close();
  };
  process.on("SIGINT", interrupt);
  process.on("SIGTERM", interrupt);
  const code = await runPrint(client, { prompt, format: options.outputFormat, commands, room: target.room }, process.stdout, process.stderr);
  await host?.stop();
  process.exit(code);
}

async function run(options: SessionOptions, joinLink: string | null, name: string): Promise<void> {
  if (options.print) {
    await printOnce(options, name);
    return;
  }
  const settings = loadSettings();
  const alerts = new Alerts();
  const updater = new Updater({ current: pkg.version, execPath: process.execPath });
  void updater.check();
  let plan;
  let startup;
  try {
    plan = planAgent(settings, loadKeys(), options);
    startup = startupCommands(options);
  } catch (error) {
    fail(problem(error));
  }
  Object.assign(process.env, plan.env);
  let target: Target;
  try {
    target = await start(options, joinLink, name);
  } catch (error) {
    fail(problem(error));
  }
  const { host, tunnel } = target;
  tunnel?.onExit((reason) =>
    alerts.emit(
      "danger",
      `the ${options.tunnel} tunnel stopped (${reason.split("\n")[0]}). Links through it no longer work and nobody new can join. Quit and start plural again to get a new address.`,
    ),
  );
  let parsed;
  try {
    parsed = parseLink(target.link);
  } catch (error) {
    await host?.stop();
    await tunnel?.stop();
    fail(error instanceof Error ? error.message : String(error));
  }

  const team = loadTeam();
  const watcher = team === null ? undefined : new TeamWatcher(team);
  watcher?.start();
  const keys = loadKeys();
  const control = host?.control ?? null;
  const skew = host === null ? null : skewNote(pkg.version, host.version);
  let startupNote: string | null = skew ?? target.note;
  if (control && plan.choice !== null) {
    if (plan.problem !== null) {
      startupNote = `could not use the model: ${plan.problem}. Open the settings (F2) to fix it.`;
    } else {
      progress.step(`loading the model (${plan.choice.preset})…`);
      const applied = await control.configure(toConfig(plan.choice, plan.key));
      if (!applied.ok) {
        startupNote = `could not use the model: ${applied.error ?? "unknown error"}. Open the settings (F2) to fix it.`;
      }
    }
  }
  const client = new SessionClient(parsed, {
    name,
    client: { kind: "tui", version: pkg.version },
    team: target.visiting === null ? undefined : (room) => teamProof(target.visiting as Team, room),
    onWelcome: target.joined ? ({ room, token }) => rememberJoined({ room, url: parsed.url, token, name }) : undefined,
  });
  progress.step("opening the session…");
  const renderer = await createCliRenderer({ exitOnCtrlC: false, useMouse: true });
  progress.done();
  const quit = new Promise<void>((resolve) => {
    createRoot(renderer).render(
      <Shell
        team={team}
        watcher={watcher}
        home={basename(process.cwd())}
        connect={(card, member) =>
          new SessionClient(parseLink((card.endpoints[0] as { url: string }).url), {
            name,
            client: { kind: "tui", version: pkg.version },
            team: (room) => teamProof(member, room),
          })
        }
        app={{
          client,
          room: target.room,
          version: pkg.version,
          guestLink: target.guestLink,
          settings,
          onSettings: saveSettings,
          control,
          keys,
          onKeys: (preset, key, remember) => {
            const stored = loadKeys();
            if (remember && key !== "") {
              stored[preset] = key;
            } else {
              delete stored[preset];
            }
            saveKeys(stored);
          },
          startupNote,
          startup: target.joined ? [] : startup,
          initialPrompt: options.prompt,
          alerts,
          updater,
          splash: true,
          onQuit: () => {
            resolve();
          },
        }}
      />,
    );
    process.on("SIGTERM", () => resolve());
    process.on("SIGINT", () => resolve());
  });
  await quit;
  watcher?.stop();
  renderer.destroy();
  await host?.stop();
  await tunnel?.stop();
  process.exit(0);
}

async function main(): Promise<void> {
  let parsed;
  try {
    parsed = parseArgs(fixDashes(process.argv.slice(2)));
  } catch (error) {
    fail(problem(error));
  }
  if (parsed.kind === "version") {
    process.stdout.write(`${pkg.version}\n`);
  } else if (parsed.kind === "help") {
    process.stdout.write(USAGE);
  } else if (parsed.kind === "selftest") {
    const probe = await createCliRenderer({ exitOnCtrlC: false, useMouse: false });
    probe.destroy();
    process.stdout.write("selftest ok\n");
    process.exit(0);
  } else if (parsed.kind === "update") {
    process.exit(await runUpdate({ check: parsed.check }, { current: pkg.version, execPath: process.execPath, out: process.stdout, err: process.stderr }));
  } else if (parsed.kind === "passthrough") {
    const child = runHostCommand(parsed.args);
    child.on("exit", (code) => process.exit(code ?? 0));
  } else if (parsed.kind === "join") {
    if (parsed.link === null) {
      fail("usage: plural join <link|@name> [--name <name>], or plural -r to go back to a room you were in");
    }
    await run(emptyOptions(), parsed.link, parsed.displayName ?? userInfo().username);
  } else {
    await run(parsed.options, null, parsed.options.displayName ?? userInfo().username);
  }
}

void main();
