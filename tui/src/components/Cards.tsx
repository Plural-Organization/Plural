import type { SyntaxStyle } from "@opentui/core";
import { useRenderer } from "@opentui/react";
import { useMemo } from "react";
import { codeBlockRenderer } from "../code";
import type { FeedItem, Tone } from "../feed";
import { previewLines } from "../lib/wrap";
import { colorFor, theme } from "../theme";
import { Spinner } from "./Spinner";

const TONES: Record<Tone, { color: string; mark: string }> = {
  dim: { color: theme.dim, mark: "·" },
  ok: { color: theme.ok, mark: "✓" },
  warn: { color: theme.warn, mark: "!" },
  danger: { color: theme.danger, mark: "✗" },
  accent: { color: theme.accent, mark: "◆" },
};

const OUTPUT_LINES = 6;

const TABLE = { widthMode: "content", cellPaddingY: 0, borderStyle: "rounded", borderColor: theme.line } as const;

export function Banner({ item }: { item: Extract<FeedItem, { kind: "banner" }> }) {
  return (
    <box flexDirection="column" marginBottom={1}>
      <text>
        <span fg={theme.accent}>
          <b>◆ plural</b>
        </span>
        <span fg={theme.dim}>  v{item.version} · room {item.room.slice(0, 14)}…</span>
      </text>
      {item.guestLink ? (
        <text fg={theme.dim}>
          invite a teammate: <span fg={theme.info}>plural join "{item.guestLink}"</span>
        </text>
      ) : null}
      <text fg={theme.dim}>/help for commands · esc interrupts · ctrl+c twice quits</text>
    </box>
  );
}

export function UserCard({ item }: { item: Extract<FeedItem, { kind: "user" }> }) {
  const color = colorFor(item.participantId);
  return (
    <box flexDirection="column" marginBottom={1} border={["left"]} borderStyle="heavy" borderColor={color} paddingLeft={1}>
      <text>
        <span fg={color}>
          <b>{item.name}</b>
        </span>
        <span fg={theme.dim}>
          {"  "}
          {item.role}
          {item.viaProposal ? " · approved by host" : ""}
        </span>
      </text>
      <text fg={theme.text}>{item.text}</text>
    </box>
  );
}

export function AssistantCard({ item, syntax }: { item: Extract<FeedItem, { kind: "assistant" }>; syntax: SyntaxStyle }) {
  const renderer = useRenderer();
  const renderNode = useMemo(() => codeBlockRenderer(renderer), [renderer]);
  return (
    <box flexDirection="column" marginBottom={1}>
      <text>
        <span fg={theme.accent}>
          <b>● plural</b>
        </span>
      </text>
      <box paddingLeft={2}>
        <markdown content={item.text} syntaxStyle={syntax} streaming={item.streaming} renderNode={renderNode} tableOptions={TABLE} />
      </box>
    </box>
  );
}

export function ToolCard({ item }: { item: Extract<FeedItem, { kind: "tool" }> }) {
  const failed = item.status === "failed";
  const color = failed ? theme.danger : theme.ok;
  const output = previewLines(item.status === "ok" ? item.output.replace(/\n?\[exit 0\]\s*$/, "") : item.output, OUTPUT_LINES);
  const showOutput = item.status !== "running" && output.lines.some((line) => line.trim() !== "");
  return (
    <box flexDirection="column" marginBottom={1}>
      <text>
        {item.status === "running" ? <Spinner color={theme.info} /> : <span fg={color}>{failed ? "✗" : "✓"}</span>}
        <span> </span>
        <b>{item.call.name}</b>
        {item.call.subject ? <span fg={theme.dim}> {item.call.subject}</span> : null}
      </text>
      {item.diff ? (
        <box paddingLeft={2}>
          <diff diff={item.diff} view="unified" showLineNumbers={false} addedBg={theme.addBg} removedBg={theme.removeBg} />
        </box>
      ) : showOutput ? (
        <box flexDirection="column" paddingLeft={2}>
          {output.lines.map((line, index) => (
            <text key={index} fg={failed ? theme.danger : theme.dim}>
              {index === 0 ? "⎿ " : "  "}
              {line}
            </text>
          ))}
          {output.more > 0 ? <text fg={theme.dim}>  … +{output.more} lines</text> : null}
        </box>
      ) : null}
    </box>
  );
}

export function NoticeCard({ item }: { item: Extract<FeedItem, { kind: "notice" }> }) {
  const tone = TONES[item.tone];
  return (
    <box flexDirection="row" marginBottom={item.text.includes("\n") ? 1 : 0}>
      <text fg={tone.color}>{tone.mark} </text>
      <text fg={item.tone === "dim" ? theme.dim : theme.text}>{item.text}</text>
    </box>
  );
}

export function FeedItemView({ item, syntax }: { item: FeedItem; syntax: SyntaxStyle }) {
  switch (item.kind) {
    case "banner":
      return <Banner item={item} />;
    case "user":
      return <UserCard item={item} />;
    case "assistant":
      return <AssistantCard item={item} syntax={syntax} />;
    case "tool":
      return <ToolCard item={item} />;
    case "notice":
      return <NoticeCard item={item} />;
  }
}
