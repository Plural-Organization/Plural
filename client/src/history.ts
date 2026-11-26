// The messages a person sent, newest first, for the arrow keys in the composer, as in a shell or an agent's terminal.
// This is the one place that decides what is kept, where the arrows move and what the list shows, so the browser and
// the terminal behave the same; each keeps the list where it can (local storage, a file) and draws it its own way.
export const MAX_HISTORY = 100;

export function remember(entries: string[], text: string): string[] {
  const sent = text.trim();
  return sent === "" ? entries : [sent, ...entries.filter((entry) => entry !== sent)].slice(0, MAX_HISTORY);
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

// Goes straight to a message the person picked from the list.
export function jump(entries: string[], browsing: Browsing, index: number, current: string): Step {
  if (index < 0 || index >= entries.length) {
    return { browsing, value: null };
  }
  const draft = browsing.position === -1 ? current : browsing.draft;
  return { browsing: { position: index, draft }, value: entries[index] ?? "" };
}

// Leaves the list and gives back the line that was being typed.
export function leave(browsing: Browsing): Step {
  return browsing.position === -1 ? { browsing, value: null } : { browsing: NOT_BROWSING, value: browsing.draft };
}

export interface HistoryRow {
  // Position in the list: 0 is the newest message.
  index: number;
  text: string;
  current: boolean;
}

export interface HistoryView {
  // "At 100 of 100" is the newest message; stepping back counts down, the way an agent's terminal shows it.
  at: number;
  of: number;
  // A few messages around the current one, the oldest first, so the newest sits nearest the box.
  rows: HistoryRow[];
}

export const HISTORY_ROWS = 6;

export function historyView(entries: string[], browsing: Browsing, rows: number = HISTORY_ROWS): HistoryView | null {
  if (browsing.position < 0 || entries.length === 0) {
    return null;
  }
  const position = Math.min(browsing.position, entries.length - 1);
  const first = Math.max(0, Math.min(position - 2, entries.length - rows));
  return {
    at: entries.length - position,
    of: entries.length,
    rows: entries
      .slice(first, first + rows)
      .map((text, offset) => ({ index: first + offset, text, current: first + offset === position }))
      .reverse(),
  };
}
