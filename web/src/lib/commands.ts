import { visibleCommands, type CommandHint, type Role } from "@plural/client";

const KEYS = [
  "enter                              send",
  "shift+enter                        new line",
  "y / a / n / b                      answer the approval card (host)",
  "esc                                stop the run (host, with an empty input)",
  "click a tool line                  open its output or diff",
];

export function helpText(role: Role | undefined, plugins: CommandHint[] = []): string {
  const commands = visibleCommands("browser", role, plugins).map((command) => `${command.usage.padEnd(34)} ${command.description}`);
  return ["commands", ...commands, "", "keys", ...KEYS].join("\n");
}
