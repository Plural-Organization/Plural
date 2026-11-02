import { expect, test } from "bun:test";
import { parseDiff } from "../src/lib/diff";
import { changedSpans } from "../src/lib/wordDiff";
import { toolRuns } from "../src/steps";
import type { FeedItem } from "../src/feed";

const diff = ["@@ -1,2 +1,2 @@", " keep", "-const a = old(x);", "+const a = fresh(x);"].join("\n");

test("a replaced line marks only what changed", () => {
  const rows = parseDiff(diff);
  const spans = changedSpans(rows);
  const removed = rows.findIndex((row) => row.kind === "del");
  const added = rows.findIndex((row) => row.kind === "add");
  expect(rows[removed]?.text.slice(spans.get(removed)?.from, spans.get(removed)?.to)).toBe("old");
  expect(rows[added]?.text.slice(spans.get(added)?.from, spans.get(added)?.to)).toBe("fresh");
});

test("a line that changed completely is not marked inside", () => {
  const rows = parseDiff(["@@ -1 +1 @@", "-abc", "+xyz"].join("\n"));
  expect(changedSpans(rows).size).toBe(0);
});

const tool = (id: string, diffText: string | null, status: "ok" | "failed" = "ok"): FeedItem =>
  ({ kind: "tool", id, call: { id, name: "edit", risk: "write", subject: id, args: {} }, status, output: "", diff: diffText, live: "" }) as FeedItem;

test("tools in a row form one run with its totals", () => {
  const items: FeedItem[] = [{ kind: "notice", id: "n", tone: "dim", text: "x" }, tool("a", diff), tool("b", null, "failed"), { kind: "notice", id: "m", tone: "dim", text: "y" }, tool("c", null)];
  const runs = toolRuns(items, () => false, new Set());
  expect(runs.get("a")).toMatchObject({ first: true, last: false, count: 2, added: 1, removed: 1, failed: 1 });
  expect(runs.get("b")).toMatchObject({ first: false, last: true });
  expect(runs.get("c")).toMatchObject({ first: true, last: true, count: 1 });
});

test("a long run keeps the last steps and says how many are folded", () => {
  const items = Array.from({ length: 8 }, (_, index) => tool(`t${index}`, null));
  const folded = toolRuns(items, () => false, new Set());
  expect(folded.get("t0")?.hidden).toBe(true);
  expect(folded.get("t3")).toMatchObject({ hidden: false, first: true, earlier: 3 });
  expect(folded.get("t7")?.last).toBe(true);
  const kept = toolRuns(items, () => false, new Set(["t0"]));
  expect(kept.get("t0")).toMatchObject({ hidden: false, first: true, earlier: 2 });
  const open = toolRuns(items, () => true, new Set());
  expect([...open.values()].some((run) => run.hidden)).toBe(false);
});
