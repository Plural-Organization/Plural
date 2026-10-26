import { describe, expect, test } from "bun:test";
import { gutterWidth, languageFor, parseDiff } from "../src/lib/diff";
import { bodyLines, diffStats, exitCode, metaOf } from "../src/lib/tools";

const DIFF = [
  "--- a/calc.py",
  "+++ b/calc.py",
  "@@ -1,4 +1,5 @@",
  " import math",
  " ",
  " def add(a, b):",
  "-    return a - b",
  "+    \"\"\"Sum.\"\"\"",
  "+    return a + b",
  "@@ -20,2 +21,2 @@",
  " x = 1",
  "-y = 2",
  "+y = 3",
  "\\ No newline at end of file",
  "",
].join("\n");

describe("diff parsing", () => {
  test("numbers lines on both sides and drops file headers", () => {
    const lines = parseDiff(DIFF);
    expect(lines.map((line) => [line.kind, line.oldNo, line.newNo, line.text])).toEqual([
      ["ctx", 1, 1, "import math"],
      ["ctx", 2, 2, ""],
      ["ctx", 3, 3, "def add(a, b):"],
      ["del", 4, null, "    return a - b"],
      ["add", null, 4, '    """Sum."""'],
      ["add", null, 5, "    return a + b"],
      ["gap", null, null, ""],
      ["ctx", 20, 21, "x = 1"],
      ["del", 21, null, "y = 2"],
      ["add", null, 22, "y = 3"],
    ]);
  });

  test("a broken or truncated diff never throws", () => {
    expect(parseDiff("")).toEqual([]);
    expect(parseDiff("not a diff at all")).toEqual([]);
    expect(parseDiff("@@ -1,9 +1,9 @@\n-a\n+b")).toHaveLength(2);
  });

  test("the gutter is as wide as the largest number", () => {
    expect(gutterWidth(parseDiff(DIFF))).toBe(2);
    expect(gutterWidth([])).toBe(1);
  });

  test("the language comes from the file extension", () => {
    expect(languageFor("src/calc.py")).toBe("python");
    expect(languageFor("a/b/App.TSX")).toBe("typescript");
    expect(languageFor("Makefile")).toBeUndefined();
    expect(languageFor("notes.unknown")).toBeUndefined();
  });
});

describe("tool summaries", () => {
  const facts = (extra: Partial<Parameters<typeof metaOf>[0]>) => ({
    name: "Bash",
    tool: "bash",
    status: "ok" as const,
    subject: "x",
    output: "",
    diff: null,
    live: "",
    ...extra,
  });

  test("counts added and removed lines", () => {
    expect(diffStats(DIFF)).toEqual({ added: 3, removed: 2 });
    expect(metaOf(facts({ tool: "edit", diff: DIFF }))).toBe("+3 −2");
    expect(metaOf(facts({ tool: "edit", diff: "" }))).toBe("no changes");
  });

  test("a command says how much it printed or how it failed", () => {
    expect(metaOf(facts({ output: "a\nb\n[exit 0]" }))).toBe("2 lines");
    expect(metaOf(facts({ output: "[exit 0]" }))).toBe("no output");
    expect(metaOf(facts({ status: "failed", output: "boom\n[exit 2]" }))).toBe("exit 2");
    expect(metaOf(facts({ status: "failed", output: "Denied: nope" }))).toBe("Denied: nope");
    expect(metaOf(facts({ status: "running" }))).toBe("");
  });

  test("other tools are counted in their own words", () => {
    expect(metaOf(facts({ tool: "read", output: "one\ntwo\nthree" }))).toBe("3 lines");
    expect(metaOf(facts({ tool: "ls", output: "a\nb" }))).toBe("2 entries");
    expect(metaOf(facts({ tool: "grep", output: "" }))).toBe("no matches");
    expect(metaOf(facts({ tool: "grep", output: "a.py:1:x" }))).toBe("1 match");
  });

  test("the exit marker is read and stripped from the body", () => {
    expect(exitCode("out\n[exit 3]")).toBe(3);
    expect(exitCode("out")).toBeNull();
    expect(bodyLines("a\nb\n[exit 0]")).toEqual(["a", "b"]);
    expect(bodyLines("[exit 0]")).toEqual([]);
  });
});
