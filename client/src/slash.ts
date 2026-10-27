import type { Command, PromptMode } from "./protocol";

const USAGE =
  "usage: /policy | /policy allow|ask|deny <tool> <pattern> | /policy rm <rule id>";
const MODE_USAGE = "usage: /mode open|review";

export class SlashError extends Error {}

const SKILLS_USAGE = "usage: /skills | /skills search <query> | /skills add <owner/repo@skill> [--global] | /skills rm <name>";

const MCP_USAGE =
  "usage: /mcp | /mcp add <name> <command…|url> [--global] | /mcp on|off|restart|rm <name> | /mcp import";

export type Slash = Command | { type: "show.policy" } | { type: "show.skills" } | { type: "show.mcp" };

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
    case "skills":
      return skills(argument);
    case "mcp":
      return mcp(argument);
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

function skills(argument: string): Slash {
  if (argument === "") {
    return { type: "show.skills" };
  }
  const space = argument.indexOf(" ");
  const verb = space === -1 ? argument : argument.slice(0, space);
  const rest = space === -1 ? "" : argument.slice(space + 1).trim();
  if (rest === "") {
    throw new SlashError(SKILLS_USAGE);
  }
  switch (verb) {
    case "search":
      return { type: "skills.search", query: rest };
    case "add": {
      const words = rest.split(/\s+/);
      const global = words.includes("--global");
      const packages = words.filter((word) => word !== "--global");
      if (packages.length !== 1) {
        throw new SlashError(SKILLS_USAGE);
      }
      return { type: "skills.install", package: packages[0]!, scope: global ? "global" : "project" };
    }
    case "rm":
      return { type: "skills.remove", name: rest };
    default:
      throw new SlashError(SKILLS_USAGE);
  }
}

function mcp(argument: string): Slash {
  const words = argument.split(/\s+/).filter(Boolean);
  const [verb, name, ...rest] = words;
  switch (verb) {
    case undefined:
      return { type: "show.mcp" };
    case "import":
      return { type: "mcp.import" };
    case "add": {
      const global = rest.includes("--global");
      const target = rest.filter((word) => word !== "--global");
      if (!name || target.length === 0) {
        throw new SlashError(MCP_USAGE);
      }
      const scope = global ? "global" : "project";
      const first = target[0]!;
      if (/^https?:\/\//.test(first)) {
        return { type: "mcp.add", name, url: first, args: [], command: null, scope };
      }
      return { type: "mcp.add", name, command: first, args: target.slice(1), url: null, scope };
    }
    case "on":
    case "off":
      if (!name) {
        throw new SlashError(MCP_USAGE);
      }
      return { type: "mcp.toggle", name, enabled: verb === "on" };
    case "restart":
      if (!name) {
        throw new SlashError(MCP_USAGE);
      }
      return { type: "mcp.restart", name };
    case "rm":
      if (!name) {
        throw new SlashError(MCP_USAGE);
      }
      return { type: "mcp.remove", name };
    default:
      throw new SlashError(MCP_USAGE);
  }
}
