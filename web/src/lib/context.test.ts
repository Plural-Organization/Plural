import { describe, expect, test } from "vitest";
import { contextText } from "./context";

describe("/context", () => {
  test("lists the parts largest first and flags a cache miss", () => {
    const text = contextText({
      tokens: 40_000,
      window: 200_000,
      compact_at: 0.9,
      hit: 0.2,
      parts: [
        { kind: "system", name: null, tokens: 2_000 },
        { kind: "tool_results", name: "read", tokens: 30_000 },
      ],
    });
    expect(text.split("\n")).toEqual([
      "context",
      "  read results  30K  15%",
      "  system prompt  2K  1%",
      "  total 40K of 200K, summarized at 90%",
      "  latest request 20% cached, most of it sent at full price",
    ]);
  });

  test("says so before the first request", () => {
    expect(contextText(null)).toBe("the agent has not been asked anything yet");
  });
});
