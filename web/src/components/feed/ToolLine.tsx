import { useState } from "react";
import { bodyLines, displayName, kindOf, lastLine, metaOf, parseDiff, type FeedItem } from "@plural/client";
import { useNow } from "../../hooks/useNow";
import { cx } from "../../lib/cx";
import styles from "./ToolLine.module.css";

const OUTPUT_LINES = 60;
const LIVE_LINES = 14;
const DIFF_LINES = 120;

type ToolItem = Extract<FeedItem, { kind: "tool" }>;

export function ToolLine({ item, expanded, onToggle }: { item: ToolItem; expanded: boolean; onToggle: () => void }) {
  const running = item.status === "running";
  const [started] = useState(Date.now);
  const now = useNow(running);
  const name = displayName(item.call.name);
  const meta = running
    ? `${Math.max(0, Math.round((now - started) / 1000))}s`
    : metaOf({ name, tool: item.call.name, status: item.status, subject: item.call.subject, output: item.output, diff: item.diff, live: item.live });
  const peek = running && !expanded ? lastLine(item.live) : "";
  return (
    <div className={cx(styles.tool, item.status === "failed" && styles.failed)}>
      <button type="button" className={styles.line} onClick={onToggle} aria-expanded={expanded}>
        <span className={styles.mark}>{running ? <span className={styles.spin} aria-label="running" /> : item.status === "ok" ? "✓" : "✗"}</span>
        <span className={styles.name}>{name}</span>
        <span className={styles.subject}>{item.call.subject}</span>
        {peek ? <span className={styles.peek}>{peek}</span> : null}
        <span className={styles.meta}>{meta}</span>
      </button>
      {expanded ? <ToolBody item={item} /> : null}
    </div>
  );
}

function ToolBody({ item }: { item: ToolItem }) {
  const kind = kindOf(item.call.name);
  const running = item.status === "running";
  if (item.diff !== null && !running && (kind === "edit" || kind === "write")) {
    const rows = parseDiff(item.diff);
    return (
      <div className={styles.body}>
        {rows.slice(0, DIFF_LINES).map((row, index) =>
          row.kind === "gap" ? (
            <div key={index} className={cx(styles.row, styles.gap)}>
              ⋯
            </div>
          ) : (
            <div key={index} className={cx(styles.row, styles[row.kind])}>
              <span className={styles.no}>{row.newNo ?? row.oldNo ?? ""}</span>
              <span className={styles.sign}>{row.kind === "add" ? "+" : row.kind === "del" ? "−" : " "}</span>
              <span>{row.text}</span>
            </div>
          ),
        )}
        {rows.length > DIFF_LINES ? <div className={styles.more}>… {rows.length - DIFF_LINES} more lines</div> : null}
      </div>
    );
  }
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
