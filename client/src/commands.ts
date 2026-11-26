import type { ChatMode, Command, PluginCommandView, PromptMode, Role, SkillView } from "./protocol";
import { SlashError, type Slash } from "./slash";

// Every slash command, once. The terminal client and the web client read this list for what to suggest, what /help says, who
// may run what and how a line is parsed; only what a command does on screen is each client's own.
//
//   kind "parsed"  the line becomes a protocol command or a `show.*` request, the same everywhere (`parse` is here);
//   kind "local"   each client carries it out itself, and TypeScript makes it name a handler for every surface it works on;
//   kind "chat"    the chat parser takes it (`/team`).
//
// `surfaces` says where a command works (both by default), `unlisted` where it works but is not offered in suggestions and
// /help, `describe` a different line for one surface.
export type Surface = "tui" | "web";

interface Base {
  name: string;
  usage: string;
  description: string;
  hostOnly?: boolean;
  surfaces?: readonly Surface[];
  unlisted?: readonly Surface[];
  describe?: Partial<Record<Surface, string>>;
}

type Spec = Base & ({ kind: "parsed"; parse: (argument: string) => Slash } | { kind: "local" } | { kind: "chat" });

const POLICY_USAGE =
  "usage: /policy | /policy allow|ask|deny <tool> <pattern> | /policy rm <rule id>";
const MODE_USAGE = "usage: /mode open|review";
const REPLIES_USAGE = "usage: /replies mention|all";
const DANGER_USAGE = "usage: /danger on|off";

const SKILLS_USAGE = "usage: /skills | /skills search <query> | /skills add <owner/repo@skill> [--global] | /skills rm <name>";

const PLUGINS_USAGE = "usage: /plugins | /plugins new <name> | /plugins rm <name> | /plugins reload";

const MCP_USAGE =
  "usage: /mcp | /mcp add <name> <command…|url> [--global] | /mcp on|off|restart|rm <name> | /mcp import";


