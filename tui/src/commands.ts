import { mentionCompletions, mentionNote, type Mentionable, type Role } from "@plural/client";

export interface CommandHint {
  name: string;
  usage: string;
  description: string;
  hostOnly?: boolean;
  insert?: string;
}

export const COMMANDS: CommandHint[] = [
  { name: "help", usage: "/help", description: "show commands and keys" },
  { name: "who", usage: "/who", description: "list participants" },
  { name: "team", usage: "/team <message>", description: "write to the room, the agent does not see it" },
  { name: "invite", usage: "/invite [participant|viewer]", description: "create an invite link", hostOnly: true },
  { name: "mode", usage: "/mode open|review", description: "who may prompt directly", hostOnly: true },
  { name: "policy", usage: "/policy [allow|ask|deny <tool> <pattern> | rm <id>]", description: "show or edit permission rules", hostOnly: true },
  { name: "skills", usage: "/skills [search <q> | add <owner/repo@skill> [--global] | rm <name>]", description: "list, find and install skills" },
  { name: "mcp", usage: "/mcp [add <name> <command|url> [--global] | on|off|restart|rm <name> | import]", description: "connect MCP servers and their tools" },
  { name: "compact", usage: "/compact", description: "summarize the context before the next prompt", hostOnly: true },
  { name: "abort", usage: "/abort", description: "stop the current run", hostOnly: true },
  { name: "cancel", usage: "/cancel <n>", description: "remove a queued prompt (yours, or any as host)" },
  { name: "settings", usage: "/settings", description: "theme, prompt mode and other preferences" },
  { name: "copy", usage: "/copy", description: "copy the last reply to the clipboard" },
  { name: "quit", usage: "/quit", description: "leave the session" },
];

export function visibleCommands(role: Role | undefined): CommandHint[] {
  return COMMANDS.filter((command) => !command.hostOnly || role === "host");
}

export function mentionHints(value: string, people: Mentionable[]): CommandHint[] {
  return mentionCompletions(value, people).map(({ person, insert }) => ({
    name: person.id,
    usage: `@${person.label}`,
    description: mentionNote(person),
    insert,
  }));
}

export function suggestions(value: string, role: Role | undefined, people: Mentionable[] = []): CommandHint[] {
  if (value.startsWith("/") && !value.includes(" ") && !value.includes("\n")) {
    const prefix = value.slice(1).toLowerCase();
    return visibleCommands(role).filter((command) => command.name.startsWith(prefix));
  }
  return mentionHints(value, people);
}

export function visibleSuggestionWindow(
  commands: CommandHint[],
  selectedIndex: number,
  limit = 6,
): { items: CommandHint[]; selectedIndex: number } {
  const size = Math.max(0, Math.min(commands.length, Math.floor(limit)));
  if (size === 0) {
    return { items: [], selectedIndex: 0 };
  }

  const selected = Math.max(0, Math.min(commands.length - 1, Math.floor(selectedIndex)));
  const start = Math.max(0, Math.min(selected - Math.floor(size / 2), commands.length - size));
  return { items: commands.slice(start, start + size), selectedIndex: selected - start };
}

export function helpText(role: Role | undefined): string {
  const commands = visibleCommands(role).map((command) => `  ${command.usage.padEnd(30)} ${command.description}`);
  const keys = [
    "  enter           send",
    "  shift+enter     new line (ctrl+j in any terminal)",
    "  tab             review approvals and proposals / complete a command or @name",
    "  shift+tab       cycle permissions: ask · accept edits · plan · auto (host)",
    "  esc             interrupt the run",
    "  pgup / pgdn     scroll the conversation",
    "  ctrl+o          expand or collapse tool details (or click a tool line)",
    "  ctrl+b          show or hide the side panel",
    "  select text     copies it to the clipboard",
    "  ctrl+y          copy the last reply",
    "  ctrl+c          clear the input, twice to quit",
  ];
  return ["commands", ...commands, "", "keys", ...keys].join("\n");
}
