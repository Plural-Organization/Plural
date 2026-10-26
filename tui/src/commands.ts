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
  { name: "invite", usage: "/invite [participant|viewer]", description: "create an invite link", hostOnly: true },
  { name: "mode", usage: "/mode open|review", description: "who may prompt directly", hostOnly: true },
  { name: "policy", usage: "/policy [allow|ask|deny <tool> <pattern> | rm <id>]", description: "show or edit permission rules", hostOnly: true },
  { name: "compact", usage: "/compact", description: "summarize the context before the next prompt", hostOnly: true },
  { name: "abort", usage: "/abort", description: "stop the current run", hostOnly: true },
  { name: "copy", usage: "/copy", description: "copy the last reply to the clipboard" },
  { name: "quit", usage: "/quit", description: "leave the session" },
];

export function visibleCommands(role: Role | undefined): CommandHint[] {
  return COMMANDS.filter((command) => !command.hostOnly || role === "host");
}

export function suggestions(value: string, role: Role | undefined): CommandHint[] {
  if (!value.startsWith("/") || value.includes(" ") || value.includes("\n")) {
    return [];
  }
  const prefix = value.slice(1).toLowerCase();
  return visibleCommands(role).filter((command) => command.name.startsWith(prefix));
}

export function helpText(role: Role | undefined): string {
  const commands = visibleCommands(role).map((command) => `  ${command.usage.padEnd(30)} ${command.description}`);
  const keys = [
    "  enter           send",
    "  shift+enter     new line (ctrl+j in any terminal)",
    "  tab             review approvals and proposals / complete a command",
    "  esc             interrupt the run",
    "  pgup / pgdn     scroll the conversation",
    "  ctrl+b          show or hide the side panel",
    "  select text     copies it to the clipboard",
    "  ctrl+y          copy the last reply",
    "  ctrl+c          clear the input, twice to quit",
  ];
  return ["commands", ...commands, "", "keys", ...keys].join("\n");
}
