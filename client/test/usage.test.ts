import { describe, expect, test } from "vitest";
import { cacheHit, cacheHitLabel, contextLines, missedCache } from "../src";
import type { ContextView } from "../src/protocol";

describe("cache hits", () => {
  test("are the share of the prompt read from the cache", () => {
    const usage = { input_tokens: 10, cache_read_tokens: 80, cache_write_tokens: 10 };
    expect(cacheHit(usage)).toBe(0.8);
    expect(cacheHitLabel(usage)).toBe("80% cached");
  });

  test("are not reported when nothing was sent", () => {
    const none = { input_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0 };
    expect(cacheHit(none)).toBeNull();
    expect(cacheHitLabel(none)).toBe("");
  });
});

describe("the context breakdown", () => {
  const context: ContextView = {
    tokens: 40_000,
    window: 200_000,
    compact_at: 0.9,
    hit: 0.2,
    parts: [
      { kind: "system", name: null, tokens: 2_000 },
      { kind: "tool_results", name: "read", tokens: 30_000 },
      { kind: "messages", name: null, tokens: 8_000 },
    ],
  };

  test("lists the largest part first, tool results by tool", () => {
    expect(contextLines(context)).toEqual([
      { label: "read results", tokens: 30_000, share: 0.15 },
      { label: "messages", tokens: 8_000, share: 0.04 },
      { label: "system prompt", tokens: 2_000, share: 0.01 },
    ]);
  });

  test("flags a large request that mostly missed the cache", () => {
    expect(missedCache(context)).toBe(true);
    expect(missedCache({ ...context, hit: 0.9 })).toBe(false);
    expect(missedCache({ ...context, tokens: 5_000 })).toBe(false);
    expect(missedCache({ ...context, hit: null })).toBe(false);
  });
});
