import type { FeedItem } from "@plural/client";
import { blocks } from "../components/feed/Markdown";

// A code block this long opens in the canvas instead of the feed, and so does a reply that reads as a
// document: a titled piece of a few paragraphs, like an essay, or a long one with sections.
export const CODE_LINES = 12;
export const TITLED_CHARS = 700;
export const DOCUMENT_CHARS = 1200;

const BOLD_LINE = /^\*\*([^*\n]+)\*\*$/;

// The title a reply opens with: a heading, or a line that is bold on its own.
function leadingTitle(text: string): string | null {
  const first = blocks(text)[0];
  if (first?.kind === "heading") {
    return first.text;
  }
  const line = first?.kind === "paragraph" ? first.text.split("\n")[0]!.trim() : "";
  return BOLD_LINE.exec(line)?.[1]?.trim() ?? null;
}

export interface CanvasDoc {
  id: string;
  title: string;
  kind: "code" | "text" | "diff";
  lang: string;
  text: string;
  live: boolean;
  // Opens by itself for everyone when it appears; a diff waits for a click, the feed already shows it.
  auto: boolean;
  // Set for a file the agent wrote or edited; the download keeps its name.
  path?: string;
}

type ToolItem = Extract<FeedItem, { kind: "tool" }>;

export function docTitle(text: string): string {
  const heading = blocks(text).find((block) => block.kind === "heading");
  return leadingTitle(text) ?? (heading?.kind === "heading" ? heading.text : "Document");
}

// What a tool call puts in the canvas: the diff of a finished edit, or the file a write fills.
export function toolDoc(item: ToolItem): CanvasDoc | null {
  const path = typeof item.call.args.path === "string" ? item.call.args.path : item.call.subject;
  if (item.status === "ok" && item.diff !== null) {
    return { id: item.id, title: path, kind: "diff", lang: "diff", text: item.diff, live: false, auto: false, path };
  }
  const file = writtenFile(item);
  if (file === null) {
    return null;
  }
  const lang = langOf(file.path);
  return { id: item.id, title: file.path, kind: lang === "md" ? "text" : "code", lang, text: file.content, live: false, auto: false, path: file.path };
}

// A write the agent made, or is about to make, with the file it fills.
export function writtenFile(item: ToolItem): { path: string; content: string } | null {
  const { path, content } = item.call.args;
  return item.call.name === "write" && item.status !== "failed" && typeof path === "string" && typeof content === "string"
    ? { path, content }
    : null;
}

export function isDocument(text: string): boolean {
  const parsed = blocks(text);
  if (text.length >= TITLED_CHARS && leadingTitle(text) !== null && parsed.filter((block) => block.kind === "paragraph").length >= 3) {
    return true;
  }
  return text.length >= DOCUMENT_CHARS && parsed.filter((block) => block.kind === "heading").length >= 2;
}

export function lineCount(text: string): number {
  return text === "" ? 0 : text.split("\n").length;
}

const EXTENSIONS: Record<string, string> = {
  ts: "ts", tsx: "tsx", js: "js", jsx: "jsx", py: "py", rs: "rs", go: "go", rb: "rb", sh: "sh", bash: "sh",
  json: "json", yaml: "yaml", yml: "yaml", toml: "toml", html: "html", css: "css", sql: "sql", md: "md", markdown: "md",
};

export function langOf(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  return ext === path.toLowerCase() ? "" : ext;
}

export function fileName(doc: CanvasDoc): string {
  if (doc.path !== undefined) {
    const name = doc.path.split("/").pop() || "file.txt";
    return doc.kind === "diff" ? `${name}.diff` : name;
  }
  if (doc.kind === "text") {
    return `${doc.title.replace(/[^\p{L}\p{N}]+/gu, "-").replace(/^-|-$/g, "").toLowerCase() || "document"}.md`;
  }
  return `snippet.${EXTENSIONS[doc.lang.toLowerCase()] ?? "txt"}`;
}

// Every client reads the same feed, so every participant gets the same documents in the same order.
export function canvasDocs(items: FeedItem[]): CanvasDoc[] {
  const docs: CanvasDoc[] = [];
  for (const item of items) {
    if (item.kind === "assistant" && item.text !== "") {
      const parsed = blocks(item.text);
      if (isDocument(item.text)) {
        docs.push({ id: item.id, title: docTitle(item.text), kind: "text", lang: "md", text: item.text, live: item.streaming, auto: true });
        continue;
      }
      let index = 0;
      parsed.forEach((block, position) => {
        if (block.kind !== "code") {
          return;
        }
        if (lineCount(block.text) >= CODE_LINES) {
          docs.push({
            id: `${item.id}:${index}`,
            title: block.lang || "code",
            kind: "code",
            lang: block.lang,
            text: block.text,
            live: item.streaming && position === parsed.length - 1,
            auto: true,
          });
        }
        index += 1;
      });
    } else if (item.kind === "tool") {
      const doc = toolDoc(item);
      if (doc !== null) {
        docs.push(doc);
      }
    }
  }
  return docs;
}
