import { useEffect, useState } from "react";
import {
  bodyLines,
  displayName,
  kindOf,
  lastLine,
  metaOf,
  parseDiff,
  type FeedItem,
} from "@plural/client";
import { Markdown } from "./Markdown";
import { colorFor } from "./colors";

const OUTPUT_LINES = 60;
const LIVE_LINES = 14;
const DIFF_LINES = 120;

export function FeedItemView({ item, expanded, onToggle }: { item: FeedItem; expanded: boolean; onToggle: (id: string) => void }) {
  switch (item.kind) {
    case "banner":
      return null;
    case "user":
      return (
        <article className="msg user" style={{ "--who": colorFor(item.participantId) } as React.CSSProperties}>
          <header>
            <span className="who">{item.name}</span>
            <span className="muted">
              {item.role}
              {item.viaProposal ? " · approved by the host" : ""}
            </span>
          </header>
          <div className="text">{item.text}</div>
        </article>
      );
    case "assistant":
      return (
        <article className={`msg agent${item.streaming ? " streaming" : ""}`}>
          <header>
            <span className="who">agent</span>
            {item.streaming ? <span className="muted">writing…</span> : null}
          </header>
          {item.text ? <Markdown text={item.text} /> : <div className="muted">…</div>}
        </article>
      );
    case "tool":
      return <ToolLine item={item} expanded={expanded} onToggle={() => onToggle(item.id)} />;
    case "notice":
      return <div className={`notice ${item.tone}`}>{item.text}</div>;
  }
}

function useElapsed(running: boolean): number {
  const [started] = useState(() => Date.now());
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!running) {
      return;
    }
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [running]);
  return Math.max(0, Math.round((now - started) / 1000));
}

function ToolLine({ item, expanded, onToggle }: { item: Extract<FeedItem, { kind: "tool" }>; expanded: boolean; onToggle: () => void }) {
  const running = item.status === "running";
  const elapsed = useElapsed(running);
  const name = displayName(item.call.name);
  const meta = running
    ? `${elapsed}s`
    : metaOf({ name, tool: item.call.name, status: item.status, subject: item.call.subject, output: item.output, diff: item.diff, live: item.live });
  const peek = running && !expanded ? lastLine(item.live) : "";
  const mark = running ? <span className="spin" aria-label="running" /> : item.status === "ok" ? "✓" : "✗";
  return (
    <div className={`tool ${item.status}${expanded ? " open" : ""}`}>
      <button type="button" className="tool-line" onClick={onToggle} aria-expanded={expanded}>
        <span className="mark">{mark}</span>
        <span className="name">{name}</span>
        <span className="subject">{item.call.subject}</span>
        {peek ? <span className="peek">{peek}</span> : null}
        <span className="meta">{meta}</span>
      </button>
      {expanded ? <ToolBody item={item} /> : null}
    </div>
  );
}

function ToolBody({ item }: { item: Extract<FeedItem, { kind: "tool" }> }) {
  const kind = kindOf(item.call.name);
  const running = item.status === "running";
  if (item.diff !== null && !running && (kind === "edit" || kind === "write")) {
    const rows = parseDiff(item.diff);
    return (
      <div className="tool-body diff">
        {rows.slice(0, DIFF_LINES).map((row, index) =>
          row.kind === "gap" ? (
            <div key={index} className="row gap">
              ⋯
            </div>
          ) : (
            <div key={index} className={`row ${row.kind}`}>
              <span className="no">{row.newNo ?? row.oldNo ?? ""}</span>
              <span className="sign">{row.kind === "add" ? "+" : row.kind === "del" ? "−" : " "}</span>
              <span className="line">{row.text}</span>
            </div>
          ),
        )}
        {rows.length > DIFF_LINES ? <div className="more">… {rows.length - DIFF_LINES} more lines</div> : null}
      </div>
    );
  }
  const lines = running ? bodyLines(item.live).slice(-LIVE_LINES) : bodyLines(item.output);
  const shown = running ? lines : lines.slice(0, OUTPUT_LINES);
  return (
    <div className={`tool-body${item.status === "failed" ? " failed" : ""}`}>
      {kind === "bash" ? <div className="command">$ {item.call.subject}</div> : null}
      {shown.length > 0 ? <pre>{shown.join("\n")}</pre> : <div className="muted">{running ? "waiting for output…" : "no output"}</div>}
      {!running && lines.length > OUTPUT_LINES ? <div className="more">… {lines.length - OUTPUT_LINES} more lines</div> : null}
    </div>
  );
}
