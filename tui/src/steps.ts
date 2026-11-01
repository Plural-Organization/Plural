import { diffStats } from "./lib/tools";
import type { FeedItem } from "./feed";

export const VISIBLE_STEPS = 5;

export interface Run {
  startId: string;
  first: boolean;
  last: boolean;
  count: number;
  added: number;
  removed: number;
  failed: number;
  hidden: boolean;
  earlier: number;
}

export function toolRuns(items: FeedItem[], isOpen: (startId: string) => boolean, keep: ReadonlySet<string>): Map<string, Run> {
  const runs = new Map<string, Run>();
  let start = 0;
  while (start < items.length) {
    if (items[start]?.kind !== "tool") {
      start += 1;
      continue;
    }
    let end = start;
    while (items[end + 1]?.kind === "tool") {
      end += 1;
    }
    const startId = (items[start] as FeedItem).id;
    const count = end - start + 1;
    let added = 0;
    let removed = 0;
    let failed = 0;
    for (let index = start; index <= end; index += 1) {
      const item = items[index];
      if (item?.kind !== "tool") {
        continue;
      }
      failed += item.status === "failed" ? 1 : 0;
      if (item.diff !== null) {
        const stats = diffStats(item.diff);
        added += stats.added;
        removed += stats.removed;
      }
    }
    const collapsed = count > VISIBLE_STEPS && !isOpen(startId);
    const shown: number[] = [];
    for (let index = start; index <= end; index += 1) {
      const item = items[index] as FeedItem;
      if (!collapsed || index > end - VISIBLE_STEPS || keep.has(item.id)) {
        shown.push(index);
      }
    }
    const earlier = count - shown.length;
    for (let index = start; index <= end; index += 1) {
      const item = items[index] as FeedItem;
      const at = shown.indexOf(index);
      runs.set(item.id, {
        startId,
        first: at === 0,
        last: index === end,
        count,
        added,
        removed,
        failed,
        hidden: at === -1,
        earlier: at === 0 ? earlier : 0,
      });
    }
    start = end + 1;
  }
  return runs;
}
