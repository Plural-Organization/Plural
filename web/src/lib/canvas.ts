import type { FeedItem } from "@plural/client";
import { blocks } from "../components/feed/Markdown";

// A code block this long, or a reply this long with headings, opens in the canvas instead of the feed.
export const CODE_LINES = 12;
export const DOCUMENT_CHARS = 1200;

export interface CanvasDoc {
  id: string;
  title: string;
  kind: "code" | "text";
  lang: string;
  text: string;
  live: boolean;
  // Set for a file the agent wrote; the download keeps its name.
  path?: string;
}

type ToolItem = Extract<FeedItem, { kind: "tool" }>;

export function docTitle(text: string): string {
  const heading = blocks(text).find((block) => block.kind === "heading");
  return heading?.kind === "heading" ? heading.text : "Document";
}

// A write the agent made, or is about to make, with the file it fills.
export function writtenFile(item: ToolItem): { path: string; content: string } | null {
  const { path, content } = item.call.args;
  return item.call.name === "write" && item.status !== "failed" && typeof path === "string" && typeof content === "string"
    ? { path, content }
    : null;
}

export function isDocument(text: string): boolean {
  return text.length >= DOCUMENT_CHARS && blocks(text).filter((block) => block.kind === "heading").length >= 2;
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
    return doc.path.split("/").pop() || "file.txt";
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
        docs.push({ id: item.id, title: docTitle(item.text), kind: "text", lang: "md", text: item.text, live: item.streaming });
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
          });
        }
        index += 1;
      });
    } else if (item.kind === "tool") {
      const file = writtenFile(item);
      if (file !== null) {
        const lang = langOf(file.path);
        docs.push({ id: item.id, title: file.path, kind: lang === "md" ? "text" : "code", lang, text: file.content, live: false, path: file.path });
      }
    }
  }
  return docs;
}
