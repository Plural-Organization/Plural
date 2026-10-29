import type { FeedItem } from "./feed";

export function searchableText(item: FeedItem): string {
  switch (item.kind) {
    case "banner":
      return "";
    case "user":
      return [item.name, item.text, ...(item.files ?? [])].join("\n");
    case "chat":
      return [item.name, item.toName ?? "", item.text].join("\n");
    case "assistant":
      return item.text;
    case "tool":
      return [item.call.name, item.call.subject, item.output, item.diff ?? "", item.live].join("\n");
    case "notice":
      return item.text;
    case "briefing":
      return `${item.from}\n${item.text}`;
  }
}

const KINDS: Record<string, (item: FeedItem) => boolean> = {
  failed: (item) => item.kind === "tool" && item.status === "failed",
  running: (item) => item.kind === "tool" && item.status === "running",
  tool: (item) => item.kind === "tool",
  prompt: (item) => item.kind === "user",
  chat: (item) => item.kind === "chat",
  reply: (item) => item.kind === "assistant",
  notice: (item) => item.kind === "notice",
  briefing: (item) => item.kind === "briefing",
};

export const SEARCH_FILTERS = Object.keys(KINDS);

interface Query {
  words: string[];
  filters: ((item: FeedItem) => boolean)[];
  authors: string[];
}

function parse(query: string): Query {
  const parsed: Query = { words: [], filters: [], authors: [] };
  for (const term of query.toLowerCase().split(/\s+/).filter((part) => part !== "")) {
    const filter = term.startsWith("is:") ? KINDS[term.slice(3)] : undefined;
    if (filter !== undefined) {
      parsed.filters.push(filter);
    } else if (term.startsWith("by:") && term.length > 3) {
      parsed.authors.push(term.slice(3));
    } else {
      parsed.words.push(term);
    }
  }
  return parsed;
}

function byAuthor(item: FeedItem, authors: string[]): boolean {
  const name = item.kind === "user" || item.kind === "chat" ? item.name.toLowerCase() : null;
  return name !== null && authors.every((author) => name.includes(author));
}

export function findInFeed(items: readonly FeedItem[], query: string): string[] {
  const { words, filters, authors } = parse(query);
  if (words.length === 0 && filters.length === 0 && authors.length === 0) {
    return [];
  }
  return items
    .filter((item) => {
      if (item.kind === "banner" || !filters.every((filter) => filter(item)) || !(authors.length === 0 || byAuthor(item, authors))) {
        return false;
      }
      const text = searchableText(item).toLowerCase();
      return words.every((word) => text.includes(word));
    })
    .map((item) => item.id);
}

export function matchPreview(item: FeedItem, query: string, width: number): string {
  const { words } = parse(query);
  const lines = searchableText(item).split("\n");
  const line = lines.find((entry) => words.some((word) => entry.toLowerCase().includes(word))) ?? lines.find((entry) => entry.trim() !== "") ?? "";
  const flat = line.replace(/\s+/g, " ").trim();
  const at = words.length === 0 ? 0 : Math.max(0, flat.toLowerCase().indexOf(words.find((word) => flat.toLowerCase().includes(word)) ?? ""));
  const start = Math.max(0, at - Math.floor(width / 3));
  const slice = flat.slice(start, start + width);
  return `${start > 0 ? "…" : ""}${slice}${start + width < flat.length ? "…" : ""}`;
}

export function stepMatch(count: number, current: number, direction: 1 | -1): number {
  return count === 0 ? 0 : (current + direction + count) % count;
}

export interface Collapsed {
  text: string;
  hidden: number;
}

export function collapseText(text: string, limit: number): Collapsed {
  const lines = text.split("\n");
  if (lines.length <= limit) {
    return { text, hidden: 0 };
  }
  const kept = lines.slice(0, limit);
  const open = kept.filter((line) => /^\s*(```|~~~)/.test(line)).length % 2 === 1;
  return { text: `${kept.join("\n")}${open ? "\n```" : ""}`, hidden: lines.length - limit };
}
