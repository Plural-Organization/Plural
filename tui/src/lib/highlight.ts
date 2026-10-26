import hljs from "highlight.js/lib/core";
import bash from "highlight.js/lib/languages/bash";
import css from "highlight.js/lib/languages/css";
import diff from "highlight.js/lib/languages/diff";
import go from "highlight.js/lib/languages/go";
import javascript from "highlight.js/lib/languages/javascript";
import json from "highlight.js/lib/languages/json";
import markdown from "highlight.js/lib/languages/markdown";
import python from "highlight.js/lib/languages/python";
import rust from "highlight.js/lib/languages/rust";
import sql from "highlight.js/lib/languages/sql";
import typescript from "highlight.js/lib/languages/typescript";
import xml from "highlight.js/lib/languages/xml";
import yaml from "highlight.js/lib/languages/yaml";
import { theme } from "../theme";

hljs.registerLanguage("bash", bash);
hljs.registerLanguage("css", css);
hljs.registerLanguage("diff", diff);
hljs.registerLanguage("go", go);
hljs.registerLanguage("javascript", javascript);
hljs.registerLanguage("json", json);
hljs.registerLanguage("markdown", markdown);
hljs.registerLanguage("python", python);
hljs.registerLanguage("rust", rust);
hljs.registerLanguage("sql", sql);
hljs.registerLanguage("typescript", typescript);
hljs.registerLanguage("xml", xml);
hljs.registerLanguage("yaml", yaml);

const ALIASES: Record<string, string> = {
  sh: "bash",
  shell: "bash",
  zsh: "bash",
  console: "bash",
  js: "javascript",
  jsx: "javascript",
  ts: "typescript",
  tsx: "typescript",
  py: "python",
  rs: "rust",
  yml: "yaml",
  html: "xml",
  md: "markdown",
  patch: "diff",
};

export interface Span {
  text: string;
  color?: string;
  bold?: boolean;
  italic?: boolean;
}

const STYLES: Record<string, Omit<Span, "text">> = {
  keyword: { color: theme.code },
  built_in: { color: theme.info },
  type: { color: theme.info },
  literal: { color: theme.warn },
  number: { color: theme.warn },
  string: { color: theme.ok },
  regexp: { color: theme.ok },
  symbol: { color: theme.ok },
  comment: { color: theme.dim, italic: true },
  doctag: { color: theme.dim, italic: true },
  title: { color: theme.accent },
  function: { color: theme.accent },
  class: { color: theme.info },
  attr: { color: theme.info },
  attribute: { color: theme.info },
  property: { color: theme.info },
  variable: { color: theme.text },
  meta: { color: theme.dim },
  addition: { color: theme.ok },
  deletion: { color: theme.danger },
  section: { color: theme.accent, bold: true },
  tag: { color: theme.code },
  name: { color: theme.code },
};

const ENTITIES: Record<string, string> = { "&lt;": "<", "&gt;": ">", "&amp;": "&", "&quot;": '"', "&#x27;": "'", "&#39;": "'" };

function unescape(text: string): string {
  return text.replace(/&(lt|gt|amp|quot|#x27|#39);/g, (entity) => ENTITIES[entity] ?? entity);
}

function styleFor(stack: string[]): Omit<Span, "text"> {
  for (let index = stack.length - 1; index >= 0; index -= 1) {
    const name = (stack[index] ?? "").replace(/^hljs-/, "").split(/[\s_]/)[0] ?? "";
    const style = STYLES[name] ?? STYLES[(stack[index] ?? "").replace(/^hljs-/, "")];
    if (style) {
      return style;
    }
  }
  return {};
}

function spans(html: string): Span[] {
  const result: Span[] = [];
  const stack: string[] = [];
  const pattern = /<span class="([^"]*)">|<\/span>|([^<]+)/g;
  for (const match of html.matchAll(pattern)) {
    if (match[1] !== undefined) {
      stack.push(match[1].split(" ")[0] ?? "");
    } else if (match[2] !== undefined) {
      result.push({ text: unescape(match[2]), ...styleFor(stack) });
    } else {
      stack.pop();
    }
  }
  return result;
}

function splitLines(parts: Span[]): Span[][] {
  const lines: Span[][] = [[]];
  for (const part of parts) {
    const pieces = part.text.split("\n");
    pieces.forEach((piece, index) => {
      if (index > 0) {
        lines.push([]);
      }
      if (piece !== "") {
        lines[lines.length - 1]?.push({ ...part, text: piece });
      }
    });
  }
  return lines;
}

export function highlightLines(code: string, language: string | undefined): Span[][] {
  const name = language ? (ALIASES[language] ?? language) : undefined;
  if (name === undefined || !hljs.getLanguage(name)) {
    return code.split("\n").map((line) => (line === "" ? [] : [{ text: line }]));
  }
  try {
    return splitLines(spans(hljs.highlight(code, { language: name, ignoreIllegals: true }).value));
  } catch {
    return code.split("\n").map((line) => (line === "" ? [] : [{ text: line }]));
  }
}
