import { listedCommands, mentionCompletions, mentionNote, pluginHints, skillHints, suggestCommands, visibleCommands as visibleOn, type CommandHint, type Mentionable, type PluginCommandView, type Role } from "@plural/client";

// What the commands are lives in @plural/client, once, for this client and the web one; this file is the terminal client's view of it.
export type { CommandHint };
export { pluginHints, skillHints };

/** Everything the terminal client offers, for any role. */
export const COMMANDS: CommandHint[] = listedCommands("tui");

/** The plugin command whose shortcut is this key, such as ctrl+r or f5, that this person may run. */
export function shortcutCommand(
  commands: readonly PluginCommandView[],
  key: { name: string; ctrl: boolean },
  role: Role | undefined,
): PluginCommandView | undefined {
  const pressed = key.ctrl ? `ctrl+${key.name}` : key.name;
  return commands.find((command) => command.shortcut === pressed && (!command.host_only || role === "host"));
}

export function visibleCommands(role: Role | undefined, plugins: CommandHint[] = []): CommandHint[] {
  return visibleOn("tui", role, plugins);
}

export function mentionHints(value: string, people: Mentionable[]): CommandHint[] {
  return mentionCompletions(value, people).map(({ person, insert }) => ({
    name: person.id,
    usage: `@${person.label}`,
    description: mentionNote(person),
    insert,
  }));
}

/** A teammate's session `/ask` can reach: `name` is what follows the @, `detail` says where they are. */
export interface AskTarget {
  name: string;
  detail: string;
}

export function askHints(value: string, targets: AskTarget[]): CommandHint[] | null {
  const typing = /^(\/(?:ask|brief)\s+)@([^\s]*)$/i.exec(value);
  if (typing === null) {
    return null;
  }
  const prefix = (typing[2] ?? "").toLowerCase();
  return targets
    .filter((target) => target.name.toLowerCase().startsWith(prefix))
    .map((target) => ({ name: target.name, usage: `@${target.name}`, description: target.detail, insert: `${typing[1] ?? ""}@${target.name} ` }));
}

export function suggestions(
  value: string,
  role: Role | undefined,
  people: Mentionable[] = [],
  plugins: CommandHint[] = [],
  targets: AskTarget[] = [],
): CommandHint[] {
  if (value.startsWith("/") && !value.includes(" ") && !value.includes("\n")) {
    return suggestCommands("tui", value, role, plugins);
  }
  return askHints(value, targets) ?? mentionHints(value, people);
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
    "  ctrl+f          search the conversation: text, commands, paths, is:failed, is:prompt, by:name",
    "  end             jump to the latest message; alt+up / alt+down between prompts",
    "  ctrl+o          expand or collapse tool details (or click a tool line)",
    "  ctrl+b          show or hide the side panel",
    "  select text     copies it to the clipboard",
    "  ctrl+y          copy the last reply",
    "  ctrl+c          clear the input, twice to quit",
  ];
  return ["commands", ...commands, "", "keys", ...keys].join("\n");
}
