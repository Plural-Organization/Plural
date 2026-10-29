import {
  BoxRenderable,
  RGBA,
  StyledText,
  TextAttributes,
  TextRenderable,
  type MarkdownOptions,
  type RenderContext,
  type TextChunk,
} from "@opentui/core";
import { highlightLines } from "./lib/highlight";
import { theme } from "./theme";

function tintFor(line: string, language: string | undefined): RGBA | undefined {
  if (language !== "diff" && language !== "patch") {
    return undefined;
  }
  if (line.startsWith("+") && !line.startsWith("+++")) {
    return RGBA.fromHex(theme.addBg);
  }
  if (line.startsWith("-") && !line.startsWith("---")) {
    return RGBA.fromHex(theme.removeBg);
  }
  return undefined;
}

export function chunks(code: string, language: string | undefined): TextChunk[] {
  const fallback = RGBA.fromHex(theme.text);
  const lines = highlightLines(code.replace(/\n$/, ""), language);
  const result: TextChunk[] = [];
  lines.forEach((spans, index) => {
    if (index > 0) {
      result.push({ __isChunk: true, text: "\n", fg: fallback });
    }
    const bg = tintFor(spans.map((span) => span.text).join(""), language);
    for (const span of spans) {
      let attributes = 0;
      if (span.bold) {
        attributes |= TextAttributes.BOLD;
      }
      if (span.italic) {
        attributes |= TextAttributes.ITALIC;
      }
      result.push({
        __isChunk: true,
        text: span.text,
        fg: span.color ? RGBA.fromHex(span.color) : fallback,
        ...(bg ? { bg } : {}),
        attributes,
      });
    }
  });
  return result;
}

let handler: (text: string) => void = () => undefined;

export function onCodeCopy(next: (text: string) => void): void {
  handler = next;
}

export function codeBlockRenderer(context: RenderContext): MarkdownOptions["renderNode"] {
  return (token) => {
    if (token.type !== "code") {
      return undefined;
    }
    const language = typeof token.lang === "string" && token.lang !== "" ? token.lang : undefined;
    const box = new BoxRenderable(context, {
      flexDirection: "column",
      border: true,
      borderStyle: "rounded",
      borderColor: theme.line,
      paddingX: 1,
      title: language,
      titleColor: theme.dim,
    });
    const code = String(token.text).replace(/\n$/, "");
    box.add(
      new TextRenderable(context, {
        content: new StyledText(chunks(code, language)),
        wrapMode: "char",
      }),
    );
    box.add(
      new TextRenderable(context, {
        content: "copy",
        fg: theme.dim,
        alignSelf: "flex-end",
        onMouseDown: () => handler(code),
      }),
    );
    return box;
  };
}
