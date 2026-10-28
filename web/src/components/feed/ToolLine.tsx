import { useState } from "react";
import { bodyLines, displayName, kindOf, lastLine, metaOf, oneLine, type FeedItem } from "@plural/client";
import { useNow } from "../../hooks/useNow";
import { cx } from "../../lib/cx";
import { DiffView, diffRows } from "../DiffView";
import styles from "./ToolLine.module.css";

const OUTPUT_LINES = 60;
const LIVE_LINES = 14;
// An edit shows this much of its diff in the feed; a click shows the rest, "open" puts it in the canvas.
const DIFF_PREVIEW = 14;

type ToolItem = Extract<FeedItem, { kind: "tool" }>;

interface ToolLineProps {
  item: ToolItem;
  expanded: boolean;
  onToggle: () => void;
  onOpen?: () => void;
}

export function ToolLine({ item, expanded, onToggle, onOpen }: ToolLineProps) {
  const running = item.status === "running";
  const [started] = useState(Date.now);
  const now = useNow(running);
  const name = displayName(item.call.name);
  const meta = running
    ? `${Math.max(0, Math.round((now - started) / 1000))}s`
    : metaOf({ name, tool: item.call.name, status: item.status, subject: item.call.subject, output: item.output, diff: item.diff, live: item.live });
  const peek = running && !expanded ? lastLine(item.live) : "";
  // A finished edit or write shows its diff right in the feed.
  const diff = !running && item.diff !== null ? item.diff : null;
  return (
    <div className={cx(styles.tool, item.status === "failed" && styles.failed)}>
      <div className={styles.top}>
        <button type="button" className={styles.line} onClick={onToggle} aria-expanded={expanded} title={`${expanded ? "Hide" : "Show"} details: ${item.call.subject}`}>
          <span className={styles.chevron} aria-hidden="true">{expanded ? "▾" : "▸"}</span>
          <span className={styles.mark}>{running ? <span className={styles.spin} aria-label="running" /> : item.status === "ok" ? "✓" : "✗"}</span>
          <span className={styles.name}>{name}</span>
          <span className={styles.subject}>{oneLine(item.call.subject)}</span>
          {peek ? <span className={styles.peek}>{peek}</span> : null}
          <span className={styles.meta}>{meta}</span>
        </button>
        {onOpen ? (
          <button type="button" className={styles.open} onClick={onOpen}>
            open ›
          </button>
        ) : null}
      </div>
      {diff !== null ? (
        <div className={styles.diff}>
          <DiffView diff={diff} limit={expanded ? undefined : DIFF_PREVIEW} anchor={`tool:${item.id}`} />
          {!expanded && diffRows(diff) > DIFF_PREVIEW ? (
            <button type="button" className={styles.more} onClick={onToggle}>
              show all {diffRows(diff)} lines
            </button>
          ) : null}
        </div>
      ) : expanded ? (
        <ToolBody item={item} />
      ) : null}
    </div>
  );
}

function ToolBody({ item }: { item: ToolItem }) {
  const kind = kindOf(item.call.name);
  const running = item.status === "running";
  const lines = running ? bodyLines(item.live).slice(-LIVE_LINES) : bodyLines(item.output);
  const shown = running ? lines : lines.slice(0, OUTPUT_LINES);
  return (
    <div className={styles.body}>
      {kind === "bash" ? <div className={styles.command}>$ {item.call.subject}</div> : null}
      {shown.length > 0 ? <pre>{shown.join("\n")}</pre> : <div className="muted">{running ? "waiting for output…" : "no output"}</div>}
      {!running && lines.length > OUTPUT_LINES ? <div className={styles.more}>… {lines.length - OUTPUT_LINES} more lines</div> : null}
    </div>
  );
}
