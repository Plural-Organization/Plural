import type { DiffLine } from "./diff";

export interface Change {
  from: number;
  to: number;
}

function common(a: string, b: string): { head: number; tail: number } {
  const limit = Math.min(a.length, b.length);
  let head = 0;
  while (head < limit && a[head] === b[head]) {
    head += 1;
  }
  let tail = 0;
  while (tail < limit - head && a[a.length - 1 - tail] === b[b.length - 1 - tail]) {
    tail += 1;
  }
  return { head, tail };
}

export function changedSpans(rows: DiffLine[]): Map<number, Change> {
  const spans = new Map<number, Change>();
  let index = 0;
  while (index < rows.length) {
    if (rows[index]?.kind !== "del") {
      index += 1;
      continue;
    }
    const removed: number[] = [];
    while (rows[index]?.kind === "del") {
      removed.push(index);
      index += 1;
    }
    const added: number[] = [];
    while (rows[index]?.kind === "add") {
      added.push(index);
      index += 1;
    }
    const pairs = Math.min(removed.length, added.length);
    for (let pair = 0; pair < pairs; pair += 1) {
      const before = rows[removed[pair] as number] as DiffLine;
      const after = rows[added[pair] as number] as DiffLine;
      const { head, tail } = common(before.text, after.text);
      const kept = head + tail;
      if (kept === 0 || (kept >= before.text.length && kept >= after.text.length)) {
        continue;
      }
      spans.set(removed[pair] as number, { from: head, to: before.text.length - tail });
      spans.set(added[pair] as number, { from: head, to: after.text.length - tail });
    }
  }
  return spans;
}