const SPECS = [
  { name: "help", usage: "/help", description: "show commands and keys", kind: "local" },
  { name: "who", usage: "/who", description: "list participants", kind: "local" },
  { name: "draw", usage: "/draw", description: "open a board everyone draws on", kind: "local", surfaces: ["web"] },
  { name: "team", usage: "/team <message>", description: "write to the room; the agent reads it only in mention mode", kind: "chat" },
  {
    name: "invite", usage: "/invite [link|once|viewer|revoke|open|approve]", description: "copy the room link, or a one-time invite, or change who may join", hostOnly: true, kind: "local",
    describe: { web: "show the room link, or a one-time invite, or change who may join" },
  },
  { name: "import", usage: "/import", description: "the address that lets Claude, ChatGPT or Grok send a chat's context to this session", hostOnly: true, kind: "local" },
  { name: "brief", usage: "/brief share off|ask|team", description: "who may ask your agent for a briefing of this session", hostOnly: true, kind: "local", unlisted: ["tui"] },
  { name: "ask", usage: "/ask @name <question> · /ask give", description: "ask a teammate's agent about their session, then hand the answer to yours (host: /ask share off|ask|team)", kind: "local", unlisted: ["web"] },
  { name: "handover", usage: "/handover <name> | cancel", description: "hand the host to a participant on their computer; the room and the conversation go with it", hostOnly: true, kind: "local" },
  { name: "approver", usage: "/approver [add|rm <name>]", description: "let a participant answer tool calls when you are away (once or refuse, never a rule)", hostOnly: true, kind: "local" },
  { name: "access", usage: "/access [note]", description: "ask the host for the right to write (host: allow|deny|revoke <name>)", kind: "local" },
  {
    name: "preview", usage: "/preview <port> [title] | off", description: "show a server running on this machine in the web canvas", hostOnly: true, kind: "local",
    describe: { web: "show a server running on this machine in the canvas" },
  },
  { name: "kick", usage: "/kick <name>", description: "remove someone from the session; a team member stays out", hostOnly: true, kind: "local" },
  { name: "mode", usage: "/mode open|review", description: "who may prompt directly", hostOnly: true, kind: "parsed", parse: mode },
  { name: "replies", usage: "/replies mention|all", description: "the agent answers only @plrl, or every message", hostOnly: true, kind: "parsed", parse: replies },
  { name: "danger", usage: "/danger on|off", description: "danger zone: guests' edits and commands run without asking you", hostOnly: true, kind: "parsed", parse: danger },
  { name: "policy", usage: "/policy [allow|ask|deny <tool> <pattern> | rm <id>]", description: "show or edit permission rules", hostOnly: true, kind: "parsed", parse: policy },
  { name: "skills", usage: "/skills [search <q> | add <owner/repo@skill> [--global] | rm <name>]", description: "list, find and install skills", kind: "parsed", parse: skills },
  { name: "mcp", usage: "/mcp [add <name> <command|url> [--global] | on|off|restart|rm <name> | import]", description: "connect MCP servers and their tools", kind: "parsed", parse: mcp },
  { name: "agents", usage: "/agents [rm <name>]", description: "sub-agents the agent can hand work to; create your own", kind: "parsed", parse: agents, unlisted: ["web"] },
  { name: "usage", usage: "/usage", description: "tokens spent per model and agent in this session", kind: "parsed", parse: () => ({ type: "show.usage" }) },
  { name: "context", usage: "/context", description: "what fills the agent's context, and whether the cache was used", kind: "parsed", parse: () => ({ type: "show.context" }) },
  // What a run did, as a tree: the latest run, or with "all" every run of the session.
  {
    name: "trace", usage: "/trace [all]", description: "what the last run did and what each step spent; all: who called what in the session", kind: "parsed",
    parse: (argument) => ({ type: "trace.get", run_id: null, everything: argument === "all" }),
  },
  { name: "plugins", usage: "/plugins [new <name> | reload]", description: "the host's plugins and their commands", kind: "parsed", parse: pluginsCommand },
  { name: "fork", usage: "/fork [title]", description: "copy this session into a new one and go on there", hostOnly: true, kind: "local", surfaces: ["tui"] },
  { name: "resume", usage: "/resume <id|title>", description: "switch to another session of yours", hostOnly: true, kind: "local", surfaces: ["tui"] },
  { name: "compact", usage: "/compact", description: "summarize the context before the next prompt", hostOnly: true, kind: "parsed", parse: () => ({ type: "context.compact" }) },
  { name: "abort", usage: "/abort", description: "stop the current run", hostOnly: true, kind: "parsed", parse: () => ({ type: "run.abort" }) },
  { name: "cancel", usage: "/cancel <n>", description: "remove a queued prompt (yours, or any as host)", kind: "local" },
  { name: "settings", usage: "/settings", description: "theme, prompt mode and other preferences", kind: "local", surfaces: ["tui"] },
  { name: "copy", usage: "/copy", description: "copy the last reply to the clipboard", kind: "local" },
  { name: "leave", usage: "/leave", description: "leave the room", kind: "local", surfaces: ["web"] },
  { name: "quit", usage: "/quit", description: "leave the session", kind: "local", surfaces: ["tui"] },
] as const satisfies readonly Spec[];

type Entry = (typeof SPECS)[number];
type WorksOn<E, S extends Surface> = E extends { surfaces: readonly (infer W)[] } ? (S extends W ? E : never) : E;
/** The commands a client carries out itself on that surface: it needs a handler for each, and only for these. */
export type LocalName<S extends Surface> = Extract<WorksOn<Entry, S>, { kind: "local" }>["name"];

export interface CommandHint {
  name: string;
  usage: string;
  description: string;
  hostOnly?: boolean;
  /** What picking the hint puts in the input, when that is not just the command. */
  insert?: string;
}

const specs: readonly Spec[] = SPECS;
const worksOn = (spec: Spec, surface: Surface): boolean => spec.surfaces === undefined || spec.surfaces.includes(surface);

/** What the surface offers in suggestions and /help, for everyone; `visibleCommands` narrows it to one role. */
export function listedCommands(surface: Surface): CommandHint[] {
  return specs
    .filter((spec) => worksOn(spec, surface) && !spec.unlisted?.includes(surface))
    .map((spec) => ({
      name: spec.name,
      usage: spec.usage,
      description: spec.describe?.[surface] ?? spec.description,
      ...(spec.hostOnly ? { hostOnly: true } : {}),
    }));
}

