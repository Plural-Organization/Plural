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
  }
}

export function findInFeed(items: readonly FeedItem[], query: string): string[] {
  const terms = query.toLowerCase().split(/\s+/).filter((term) => term !== "");
  if (terms.length === 0) {
    return [];
  }
  return items
    .filter((item) => {
      const text = searchableText(item).toLowerCase();
      return terms.every((term) => text.includes(term));
    })
    .map((item) => item.id);
}

export function stepMatch(count: number, current: number, direction: 1 | -1): number {
  return count === 0 ? 0 : (current + direction + count) % count;
}
