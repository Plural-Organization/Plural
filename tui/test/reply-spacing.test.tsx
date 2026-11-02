import { describe, expect, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { useRenderer } from "@opentui/react";
import { useMemo } from "react";
import { codeBlockRenderer } from "../src/code";
import { createSyntaxStyle } from "../src/syntax";

function Reply({ text }: { text: string }) {
  const renderer = useRenderer();
  const syntaxStyle = useMemo(() => createSyntaxStyle(renderer as never), [renderer]);
  const renderNode = useMemo(() => codeBlockRenderer(renderer as never), [renderer]);
  return <markdown content={text} syntaxStyle={syntaxStyle} renderNode={renderNode} />;
}

// Markdown lays itself out over several frames, so read it once it has stopped changing.
async function settled(text: string): Promise<string[]> {
  const setup = await testRender(<Reply text={text} />, { width: 50, height: 26 });
  let out = "";
  let same = 0;
  const deadline = Date.now() + 8000;
  while (Date.now() < deadline && same < 5) {
    await setup.renderOnce();
    const next = setup.captureCharFrame();
    same = next === out && next.trim() !== "" ? same + 1 : 0;
    out = next;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  setup.renderer.destroy();
  return out.split("\n").map((line) => line.trimEnd());
}

function after(lines: string[], text: string): string | undefined {
  return lines[lines.findIndex((line) => line.includes(text)) + 1];
}

describe("spacing in the agent's replies", () => {
  test("the code renderer draws code blocks only, so the rest stays one block", () => {
    expect((codeBlockRenderer({} as never) as { codeBlockOnly?: boolean }).codeBlockOnly).toBe(true);
  });

  test("a blank line between paragraphs and around a list is kept", async () => {
    const lines = await settled("First paragraph.\n\nSecond paragraph.\n\n- one\n- two\n\nLast paragraph.");
    expect(after(lines, "First paragraph.")).toBe("");
    expect(after(lines, "Second paragraph.")).toBe("");
    expect(after(lines, "- two")).toBe("");
    expect(lines.some((line) => line.includes("Last paragraph."))).toBe(true);
  });

  test("lines without a blank line between them stay together", async () => {
    const lines = await settled("line one\nline two\n- one\n- two");
    expect(after(lines, "line one")).toContain("line two");
    expect(after(lines, "- one")).toContain("- two");
  });

  test("code blocks keep their frame and copy button", async () => {
    const lines = await settled("Before.\n\n```ts\nconst a = 1;\n```\n\nAfter.");
    expect(lines.some((line) => line.includes("╭─ts"))).toBe(true);
    expect(lines.some((line) => line.includes("copy"))).toBe(true);
  });
});
