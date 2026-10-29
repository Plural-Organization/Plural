import { expect, test } from "vitest";
import type { FeedItem } from "@plural/client";
import { canvasDocs, docTitle, fileName } from "./canvas";

const code = (lines: number) => Array.from({ length: lines }, (_, index) => `line ${index + 1}`).join("\n");
const reply = (text: string, streaming = false): FeedItem => ({ kind: "assistant", id: "m1", text, streaming });

test("a long code block opens in the canvas and a short one stays in the feed", () => {
  const docs = canvasDocs([reply(`Short:\n\`\`\`sh\nls\n\`\`\`\nLong:\n\`\`\`ts\n${code(14)}\n\`\`\``)]);
  expect(docs).toEqual([{ id: "m1:1", title: "ts", kind: "code", lang: "ts", text: code(14), live: false, auto: true }]);
});

test("a code block that is still streaming is live", () => {
  const [doc] = canvasDocs([reply(`\`\`\`py\n${code(13)}`, true)]);
  expect(doc).toMatchObject({ id: "m1:0", live: true });
});

test("a long reply with headings is one document named by its first heading", () => {
  const text = `# Release plan\n\n${"Some words. ".repeat(120)}\n\n## Risks\n\n\`\`\`ts\n${code(20)}\n\`\`\``;
  const docs = canvasDocs([reply(text)]);
  expect(docs).toHaveLength(1);
  expect(docs[0]).toMatchObject({ id: "m1", title: "Release plan", kind: "text" });
  expect(fileName(docs[0]!)).toBe("release-plan.md");
  expect(fileName({ ...docs[0]!, title: "Release 1.2 / notes" })).toBe("release-1-2-notes.md");
});

test("a written file opens under its path", () => {
  const tool: FeedItem = {
    kind: "tool",
    id: "t1",
    call: { id: "c1", name: "write", subject: "src/app.ts", risk: "write", args: { path: "src/app.ts", content: "export {};" } },
    status: "ok",
    output: "",
    diff: null,
    live: "",
  };
  const [doc] = canvasDocs([tool]);
  expect(doc).toMatchObject({ id: "t1", title: "src/app.ts", kind: "code", lang: "ts" });
  expect(fileName({ ...doc!, path: "Makefile" })).toBe("Makefile");
  expect(canvasDocs([{ ...tool, status: "failed" }])).toEqual([]);
  expect(fileName(doc!)).toBe("app.ts");
});

test("a comment in a code block is not taken for the title", () => {
  expect(docTitle("```sh\n# install\n```\n## Setup\ntext")).toBe("Setup");
});

test("a titled essay of a few paragraphs is a document, a long plain answer is not", () => {
  const paragraph = "Такие слова помогают справиться со смущением и снижают важность разговора. ".repeat(3);
  const essay = `**Почему мы говорим так**\n\n${paragraph}\n\n${paragraph}\n\n${paragraph}\n\n${paragraph}`;
  const [doc] = canvasDocs([reply(essay)]);
  expect(doc).toMatchObject({ id: "m1", kind: "text", title: "Почему мы говорим так" });
  expect(canvasDocs([reply(`${paragraph}\n\n${paragraph}\n\n${paragraph}\n\n${paragraph}`)])).toEqual([]);
});

test("a finished edit opens as a diff that waits for a click", () => {
  const edit: FeedItem = {
    kind: "tool",
    id: "t2",
    call: { id: "c2", name: "edit", subject: "src/app.ts", risk: "write", args: { path: "src/app.ts" } },
    status: "ok",
    output: "",
    diff: "@@ -1 +1 @@\n-a\n+b\n",
    live: "",
  };
  expect(canvasDocs([edit])).toEqual([expect.objectContaining({ id: "t2", kind: "diff", title: "src/app.ts", auto: false })]);
});
