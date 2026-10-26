import { describe, expect, test } from "bun:test";
import { chunks } from "../src/code";
import { highlightLines } from "../src/lib/highlight";
import { theme } from "../src/theme";

describe("highlighting", () => {
  test("keywords, strings and comments get their own colours", () => {
    const [line] = highlightLines('def f(): return "x"  # note', "python");
    const colours = new Map(line?.map((span) => [span.text.trim(), span.color]));
    expect(colours.get("def")).toBe(theme.code);
    expect(colours.get('"x"')).toBe(theme.ok);
    expect(colours.get("# note")).toBe(theme.dim);
  });

  test("language aliases resolve and unknown languages stay plain", () => {
    expect(highlightLines("const a = 1", "ts")[0]?.some((span) => span.color !== undefined)).toBe(true);
    expect(highlightLines("whatever 1", "klingon")).toEqual([[{ text: "whatever 1" }]]);
    expect(highlightLines("plain", undefined)).toEqual([[{ text: "plain" }]]);
  });

  test("lines survive highlighting, blank lines included", () => {
    expect(highlightLines("a = 1\n\nb = 2", "python").map((spans) => spans.map((span) => span.text).join(""))).toEqual([
      "a = 1",
      "",
      "b = 2",
    ]);
  });

  test("chunks keep the text intact with newlines between lines", () => {
    const text = chunks("x = 1\ny = 2\n", "python")
      .map((chunk) => chunk.text)
      .join("");
    expect(text).toBe("x = 1\ny = 2");
  });
});

describe("diff blocks in replies", () => {
  test("added and removed lines get a tinted background, the rest does not", () => {
    const parts = chunks("@@ -1 +1 @@\n-old line\n+new line\n context", "diff");
    const tinted = (needle: string) => parts.find((chunk) => chunk.text.includes(needle))?.bg;
    expect(tinted("old line")).toBeDefined();
    expect(tinted("new line")).toBeDefined();
    expect(tinted("old line")).not.toEqual(tinted("new line"));
    expect(tinted("context")).toBeUndefined();
    expect(tinted("@@")).toBeUndefined();
  });

  test("other languages are never tinted", () => {
    expect(chunks("+x\n-y", "python").every((chunk) => chunk.bg === undefined)).toBe(true);
  });
});
