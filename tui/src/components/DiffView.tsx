import { gutterWidth, languageFor, parseDiff } from "../lib/diff";
import { highlightLines } from "../lib/highlight";
import { changedSpans } from "../lib/wordDiff";
import { theme } from "../theme";

interface Piece {
  text: string;
  color: string;
  marked: boolean;
}

function pieces(text: string, language: string | undefined, fallback: string, from: number, to: number): Piece[] {
  const out: Piece[] = [];
  let offset = 0;
  for (const part of highlightLines(text, language)[0] ?? []) {
    const color = part.color ?? fallback;
    let start = 0;
    while (start < part.text.length) {
      const at = offset + start;
      const marked = at >= from && at < to;
      const edge = marked ? to : at < from ? from : Infinity;
      const length = Math.min(part.text.length - start, edge - at);
      out.push({ text: part.text.slice(start, start + length), color, marked });
      start += length;
    }
    offset += part.text.length;
  }
  return out;
}

export function DiffView({ diff, path, limit }: { diff: string; path: string; limit: number }) {
  const rows = parseDiff(diff);
  const language = languageFor(path);
  const width = gutterWidth(rows);
  const changes = changedSpans(rows);
  const tint = { add: theme.addBg, del: theme.removeBg } as const;
  const bgOf = (kind: string) => (kind === "add" || kind === "del" ? tint[kind] : undefined);
  const mark = { add: theme.addMark, del: theme.removeMark } as const;
  const sign = { add: "+", del: "-", ctx: " ", gap: " " } as const;
  const signColor = { add: theme.ok, del: theme.danger, ctx: theme.dim, gap: theme.dim } as const;
  return (
    <box flexDirection="column">
      {rows.slice(0, limit).map((row, index) => {
        if (row.kind === "gap") {
          return (
            <text key={index} fg={theme.dim}>
              {" ".repeat(width + 1)}…
            </text>
          );
        }
        const change = changes.get(index);
        const bg = bgOf(row.kind);
        return (
          <box key={index} flexDirection="row" {...(bg ? { backgroundColor: bg } : {})}>
            <box width={width + 3} flexShrink={0}>
              <text wrapMode="none">
                <span fg={theme.dim}>{String(row.kind === "del" ? row.oldNo : (row.newNo ?? row.oldNo) ?? "").padStart(width)} </span>
                <span fg={signColor[row.kind]}>{sign[row.kind]} </span>
              </text>
            </box>
            <box flexGrow={1} flexShrink={1}>
              <text wrapMode="char">
                {pieces(row.text, language, theme.text, change?.from ?? 0, change?.to ?? 0).map((piece, position) =>
                  piece.marked && (row.kind === "add" || row.kind === "del") ? (
                    <span key={position} fg={piece.color} bg={mark[row.kind]}>
                      {piece.text}
                    </span>
                  ) : (
                    <span key={position} fg={piece.color}>
                      {piece.text}
                    </span>
                  ),
                )}
              </text>
            </box>
          </box>
        );
      })}
      {rows.length > limit ? <text fg={theme.dim}>… +{rows.length - limit} more lines · click to see all</text> : null}
    </box>
  );
}
