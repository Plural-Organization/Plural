import { MAX_HISTORY } from "@plural/client";

// The messages this person sent, kept in this browser only, across rooms and reloads. What is kept and how the arrow
// keys walk through it is decided in @plural/client, the same as in the terminal.
const KEY = "plural.history";

export function loadHistory(): string[] {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(raw) ? raw.filter((entry): entry is string => typeof entry === "string" && entry !== "").slice(0, MAX_HISTORY) : [];
  } catch {
    return [];
  }
}

export function saveHistory(entries: string[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(entries));
  } catch {
    // Without storage the history lasts until the page is closed.
  }
}
