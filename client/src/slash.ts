import type { Command } from "./protocol";

export class SlashError extends Error {}

/** `/skill:name request` runs a skill by hand; the host expands it, so it goes out as a prompt. */
export const SKILL_COMMAND = "/skill:";

export function isSkillCommand(text: string): boolean {
  return text.startsWith(SKILL_COMMAND) && text.length > SKILL_COMMAND.length;
}

export type Slash =
  | Command
  | { type: "show.policy" }
  | { type: "show.skills" }
  | { type: "show.mcp" }
  | { type: "show.agents" }
  | { type: "show.usage" }
  | { type: "show.context" }
  | { type: "show.plugins" };
