import type { Role } from "@plural/client";

export interface CommandHint {
  name: string;
  usage: string;
  description: string;
  hostOnly?: boolean;
}

export const COMMANDS: CommandHint[] = [
  { name: "help", usage: "/help", description: "show commands and keys" },
  { name: "who", usage: "/who", description: "list participants" },
  { name: "draw", usage: "/draw", description: "open a board everyone draws on" },
  { name: "team", usage: "/team <message>", description: "write to the room, the agent does not see it" },
  { name: "invite", usage: "/invite [link|once|viewer|revoke|open|approve]", description: "show the room link, or a one-time invite, or change who may join", hostOnly: true },
  { name: "kick", usage: "/kick <name>", description: "remove someone from the session; a team member stays out", hostOnly: true },
  { name: "mode", usage: "/mode open|review", description: "who may prompt directly", hostOnly: true },
  { name: "policy", usage: "/policy [allow|ask|deny <tool> <pattern> | rm <id>]", description: "show or edit permission rules", hostOnly: true },
  { name: "skills", usage: "/skills [search <q> | add <owner/repo@skill> [--global] | rm <name>]", description: "list, find and install skills" },
  { name: "mcp", usage: "/mcp [add <name> <command|url> [--global] | on|off|restart|rm <name> | import]", description: "connect MCP servers and their tools" },
  { name: "compact", usage: "/compact", description: "summarize the context before the next prompt", hostOnly: true },
  { name: "abort", usage: "/abort", description: "stop the current run", hostOnly: true },
  { name: "cancel", usage: "/cancel <n>", description: "remove a queued prompt" },
  { name: "copy", usage: "/copy", description: "copy the last reply" },
  { name: "leave", usage: "/leave", description: "leave the room" },
];

const KEYS = [
  "enter                              send",
  "shift+enter                        new line",
  "y / a / n / b                      answer the approval card (host)",
  "esc                                stop the run (host, with an empty input)",
  "click a tool line                  open its output or diff",
];

export function visibleCommands(role: Role | undefined): CommandHint[] {
  return COMMANDS.filter((command) => !command.hostOnly || role === "host");
}

export function suggestions(value: string, role: Role | undefined): CommandHint[] {
  if (!value.startsWith("/") || /\s/.test(value)) {
    return [];
  }
  const prefix = value.slice(1).toLowerCase();
  return visibleCommands(role).filter((command) => command.name.startsWith(prefix));
}

export function commandName(text: string): string {
  return text.slice(1).split(/\s+/)[0] ?? "";
}

export function isHostOnly(text: string): boolean {
  const name = commandName(text);
  return COMMANDS.some((command) => command.name === name && command.hostOnly === true);
}

export function helpText(role: Role | undefined): string {
  const commands = visibleCommands(role).map((command) => `${command.usage.padEnd(34)} ${command.description}`);
  return ["commands", ...commands, "", "keys", ...KEYS].join("\n");
}
