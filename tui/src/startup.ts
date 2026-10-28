import type { Command } from "@plural/client";
import { UsageError, type SessionOptions } from "./options";

const TOOLS: Record<string, string> = {
  bash: "bash",
  read: "read",
  write: "write",
  edit: "edit",
  multiedit: "multi_edit",
  multi_edit: "multi_edit",
  grep: "grep",
  glob: "glob",
  ls: "ls",
  webfetch: "web_fetch",
  web_fetch: "web_fetch",
  websearch: "web_search",
  web_search: "web_search",
  skill: "skill",
};

export interface ToolRule {
  tool: string;
  pattern: string;
}

export function toolRule(spec: string): ToolRule {
  const match = /^([A-Za-z_]+)(?:\((.*)\))?$/s.exec(spec.trim());
  if (match === null) {
    throw new UsageError(`${spec} is not a tool, write Bash or Bash(git log *)`);
  }
  const name = (match[1] as string).toLowerCase();
  const tool = TOOLS[name];
  if (tool === undefined) {
    throw new UsageError(`there is no tool ${match[1]}, the tools are ${Object.values(TOOLS).filter((value, index, all) => all.indexOf(value) === index).join(", ")}`);
  }
  const inner = (match[2] ?? "").trim();
  const pattern = inner === "" ? "*" : inner.replace(/:\*$/, " *");
  return { tool, pattern };
}

export function startupCommands(options: Pick<SessionOptions, "permissionMode" | "allowedTools" | "disallowedTools">): Command[] {
  const commands: Command[] = [];
  if (options.permissionMode !== null) {
    commands.push({ type: "session.set_permission_mode", mode: options.permissionMode as "default" | "accept_edits" | "plan" | "auto" });
  }
  for (const spec of options.allowedTools) {
    commands.push({ type: "policy.add", ...toolRule(spec), action: "allow" });
  }
  for (const spec of options.disallowedTools) {
    commands.push({ type: "policy.add", ...toolRule(spec), action: "deny" });
  }
  return commands;
}
