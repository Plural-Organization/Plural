import { Box, Text } from "ink";
import { marked, type Token, type Tokens } from "marked";
import type { ReactNode } from "react";
import { plainWidth, truncate } from "../lib/wrap";
import { theme } from "../theme";
import { CodeBlock } from "./Code";

function inline(tokens: Token[] | undefined, keyPrefix = ""): ReactNode[] {
  return (tokens ?? []).map((token, index) => {
    const key = `${keyPrefix}${index}`;
    switch (token.type) {
      case "strong":
        return (
          <Text key={key} bold>
            {inline((token as Tokens.Strong).tokens, key)}
          </Text>
        );
      case "em":
        return (
          <Text key={key} italic>
            {inline((token as Tokens.Em).tokens, key)}
          </Text>
        );
      case "del":
        return (
          <Text key={key} strikethrough>
            {inline((token as Tokens.Del).tokens, key)}
          </Text>
        );
      case "codespan":
        return (
          <Text key={key} color={theme.code}>
            {(token as Tokens.Codespan).text}
          </Text>
        );
      case "link": {
        const link = token as Tokens.Link;
        return (
          <Text key={key}>
            <Text color={theme.accent} underline>
              {inline(link.tokens, key)}
            </Text>
            {link.href && link.href !== link.text ? <Text color={theme.dim}> ({link.href})</Text> : null}
          </Text>
        );
      }
      case "br":
        return <Text key={key}>{"\n"}</Text>;
      case "escape":
      case "text": {
        const text = token as Tokens.Text;
        return text.tokens ? <Text key={key}>{inline(text.tokens, key)}</Text> : <Text key={key}>{unescapeHtml(text.text)}</Text>;
      }
      default:
        return <Text key={key}>{unescapeHtml("text" in token ? String(token.text) : token.raw)}</Text>;
    }
  });
}

function unescapeHtml(text: string): string {
  return text.replace(/&(amp|lt|gt|quot|#39);/g, (entity) => ({ "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'" })[entity] ?? entity);
}

function plain(tokens: Token[] | undefined): string {
  return (tokens ?? [])
    .map((token) => {
      const child = token as { tokens?: Token[]; text?: string; raw: string };
      return child.tokens ? plain(child.tokens) : (child.text ?? child.raw);
    })
    .join("");
}

function Table({ token, width }: { token: Tokens.Table; width: number }) {
  const rows = [token.header.map((cell) => plain(cell.tokens)), ...token.rows.map((row) => row.map((cell) => plain(cell.tokens)))];
  const columns = token.header.length;
  const natural = Array.from({ length: columns }, (_, column) => Math.max(...rows.map((row) => plainWidth(row[column] ?? ""))));
  const budget = Math.max(columns * 4, width - (columns + 1) * 3);
  const total = natural.reduce((sum, value) => sum + value, 0);
  const widths = total <= budget ? natural : natural.map((value) => Math.max(4, Math.floor((value / total) * budget)));
  const cell = (text: string, column: number) => truncate(text, widths[column] ?? 4).padEnd(widths[column] ?? 4);
  return (
    <Box flexDirection="column">
      <Text bold>{rows[0]?.map((text, column) => cell(text, column)).join("  ")}</Text>
      <Text color={theme.dim}>{widths.map((value) => "─".repeat(value)).join("──")}</Text>
      {rows.slice(1).map((row, index) => (
        <Text key={index}>{row.map((text, column) => cell(text, column)).join("  ")}</Text>
      ))}
    </Box>
  );
}

function List({ token, width, depth }: { token: Tokens.List; width: number; depth: number }) {
  const start = typeof token.start === "number" ? token.start : 1;
  return (
    <Box flexDirection="column">
      {token.items.map((item, index) => {
        const bullet = token.ordered ? `${start + index}.` : depth % 2 === 0 ? "•" : "◦";
        const mark = item.task ? (item.checked ? "☑ " : "☐ ") : "";
        return (
          <Box key={index}>
            <Text color={theme.dim}>{bullet} </Text>
            <Box flexDirection="column" flexShrink={1}>
              {item.task ? <Text>{mark}</Text> : null}
              <Blocks tokens={item.tokens} width={width - 3} depth={depth + 1} tight />
            </Box>
          </Box>
        );
      })}
    </Box>
  );
}

function Blocks({ tokens, width, depth = 0, tight = false }: { tokens: Token[]; width: number; depth?: number; tight?: boolean }) {
  const blocks = tokens.filter((token) => token.type !== "space");
  return (
    <Box flexDirection="column" gap={tight ? 0 : 1}>
      {blocks.map((token, index) => {
        switch (token.type) {
          case "heading": {
            const heading = token as Tokens.Heading;
            return (
              <Text key={index} bold color={heading.depth <= 2 ? theme.accent : undefined}>
                {inline(heading.tokens)}
              </Text>
            );
          }
          case "paragraph":
            return <Text key={index}>{inline((token as Tokens.Paragraph).tokens)}</Text>;
          case "text": {
            const text = token as Tokens.Text;
            return <Text key={index}>{text.tokens ? inline(text.tokens) : text.text}</Text>;
          }
          case "code": {
            const code = token as Tokens.Code;
            return <CodeBlock key={index} code={code.text} language={code.lang || undefined} />;
          }
          case "list":
            return <List key={index} token={token as Tokens.List} width={width} depth={depth} />;
          case "blockquote":
            return (
              <Box key={index} borderStyle="bold" borderColor={theme.dim} borderTop={false} borderBottom={false} borderRight={false} paddingLeft={1}>
                <Blocks tokens={(token as Tokens.Blockquote).tokens} width={width - 2} depth={depth} />
              </Box>
            );
          case "hr":
            return (
              <Text key={index} color={theme.dim}>
                {"─".repeat(Math.max(3, Math.min(width, 60)))}
              </Text>
            );
          case "table":
            return <Table key={index} token={token as Tokens.Table} width={width} />;
          default:
            return (
              <Text key={index} color={theme.dim}>
                {unescapeHtml(token.raw.trim())}
              </Text>
            );
        }
      })}
    </Box>
  );
}

export function Markdown({ text, width }: { text: string; width: number }) {
  const tokens = marked.lexer(text, { gfm: true, breaks: false });
  return <Blocks tokens={tokens} width={width} />;
}
