import { commandName, isHostOnly as hostOnlyOn, listedCommands, pluginHints, skillHints, suggestCommands, visibleCommands as visibleOn, type CommandHint, type Role } from "@plural/client";

export { commandName, pluginHints, skillHints };

// What the commands are lives in @plural/client, once, for this client and the terminal one; this file is the web client's view of it.
export type { CommandHint };

/** Everything the web client offers, for any role. */
export const COMMANDS: CommandHint[] = listedCommands("web");

const KEYS = [
  "enter                              send",
  "shift+enter                        new line",
  "y / a / n / b                      answer the approval card (host)",
  "esc                                stop the run (host, with an empty input)",
  "click a tool line                  open its output or diff",
];

export function visibleCommands(role: Role | undefined, plugins: CommandHint[] = []): CommandHint[] {
  return visibleOn("web", role, plugins);
}

export function suggestions(value: string, role: Role | undefined, plugins: CommandHint[] = []): CommandHint[] {
  return suggestCommands("web", value, role, plugins);
}

export function isHostOnly(text: string, plugins: CommandHint[] = []): boolean {
  return hostOnlyOn("web", text, plugins);
}

export function helpText(role: Role | undefined, plugins: CommandHint[] = []): string {
  const commands = visibleCommands(role, plugins).map((command) => `${command.usage.padEnd(34)} ${command.description}`);
  return ["commands", ...commands, "", "keys", ...KEYS].join("\n");
}
