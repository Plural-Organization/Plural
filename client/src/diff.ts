export type DiffKind = "add" | "del" | "ctx" | "gap";

export interface DiffLine {
  kind: DiffKind;
  oldNo: number | null;
  newNo: number | null;
  text: string;
}

const HUNK = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/;

export function parseDiff(diff: string): DiffLine[] {
  const lines: DiffLine[] = [];
  let oldNo = 0;
  let newNo = 0;
  let inside = false;
  let hunks = 0;
  for (const raw of diff.replace(/\n$/, "").split("\n")) {
    const header = HUNK.exec(raw);
    if (header) {
      oldNo = Number(header[1]);
      newNo = Number(header[2]);
      if (hunks > 0) {
        lines.push({ kind: "gap", oldNo: null, newNo: null, text: "" });
      }
      hunks += 1;
      inside = true;
      continue;
    }
    if (!inside || raw.startsWith("\\")) {
      continue;
    }
    if (raw.startsWith("+")) {
      lines.push({ kind: "add", oldNo: null, newNo, text: raw.slice(1) });
      newNo += 1;
    } else if (raw.startsWith("-")) {
      lines.push({ kind: "del", oldNo, newNo: null, text: raw.slice(1) });
      oldNo += 1;
    } else {
      lines.push({ kind: "ctx", oldNo, newNo, text: raw.startsWith(" ") ? raw.slice(1) : raw });
      oldNo += 1;
      newNo += 1;
    }
  }
  return lines;
}

const LANGUAGES: Record<string, string> = {
  py: "python",
  ts: "typescript",
  tsx: "typescript",
  js: "javascript",
  jsx: "javascript",
  mjs: "javascript",
  json: "json",
  sh: "bash",
  bash: "bash",
  zsh: "bash",
  yml: "yaml",
  yaml: "yaml",
  md: "markdown",
  rs: "rust",
  go: "go",
  sql: "sql",
  css: "css",
  html: "xml",
  xml: "xml",
  diff: "diff",
};

export function languageFor(path: string): string | undefined {
  const extension = path.split(".").pop()?.toLowerCase();
  return extension && extension !== path.toLowerCase() ? LANGUAGES[extension] : undefined;
}

export function gutterWidth(lines: DiffLine[]): number {
  let widest = 1;
  for (const line of lines) {
    widest = Math.max(widest, String(line.newNo ?? line.oldNo ?? 0).length);
  }
  return widest;
}
