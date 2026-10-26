import type { Command, PromptMode } from "./protocol";

const USAGE =
  "usage: /policy | /policy allow|ask|deny <tool> <pattern> | /policy rm <rule id>";
const MODE_USAGE = "usage: /mode open|review";

export class SlashError extends Error {}

export type Slash = Command | { type: "show.policy" };

export function parseSlash(text: string): Slash | null {
  if (!text.startsWith("/")) {
    return null;
  }
  const rest = text.slice(1);
  const space = rest.indexOf(" ");
  const name = space === -1 ? rest : rest.slice(0, space);
  const argument = space === -1 ? "" : rest.slice(space + 1).trim();
  switch (name) {
    case "abort":
      return { type: "run.abort" };
    case "compact":
      return { type: "context.compact" };
    case "mode":
      return mode(argument);
    case "policy":
      return policy(argument);
    default:
      throw new SlashError(`unknown command /${name}`);
  }
}

function mode(argument: string): Command {
  if (argument !== "open" && argument !== "review") {
    throw new SlashError(MODE_USAGE);
  }
  return { type: "session.set_prompt_mode", mode: argument satisfies PromptMode };
}

function policy(argument: string): Slash {
  if (argument === "") {
    return { type: "show.policy" };
  }
  const space = argument.indexOf(" ");
  const verb = space === -1 ? argument : argument.slice(0, space);
  const rest = space === -1 ? "" : argument.slice(space + 1).trim();
  if (verb === "rm") {
    if (rest === "") {
      throw new SlashError(USAGE);
    }
    return { type: "policy.remove", rule_id: rest };
  }
  if (verb !== "allow" && verb !== "ask" && verb !== "deny") {
    throw new SlashError(USAGE);
  }
  const split = rest.indexOf(" ");
  const tool = split === -1 ? rest : rest.slice(0, split);
  const pattern = split === -1 ? "" : rest.slice(split + 1).trim();
  if (tool === "" || pattern === "") {
    throw new SlashError(USAGE);
  }
  return { type: "policy.add", tool, pattern, action: verb };
}
