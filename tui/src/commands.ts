import { commandSuggestions, mentionCompletions, mentionNote, visibleCommands, type CommandHint, type Mentionable, type Role } from "@plural/client";

export function mentionHints(value: string, people: Mentionable[]): CommandHint[] {
  return mentionCompletions(value, people).map(({ person, insert }) => ({
    name: person.id,
    usage: `@${person.label}`,
    description: mentionNote(person),
    insert,
  }));
}

export function suggestions(
  value: string,
  role: Role | undefined,
  people: Mentionable[] = [],
  plugins: CommandHint[] = [],
): CommandHint[] {
  if (value.startsWith("/") && !/\s/.test(value)) {
    return commandSuggestions("terminal", value, role, plugins);
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
  const commands = visibleCommands("terminal", role).map((command) => `  ${command.usage.padEnd(30)} ${command.description}`);
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
