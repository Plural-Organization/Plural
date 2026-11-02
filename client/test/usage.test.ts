import { describe, expect, test } from "vitest";
import { cacheHit, cacheHitLabel } from "../src";

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
