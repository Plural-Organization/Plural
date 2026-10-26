import { truncate } from "./wrap";

export type ToolKind = "bash" | "read" | "edit" | "write" | "list" | "search" | "other";

const KINDS: Record<string, ToolKind> = {
  bash: "bash",
  read: "read",
  edit: "edit",
  write: "write",
  ls: "list",
  glob: "search",
  grep: "search",
};

const NAMES: Record<string, string> = {
  bash: "Bash",
  read: "Read",
  edit: "Edit",
  write: "Write",
  ls: "List",
  glob: "Glob",
  grep: "Search",
};

export interface ToolFacts {
  name: string;
  status: "running" | "ok" | "failed";
  subject: string;
  output: string;
  diff: string | null;
  live: string;
  tool: string;
}

export function kindOf(tool: string): ToolKind {
  return KINDS[tool] ?? "other";
}

export function displayName(tool: string): string {
  return NAMES[tool] ?? tool.charAt(0).toUpperCase() + tool.slice(1);
}

export function diffStats(diff: string): { added: number; removed: number } {
  let added = 0;
  let removed = 0;
  for (const line of diff.split("\n")) {
    if (line.startsWith("+") && !line.startsWith("+++")) {
      added += 1;
    } else if (line.startsWith("-") && !line.startsWith("---")) {
      removed += 1;
    }
  }
  return { added, removed };
}

const EXIT = /\n?\[exit (-?\d+)\]\s*$/;

export function exitCode(output: string): number | null {
  const match = EXIT.exec(output);
  return match ? Number(match[1]) : null;
}

export function bodyOf(output: string): string {
  return output.replace(EXIT, "").replace(/\s+$/, "");
}

export function bodyLines(output: string): string[] {
  const body = bodyOf(output);
  return body === "" ? [] : body.split("\n");
}

export function lastLine(text: string): string {
  const lines = text.split("\n").map((line) => line.trim()).filter((line) => line !== "");
  return lines.at(-1) ?? "";
}

function count(n: number, singular: string, plural = `${singular}s`): string {
  return `${n} ${n === 1 ? singular : plural}`;
}

export function metaOf(facts: ToolFacts): string {
  const kind = kindOf(facts.tool);
  if (facts.status === "running") {
    return "";
  }
  if (facts.diff !== null && (kind === "edit" || kind === "write")) {
    const { added, removed } = diffStats(facts.diff);
    return added === 0 && removed === 0 ? "no changes" : `+${added} −${removed}`;
  }
  const lines = bodyLines(facts.output);
  if (facts.status === "failed") {
    const code = exitCode(facts.output);
    if (code !== null) {
      return `exit ${code}`;
    }
    return truncate(lines[0] ?? "failed", 40);
  }
  switch (kind) {
    case "bash":
      return lines.length === 0 ? "no output" : count(lines.length, "line");
    case "read":
      return count(lines.length, "line");
    case "list":
      return count(lines.length, "entry", "entries");
    case "search":
      return lines.length === 0 ? "no matches" : count(lines.length, "match", "matches");
    default:
      return lines.length === 0 ? "" : count(lines.length, "line");
  }
}

export function oneLine(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}