export function visibleCommands(surface: Surface, role: Role | undefined, extra: readonly CommandHint[] = []): CommandHint[] {
  return [...listedCommands(surface), ...extra].filter((command) => !command.hostOnly || role === "host");
}

/** The commands that complete `value` as a command name: only while the first word is still being typed. */
export function suggestCommands(surface: Surface, value: string, role: Role | undefined, extra: readonly CommandHint[] = []): CommandHint[] {
  if (!value.startsWith("/") || /\s/.test(value)) {
    return [];
  }
  const prefix = value.slice(1).toLowerCase();
  return visibleCommands(surface, role, extra).filter((command) => command.name.startsWith(prefix));
}

export function commandName(text: string): string {
  return text.slice(1).split(/\s+/)[0] ?? "";
}

/** Whether only the host may run the command in `text`, built in (listed or not) or from a plugin. */
export function isHostOnly(surface: Surface, text: string, extra: readonly CommandHint[] = []): boolean {
  const name = commandName(text);
  return specs.some((spec) => spec.name === name && worksOn(spec, surface) && spec.hostOnly === true) || extra.some((command) => command.name === name && command.hostOnly === true);
}

/** The command a client has to carry out itself, if `name` is one on this surface. Switch on its `name` and end with `assertNever`. */
export function localCommand<S extends Surface>(surface: S, name: string): { name: LocalName<S> } | undefined {
  const spec = specs.find((item) => item.name === name && item.kind === "local" && worksOn(item, surface));
  return spec === undefined ? undefined : { name: spec.name as LocalName<S> };
}

export function assertNever(value: never): never {
  throw new Error(`a local command has no handler: ${String(value)}`);
}

export function pluginHints(commands: readonly PluginCommandView[]): CommandHint[] {
  return commands.map((command) => ({
    name: command.name,
    usage: command.usage ?? `/${command.name}`,
    description: command.description || `from the ${command.plugin} plugin`,
    hostOnly: command.host_only ?? false,
  }));
}

/** `/skill:<name>` for every skill, the only way to run one the model does not see. */
export function skillHints(skills: readonly SkillView[]): CommandHint[] {
  return skills.map((skill) => ({
    name: `skill:${skill.name}`,
    usage: `/skill:${skill.name} [request]`,
    description: skill.description || "run this skill",
  }));
}

/** `plugins` names the commands the host's plugins provide; they are sent to the host as `command.run`. */
export function parseSlash(text: string, plugins: ReadonlySet<string> = new Set()): Slash | null {
  if (!text.startsWith("/")) {
    return null;
  }
  const rest = text.slice(1);
  const space = rest.indexOf(" ");
  const name = space === -1 ? rest : rest.slice(0, space);
  const argument = space === -1 ? "" : rest.slice(space + 1).trim();
  const spec = specs.find((item) => item.name === name);
  if (spec?.kind === "parsed") {
    return spec.parse(argument);
  }
  if (plugins.has(name)) {
    return { type: "command.run", name, args: argument };
  }
  throw new SlashError(`unknown command /${name}`);
}

function agents(argument: string): Slash {
  const [verb, name] = argument.split(/\s+/).filter(Boolean);
  if (verb === undefined) {
    return { type: "show.agents" };
  }
  if (verb === "rm" && name) {
    return { type: "agents.remove", name };
  }
  throw new SlashError("usage: /agents | /agents rm <name>");
}

function pluginsCommand(argument: string): Slash {
  if (argument === "") {
    return { type: "show.plugins" };
  }
  if (argument === "reload") {
    return { type: "plugins.reload" };
  }
  const [verb, name, ...extra] = argument.split(/\s+/);
  if ((verb !== "new" && verb !== "rm") || !name || extra.length > 0 || !/^[a-z][a-z0-9_-]*$/.test(name)) {
    throw new SlashError(PLUGINS_USAGE);
  }
  return verb === "new" ? { type: "plugins.create", name } : { type: "plugins.remove", name };
}

