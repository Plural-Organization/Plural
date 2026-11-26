import type { ReactNode } from "react";
import { CODE_LINES, lineCount } from "../../lib/canvas";
import { cx } from "../../lib/cx";
import { DocCard } from "./DocCard";
import styles from "./Markdown.module.css";
import { Mentions } from "./Mentions";

export type Block =
  | { kind: "code"; lang: string; text: string }
  | { kind: "heading"; level: number; text: string }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "table"; headers: string[]; rows: string[][] }
  | { kind: "quote"; text: string }
  | { kind: "paragraph"; text: string };

const FENCE = /^```\s*([\w+-]*)\s*$/;
const HEADING = /^(#{1,4})\s+(.*)$/;
const BULLET = /^\s*[-*]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
const TABLE_DIVIDER = /^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/;

function tableCells(line: string): string[] {
  const source = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  const cells: string[] = [];
  let cell = "";
  let escaped = false;
  let code = false;
  for (const character of source) {
    if (escaped) {
      cell += character === "|" ? "|" : `\\${character}`;
      escaped = false;
    } else if (character === "\\") {
      escaped = true;
    } else if (character === "`") {
      cell += character;
      code = !code;
    } else if (character === "|" && !code) {
      cells.push(cell.trim());
      cell = "";
    } else {
      cell += character;
    }
  }
  if (escaped) cell += "\\";
  cells.push(cell.trim());
  return cells;
}

export function blocks(source: string): Block[] {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const out: Block[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index]!;
    const fence = FENCE.exec(line);
    if (fence) {
      const body: string[] = [];
      index += 1;
      while (index < lines.length && !/^```\s*$/.test(lines[index]!)) {
        body.push(lines[index]!);
        index += 1;
      }
      index += 1;
      out.push({ kind: "code", lang: fence[1] ?? "", text: body.join("\n") });
      continue;
    }
    if (line.trim() === "") {
      index += 1;
      continue;
    }
    if (index + 1 < lines.length && line.includes("|") && TABLE_DIVIDER.test(lines[index + 1]!)) {
      const headers = tableCells(line);
      const rows: string[][] = [];
      index += 2;
      while (index < lines.length && lines[index]!.includes("|") && lines[index]!.trim() !== "") {
        const cells = tableCells(lines[index]!);
        rows.push(headers.map((_, column) => cells[column] ?? ""));
        index += 1;
      }
      out.push({ kind: "table", headers, rows });
      continue;
    }
    const heading = HEADING.exec(line);
    if (heading) {
      out.push({ kind: "heading", level: heading[1]!.length, text: heading[2]! });
      index += 1;
      continue;
    }
    if (BULLET.test(line) || NUMBERED.test(line)) {
      const ordered = NUMBERED.test(line);
      const items: string[] = [];
      while (index < lines.length) {
        const match = (ordered ? NUMBERED : BULLET).exec(lines[index]!);
        if (match) {
          items.push(match[1]!);
        } else if (/^\s{2,}\S/.test(lines[index]!) && items.length > 0) {
          items[items.length - 1] += ` ${lines[index]!.trim()}`;
        } else {
          break;
        }
        index += 1;
      }
      out.push({ kind: "list", ordered, items });
      continue;
    }
    if (line.startsWith(">")) {
      const body: string[] = [];
      while (index < lines.length && lines[index]!.startsWith(">")) {
        body.push(lines[index]!.replace(/^>\s?/, ""));
        index += 1;
      }
      out.push({ kind: "quote", text: body.join(" ") });
      continue;
    }
    const body: string[] = [];
    while (
      index < lines.length &&
      lines[index]!.trim() !== "" &&
      !FENCE.test(lines[index]!) &&
      !HEADING.test(lines[index]!) &&
      !BULLET.test(lines[index]!) &&
      !NUMBERED.test(lines[index]!)
    ) {
      body.push(lines[index]!);
      index += 1;
    }
    out.push({ kind: "paragraph", text: body.join("\n") });
  }
  return out;
}

const INLINE = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(\*[^*\s][^*\n]*\*|(?<![\w])_[^_\s][^_\n]*_(?![\w]))|(\[[^\]\n]+\]\(https?:\/\/[^)\s]+\))/g;

function inline(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let last = 0;
  let key = 0;
  for (const match of text.matchAll(INLINE)) {
    const at = match.index ?? 0;
    if (at > last) {
      nodes.push(<Mentions key={`text-${key++}`} text={text.slice(last, at)} />);
    }
    const token = match[0];
    if (match[1]) {
      nodes.push(<code key={key++}>{token.slice(1, -1)}</code>);
    } else if (match[2]) {
      nodes.push(<strong key={key++}><Mentions text={token.slice(2, -2)} /></strong>);
    } else if (match[3]) {
      nodes.push(<em key={key++}><Mentions text={token.slice(1, -1)} /></em>);
    } else {
      const split = token.indexOf("](");
      nodes.push(
        <a key={key++} href={token.slice(split + 2, -1)} target="_blank" rel="noopener noreferrer">
          {token.slice(1, split)}
        </a>,
      );
    }
    last = at + token.length;
  }
  if (last < text.length) {
    nodes.push(<Mentions key={`text-${key++}`} text={text.slice(last)} />);
  }
  return nodes;
}

interface MarkdownProps {
  text: string;
  streaming?: boolean;
  // Given, long code blocks become a card that opens the block in the canvas.
  onOpenCode?: (index: number) => void;
}

export function Markdown({ text, streaming = false, onOpenCode }: MarkdownProps) {
  let code = -1;
  return (
    <div className={cx(styles.md, streaming && styles.streaming)}>
      {blocks(text).map((block, index) => {
        switch (block.kind) {
          case "code": {
            code += 1;
            const lines = lineCount(block.text);
            if (onOpenCode && lines >= CODE_LINES) {
              const at = code;
              return <DocCard key={index} title={block.lang || "code"} meta={`${lines} lines`} preview={block.text} onOpen={() => onOpenCode(at)} />;
            }
            return (
              <pre key={index} className={styles.code} data-lang={block.lang || undefined}>
                <code>{block.text}</code>
              </pre>
            );
          }
          case "heading": {
            const Tag = (["h3", "h3", "h4", "h5"] as const)[block.level - 1] ?? "h5";
            return <Tag key={index}>{inline(block.text)}</Tag>;
          }
          case "list": {
            const Tag = block.ordered ? "ol" : "ul";
            return (
              <Tag key={index}>
                {block.items.map((item, position) => (
                  <li key={position}>{inline(item)}</li>
                ))}
              </Tag>
            );
          }
          case "table":
            return (
              <div key={index} className={styles.tableWrap}>
                <table>
                  <thead><tr>{block.headers.map((cell, column) => <th key={column}>{inline(cell)}</th>)}</tr></thead>
                  <tbody>{block.rows.map((row, position) => <tr key={position}>{row.map((cell, column) => <td key={column}>{inline(cell)}</td>)}</tr>)}</tbody>
                </table>
              </div>
            );
          case "quote":
            return <blockquote key={index}>{inline(block.text)}</blockquote>;
          case "paragraph":
            return <p key={index}>{inline(block.text)}</p>;
        }
      })}
    </div>
  );
}
