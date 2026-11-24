import { chmodSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { MAX_HISTORY } from "@plural/client";
import { dataDir } from "./paths";

// The prompts this person sent, kept on this computer for the up key in the next session, as a shell keeps its history.
// One list for every room, newest first; readable by its owner only, since a prompt can hold anything.
// Very long prompts (a pasted file) stay in memory for the session and are not written down.
const MAX_SAVED_CHARS = 8000;

export function historyPath(environment: Record<string, string | undefined> = process.env): string {
  return join(dataDir(environment), "history.json");
}

export function loadHistory(path: string = historyPath()): string[] {
  try {
    const raw: unknown = JSON.parse(readFileSync(path, "utf8"));
    return Array.isArray(raw) ? raw.filter((entry): entry is string => typeof entry === "string" && entry !== "").slice(0, MAX_HISTORY) : [];
  } catch {
    return [];
  }
}

export function saveHistory(entries: string[], path: string = historyPath()): void {
  try {
    mkdirSync(dirname(path), { recursive: true });
    const temporary = `${path}.tmp`;
    const kept = entries.filter((entry) => entry.length <= MAX_SAVED_CHARS).slice(0, MAX_HISTORY);
    writeFileSync(temporary, `${JSON.stringify(kept)}\n`, { encoding: "utf8", mode: 0o600 });
    chmodSync(temporary, 0o600);
    renameSync(temporary, path);
  } catch {
    return;
  }
}