function mode(argument: string): Command {
  if (argument !== "open" && argument !== "review") {
    throw new SlashError(MODE_USAGE);
  }
  return { type: "session.set_prompt_mode", mode: argument satisfies PromptMode };
}

/** mention: the agent answers @plrl and reads the rest as chat; all: it answers every message. */
function replies(argument: string): Command {
  if (argument !== "mention" && argument !== "all") {
    throw new SlashError(REPLIES_USAGE);
  }
  return { type: "session.set_chat_mode", mode: argument satisfies ChatMode };
}

/** on: guests' edits and commands run without asking the host; off: back to asking. Typed out on purpose, never on a key. */
function danger(argument: string): Command {
  if (argument !== "on" && argument !== "off") {
    throw new SlashError(DANGER_USAGE);
  }
  return { type: "session.set_permission_mode", mode: argument === "on" ? "danger" : "default" };
}

function policy(argument: string): Slash {
  if (argument === "") {
    return { type: "show.policy" };
  }
  const space = argument.indexOf(" ");
  const verb = space === -1 ? argument : argument.slice(0, space);
  const rest = space === -1 ? "" : argument.slice(space + 1).trim();
  if (verb === "rm") {
    if (rest === "") {
      throw new SlashError(POLICY_USAGE);
    }
    return { type: "policy.remove", rule_id: rest };
  }
  if (verb !== "allow" && verb !== "ask" && verb !== "deny") {
    throw new SlashError(POLICY_USAGE);
  }
  const split = rest.indexOf(" ");
  const tool = split === -1 ? rest : rest.slice(0, split);
  const pattern = split === -1 ? "" : rest.slice(split + 1).trim();
  if (tool === "" || pattern === "") {
    throw new SlashError(POLICY_USAGE);
  }
  return { type: "policy.add", tool, pattern, action: verb };
}

function skills(argument: string): Slash {
  if (argument === "") {
    return { type: "show.skills" };
  }
  const space = argument.indexOf(" ");
  const verb = space === -1 ? argument : argument.slice(0, space);
  const rest = space === -1 ? "" : argument.slice(space + 1).trim();
  if (rest === "") {
    throw new SlashError(SKILLS_USAGE);
  }
  switch (verb) {
    case "search":
      return { type: "skills.search", query: rest };
    case "add": {
      const words = rest.split(/\s+/);
      const global = words.includes("--global");
      const packages = words.filter((word) => word !== "--global");
      if (packages.length !== 1) {
        throw new SlashError(SKILLS_USAGE);
      }
      return { type: "skills.install", package: packages[0]!, scope: global ? "global" : "project" };
    }
    case "rm":
      return { type: "skills.remove", name: rest };
    default:
      throw new SlashError(SKILLS_USAGE);
  }
}

function mcp(argument: string): Slash {
  const words = argument.split(/\s+/).filter(Boolean);
  const [verb, name, ...rest] = words;
  switch (verb) {
    case undefined:
      return { type: "show.mcp" };
    case "import":
      return { type: "mcp.import" };
    case "add": {
      const global = rest.includes("--global");
      const target = rest.filter((word) => word !== "--global");
      if (!name || target.length === 0) {
        throw new SlashError(MCP_USAGE);
      }
      const scope = global ? "global" : "project";
      const first = target[0]!;
      if (/^https?:\/\//.test(first)) {
        return { type: "mcp.add", name, url: first, args: [], command: null, scope };
      }
      return { type: "mcp.add", name, command: first, args: target.slice(1), url: null, scope };
    }
    case "on":
    case "off":
      if (!name) {
        throw new SlashError(MCP_USAGE);
      }
      return { type: "mcp.toggle", name, enabled: verb === "on" };
    case "restart":
      if (!name) {
        throw new SlashError(MCP_USAGE);
      }
      return { type: "mcp.restart", name };
    case "rm":
      if (!name) {
        throw new SlashError(MCP_USAGE);
      }
      return { type: "mcp.remove", name };
    default:
      throw new SlashError(MCP_USAGE);
  }
}
