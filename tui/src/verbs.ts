export const VERBS: readonly (readonly [string, string])[] = [
  ["Cogitating", "Cogitated"],
  ["Vibing", "Vibed"],
  ["Pondering", "Pondered"],
  ["Noodling", "Noodled"],
  ["Brewing", "Brewed"],
  ["Scheming", "Schemed"],
  ["Percolating", "Percolated"],
  ["Ruminating", "Ruminated"],
  ["Conjuring", "Conjured"],
  ["Tinkering", "Tinkered"],
  ["Marinating", "Marinated"],
  ["Musing", "Mused"],
  ["Simmering", "Simmered"],
  ["Churning", "Churned"],
  ["Wrangling", "Wrangled"],
  ["Spelunking", "Spelunked"],
];

export const VERB_MS = 4000;

export function firstVerb(random: () => number = Math.random): number {
  return Math.floor(random() * VERBS.length);
}

export function verbAt(first: number, ms: number): number {
  return (first + Math.floor(ms / VERB_MS)) % VERBS.length;
}

export function took(ms: number): string {
  const seconds = Math.max(1, Math.round(ms / 1000));
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

export function doneText(first: number, ms: number, at: Date): string {
  const clock = at.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  return `${VERBS[verbAt(first, ms)]?.[1] ?? "Worked"} for ${took(ms)} · done ${clock}`;
}
