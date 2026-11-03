import type { PluginCommandView, Role, SkillView } from "./protocol";

export type Surface = "terminal" | "browser";

export interface CommandHint {
  name: string;
  usage: string;
  description: string;
  hostOnly?: boolean;
  insert?: string;
}

interface Entry extends CommandHint {
  only?: Surface;
}

const CATALOG: readonly Entry[] = [
  { name: "help", usage: "/help", description: "show commands and keys" },
  { name: "who", usage: "/who", description: "list participants" },
  { name: "draw", usage: "/draw", description: "open a board everyone draws on", only: "browser" },
  { name: "team", usage: "/team <message>", description: "write to the room, the agent does not see it" },
  { name: "invite", usage: "/invite [link|once|viewer|revoke|open|approve]", description: "the room link, or a one-time invite, or change who may join", hostOnly: true },
  {
    name: "brief",
    usage: "/brief [question] · /brief update · /brief give",
    description: "ask a teammate's agent for a briefing of their session, then hand it to yours (host: /brief share off|ask|team)",
    only: "terminal",
  },
  { name: "brief", usage: "/brief share off|ask|team", description: "who may ask your agent for a briefing of this session", hostOnly: true, only: "browser" },
  { name: "access", usage: "/access [note]", description: "ask the host for the right to write (host: allow|deny|revoke <name>)" },
  { name: "kick", usage: "/kick <name>", description: "remove someone from the session; a team member stays out", hostOnly: true },
  { name: "mode", usage: "/mode open|review", description: "who may prompt directly", hostOnly: true },
  { name: "policy", usage: "/policy [allow|ask|deny <tool> <pattern> | rm <id>]", description: "show or edit permission rules", hostOnly: true },
  { name: "skills", usage: "/skills [search <q> | add <owner/repo@skill> [--global] | rm <name>]", description: "list, find and install skills" },
  { name: "mcp", usage: "/mcp [add <name> <command|url> [--global] | on|off|restart|rm <name> | import]", description: "connect MCP servers and their tools" },
  { name: "agents", usage: "/agents [rm <name>]", description: "sub-agents the agent can hand work to; create your own" },
  { name: "usage", usage: "/usage", description: "tokens spent per model and agent in this session" },
  { name: "context", usage: "/context", description: "what fills the agent's context, and whether the cache was used" },
  { name: "plugins", usage: "/plugins [new <name> | reload]", description: "the host's plugins and their commands" },
  { name: "compact", usage: "/compact", description: "summarize the context before the next prompt", hostOnly: true },
  { name: "abort", usage: "/abort", description: "stop the current run", hostOnly: true },
  { name: "cancel", usage: "/cancel <n>", description: "remove a queued prompt (yours, or any as host)" },
  { name: "settings", usage: "/settings", description: "theme, prompt mode and other preferences", only: "terminal" },
  { name: "copy", usage: "/copy", description: "copy the last reply to the clipboard" },
  { name: "leave", usage: "/leave", description: "leave the room", only: "browser" },
  { name: "quit", usage: "/quit", description: "leave the session", only: "terminal" },
];

export function commandsFor(surface: Surface): CommandHint[] {
  return CATALOG.filter((entry) => entry.only === undefined || entry.only === surface).map(({ only: _only, ...hint }) => hint);
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

export function visibleCommands(surface: Surface, role: Role | undefined, plugins: CommandHint[] = []): CommandHint[] {
  return [...commandsFor(surface), ...plugins].filter((command) => !command.hostOnly || role === "host");
}

/** The commands a half-typed `/name` could become. */
export function commandSuggestions(surface: Surface, value: string, role: Role | undefined, plugins: CommandHint[] = []): CommandHint[] {
  if (!value.startsWith("/") || /\s/.test(value)) {
    return [];
  }
  const prefix = value.slice(1).toLowerCase();
  return visibleCommands(surface, role, plugins).filter((command) => command.name.startsWith(prefix));
}

export function commandName(text: string): string {
  return text.slice(1).split(/\s+/)[0] ?? "";
}

export function isHostOnly(surface: Surface, text: string, plugins: CommandHint[] = []): boolean {
  const name = commandName(text);
  return [...commandsFor(surface), ...plugins].some((command) => command.name === name && command.hostOnly === true);
}
