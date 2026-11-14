// The messages this person sent, newest first, for the arrow keys in the composer, as in a shell or an agent's terminal.
// Kept in this browser only, across rooms and reloads, and capped.
export const MAX_HISTORY = 100;
const KEY = "plural.history";

export function remember(entries: string[], text: string): string[] {
  const sent = text.trim();
  return sent === "" ? entries : [sent, ...entries.filter((entry) => entry !== sent)].slice(0, MAX_HISTORY);
}

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

// Where the person is in the list: -1 is the line they were typing, 0 the last message sent, 1 the one before it.
export interface Browsing {
  position: number;
  // What was in the box before the first step back, so stepping forward past the newest message brings it back.
  draft: string;
}

export const NOT_BROWSING: Browsing = { position: -1, draft: "" };

export interface Step {
  browsing: Browsing;
  // The new content of the box, or null when the key changes nothing (the end of the list).
  value: string | null;
}

export function older(entries: string[], browsing: Browsing, current: string): Step {
  const next = browsing.position + 1;
  if (next >= entries.length) {
    return { browsing, value: null };
  }
  const draft = browsing.position === -1 ? current : browsing.draft;
  return { browsing: { position: next, draft }, value: entries[next] ?? "" };
}

export function newer(entries: string[], browsing: Browsing): Step {
  if (browsing.position === -1) {
    return { browsing, value: null };
  }
  const next = browsing.position - 1;
  return { browsing: { position: next, draft: browsing.draft }, value: next === -1 ? browsing.draft : (entries[next] ?? "") };
}
