import type { SyntaxStyle } from "@opentui/core";
import { useRenderer } from "@opentui/react";
import { useMemo } from "react";
import { codeBlockRenderer } from "../code";
import type { FeedItem, Tone } from "../feed";
import { gutterWidth, languageFor, parseDiff } from "../lib/diff";
import { highlightLines } from "../lib/highlight";
import { bodyLines, displayName, kindOf, lastLine, metaOf, oneLine } from "../lib/tools";
import { truncate } from "../lib/wrap";
import { colorFor, theme } from "../theme";
import { collapseText } from "@plural/client";
import { Picture } from "./Splash";
import { Spinner, useElapsed } from "./Spinner";

const TONES: Record<Tone, { color: string; mark: string }> = {
  dim: { color: theme.dim, mark: "·" },
  ok: { color: theme.ok, mark: "✓" },
  warn: { color: theme.warn, mark: "!" },
  danger: { color: theme.danger, mark: "✗" },
  accent: { color: theme.accent, mark: "◆" },
};

const table = () => ({ widthMode: "content", cellPaddingY: 0, borderStyle: "rounded", borderColor: theme.line }) as const;

export function Banner({ item }: { item: Extract<FeedItem, { kind: "banner" }> }) {
  return (
    <box flexDirection="row" alignItems="center" marginBottom={1}>
      <box flexShrink={0} marginRight={3}>
        <Picture />
      </box>
      <box flexDirection="column" flexShrink={1}>
        <text>
          <span fg={theme.accent}>
            <b>◆ plural</b>
          </span>
          <span fg={theme.dim}>  v{item.version} · room {item.room.slice(0, 14)}…</span>
        </text>
        {item.guestLink ? (
          <text fg={theme.dim}>
            room link: <span fg={theme.info}>plural join "{item.guestLink}"</span>
            <span fg={theme.dim}> · you let people in, /invite revoke ends the link</span>
          </text>
        ) : null}
        {item.teamLink ? (
          <text fg={theme.dim}>
            team link: <span fg={theme.info}>{item.teamLink}</span>
            <span fg={theme.dim}> · one use, for an hour</span>
          </text>
        ) : null}
        <text fg={theme.dim}>/help for commands · esc interrupts · ctrl+o tool details · ctrl+c twice quits</text>
      </box>
    </box>
  );
}

export const pinId = (id: string): string => `user-${id}`;
export const feedId = (id: string): string => `feed-${id}`;

export function PinnedPrompt({ item, width, onJump }: { item: Extract<FeedItem, { kind: "user" }>; width: number; onJump: () => void }) {
  const color = colorFor(item.participantId);
  const first = item.text.split("\n")[0] ?? "";
  const room = Math.max(10, width - item.name.length - item.role.length - 16);
  return (
    <box position="absolute" top={1} left={0} width="100%" zIndex={10} paddingX={2} backgroundColor={theme.panel} onMouseDown={onJump}>
      <box border={["left"]} borderStyle="heavy" borderColor={color} paddingLeft={1}>
        <text wrapMode="none">
          <span fg={color}>
            <b>{item.name}</b>
          </span>
          <span fg={theme.dim}> {item.role} · </span>
          <span fg={theme.text}>{truncate(first, room)}</span>
          <span fg={theme.dim}>{"  ↑ jump"}</span>
        </text>
      </box>
    </box>
  );
}

const BRIEFING_LINES = 30;

export function BriefingCard({ item, expanded, onToggle, onCopy }: { item: Extract<FeedItem, { kind: "briefing" }>; expanded: boolean; onToggle: () => void; onCopy: (text: string) => void }) {
  const long = item.text.split("\n").length > BRIEFING_LINES;
  const view = long && !expanded ? collapseText(item.text, BRIEFING_LINES) : { text: item.text, hidden: 0 };
  return (
    <box flexDirection="column" marginY={1} border={["left"]} borderStyle="heavy" borderColor={theme.info} backgroundColor={theme.panel} paddingX={1}>
      <text>
        <span fg={theme.info}>
          <b>✉ briefing from {item.from}</b>
        </span>
        <span fg={theme.dim}>
          {item.update ? " · update" : ""} · as of event {item.asOf}
        </span>
      </text>
      <text fg={theme.text} wrapMode="word">
        {view.text}
      </text>
      {long ? (
        <box onMouseDown={() => onToggle()}>
          <text fg={theme.accent}>{expanded ? "▴ show less" : `▾ ${view.hidden} more lines · click or ctrl+o to expand`}</text>
        </box>
      ) : null}
      <box flexDirection="row">
        <box onMouseDown={() => onCopy(item.text)}>
          <text fg={theme.accent}>copy</text>
        </box>
        <text fg={theme.dim}>  ·  /brief give hands it to your agent  ·  /brief update refreshes it</text>
      </box>
    </box>
  );
}

export type Queued = "steer" | "follow_up" | null;

export function UserCard({ item, queued }: { item: Extract<FeedItem, { kind: "user" }>; queued: Queued }) {
  const color = colorFor(item.participantId);
  return (
    <box id={pinId(item.id)} flexDirection="column" marginTop={1} marginBottom={1} border={["left"]} borderStyle="heavy" borderColor={color} backgroundColor={theme.panel} paddingX={1} paddingY={1}>
      <text>
        <span fg={color}>
          <b>{item.name}</b>
        </span>
        <span fg={theme.dim}>
          {"  "}
          {item.role} · to agent
          {item.viaProposal ? " · approved by host" : ""}
        </span>
      </text>
      <text fg={theme.text} wrapMode="word">{item.text}</text>
      {queued ? (
        <text fg={theme.warn}>
          ⧗ queued · <span fg={theme.dim}>{queued === "steer" ? "the agent reads it after its current step" : "sent when the run ends"}</span>
        </text>
      ) : null}
    </box>
  );
}

export function ChatCard({ item }: { item: Extract<FeedItem, { kind: "chat" }> }) {
  const color = colorFor(item.authorId);
  const direct = item.to !== null;
  const head = direct
    ? item.mine
      ? `you → ${item.toName ?? "someone"}`
      : `${item.name} → you`
    : item.mine
      ? "you · to the room"
      : `${item.name} · to the room`;
  const mark = item.mentioned ? theme.accent : direct ? theme.warn : color;
  return (
    <box flexDirection="column" marginBottom={1} border={["left"]} borderStyle="single" borderColor={mark} paddingLeft={1}>
      <text>
        <span fg={mark}>✉ </span>
        <span fg={direct ? theme.warn : color}>
          <b>{head}</b>
        </span>
        <span fg={theme.dim}>
          {direct ? " · private, the agent does not see it" : " · the agent does not see it"}
          {item.mentioned && !direct ? " · mentions you" : ""}
        </span>
      </text>
      <text fg={theme.text} wrapMode="word">{item.text}</text>
    </box>
  );
}

const REPLY_LINES = 40;

interface AssistantProps {
  item: Extract<FeedItem, { kind: "assistant" }>;
  syntax: SyntaxStyle;
  expanded: boolean;
  onToggle: () => void;
}

export function AssistantCard({ item, syntax, expanded, onToggle }: AssistantProps) {
  const renderer = useRenderer();
  const renderNode = useMemo(() => codeBlockRenderer(renderer), [renderer]);
  if (item.streaming && item.text.trim() === "") {
    return null;
  }
  const long = !item.streaming && item.text.split("\n").length > REPLY_LINES;
  const view = long && !expanded ? collapseText(item.text, REPLY_LINES) : { text: item.text, hidden: 0 };
  return (
    <box flexDirection="column" marginBottom={1}>
      <text>
        <span fg={theme.accent}>
          <b>● plural</b>
        </span>
      </text>
      <box paddingLeft={2}>
        <markdown content={view.text} syntaxStyle={syntax} streaming={item.streaming} renderNode={renderNode} tableOptions={table()} />
      </box>
      {long ? (
        <box paddingLeft={2} onMouseDown={() => onToggle()}>
          <text fg={theme.accent}>{expanded ? "▴ show less" : `▾ ${view.hidden} more lines · click or ctrl+o to expand`}</text>
        </box>
      ) : null}
    </box>
  );
}

const EXPANDED_LINES = 40;
const LIVE_LINES = 15;
const DIFF_LINES = 60;

function trimLines(lines: string[], limit: number): { shown: string; more: number } {
  return { shown: lines.slice(0, limit).join("\n"), more: Math.max(0, lines.length - limit) };
}

function DiffView({ diff, path }: { diff: string; path: string }) {
  const rows = parseDiff(diff);
  const language = languageFor(path);
  const width = gutterWidth(rows);
  const shown = rows.slice(0, DIFF_LINES);
  const tint = { add: theme.addBg, del: theme.removeBg, ctx: undefined, gap: undefined } as const;
  const sign = { add: "+", del: "−", ctx: " ", gap: " " } as const;
  const signColor = { add: theme.ok, del: theme.danger, ctx: theme.dim, gap: theme.dim } as const;
  return (
    <box flexDirection="column">
      {shown.map((row, index) =>
        row.kind === "gap" ? (
          <text key={index} fg={theme.dim}>
            {" ".repeat(width)} ⋯
          </text>
        ) : (
          <box key={index} flexDirection="row" backgroundColor={tint[row.kind]}>
            <text wrapMode="char">
              <span fg={theme.dim}>{String(row.newNo ?? row.oldNo ?? "").padStart(width)} </span>
              <span fg={signColor[row.kind]}>{sign[row.kind]} </span>
              {(highlightLines(row.text, language)[0] ?? []).map((part, position) => (
                <span key={position} fg={part.color ?? (row.kind === "ctx" ? theme.dim : theme.text)}>
                  {part.text}
                </span>
              ))}
            </text>
          </box>
        ),
      )}
      {rows.length > DIFF_LINES ? <text fg={theme.dim}>… +{rows.length - DIFF_LINES} more lines</text> : null}
    </box>
  );
}

function Body({ item, onCopy }: { item: Extract<FeedItem, { kind: "tool" }>; onCopy: (text: string) => void }) {
  const kind = kindOf(item.call.name);
  const failed = item.status === "failed";
  const running = item.status === "running";
  if (item.diff !== null && !running && (kind === "edit" || kind === "write")) {
    return (
      <box flexDirection="column">
        <DiffView diff={item.diff} path={item.call.subject} />
        <box alignSelf="flex-end" onMouseDown={() => onCopy(item.diff ?? "")}>
          <text fg={theme.dim}>copy</text>
        </box>
      </box>
    );
  }
  const lines = running ? bodyLines(item.live).slice(-LIVE_LINES) : bodyLines(item.output);
  const trimmed = running ? { shown: lines.join("\n"), more: 0 } : trimLines(lines, EXPANDED_LINES);
  return (
    <box flexDirection="column">
      {kind === "bash" ? <text fg={theme.info}>$ {item.call.subject}</text> : null}
      {trimmed.shown !== "" ? (
        <text fg={failed ? theme.danger : theme.text} wrapMode="char">
          {trimmed.shown}
        </text>
      ) : (
        <text fg={theme.dim}>{running ? "waiting for output…" : "no output"}</text>
      )}
      {trimmed.more > 0 ? <text fg={theme.dim}>… +{trimmed.more} more lines</text> : null}
      {!running && lines.length > 0 ? (
        <box alignSelf="flex-end" onMouseDown={() => onCopy(`${kind === "bash" ? `$ ${item.call.subject}\n` : ""}${lines.join("\n")}`)}>
          <text fg={theme.dim}>copy</text>
        </box>
      ) : null}
    </box>
  );
}

interface ToolCardProps {
  item: Extract<FeedItem, { kind: "tool" }>;
  expanded: boolean;
  onToggle: () => void;
  onCopy: (text: string) => void;
  width: number;
}

export function ToolCard({ item, expanded, onToggle, onCopy, width }: ToolCardProps) {
  const running = item.status === "running";
  const failed = item.status === "failed";
  const elapsed = useElapsed(running);
  const name = displayName(item.call.name);
  const meta = running
    ? `${elapsed}s`
    : metaOf({ name, tool: item.call.name, status: item.status, subject: item.call.subject, output: item.output, diff: item.diff, live: item.live });
  const peek = running && kindOf(item.call.name) === "agent" ? lastLine(item.live) : "";
  const fixed = name.length + meta.length + 10;
  const subject = truncate(oneLine(item.call.subject), Math.max(0, width - fixed - (peek ? 24 : 0)));
  const room = Math.max(0, width - fixed - subject.length - 3);
  return (
    <box flexDirection="column" marginBottom={expanded ? 1 : 0}>
      <box flexDirection="row" onMouseDown={() => onToggle()}>
        <text wrapMode="none">
          <span fg={theme.dim}>{expanded ? "▾ " : "▸ "}</span>
          {running ? <Spinner color={theme.info} /> : <span fg={failed ? theme.danger : theme.ok}>{failed ? "✗" : "✓"}</span>}
          <span> </span>
          <b>{name}</b>
          <span fg={theme.text}> {subject}</span>
          {meta ? <span fg={failed ? theme.danger : theme.dim}> · {meta}</span> : null}
          {peek && room > 8 ? <span fg={theme.dim}> · {truncate(peek, room)}</span> : null}
        </text>
      </box>
      {expanded ? (
        <box flexDirection="column" marginLeft={2} paddingLeft={1} border={["left"]} borderColor={theme.line}>
          <Body item={item} onCopy={onCopy} />
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

interface ViewProps {
  item: FeedItem;
  syntax: SyntaxStyle;
  width: number;
  expanded: boolean;
  queued?: Queued;
  onToggle: (id: string) => void;
  onCopy: (text: string) => void;
}

export function FeedItemView({ item, syntax, width, expanded, queued = null, onToggle, onCopy }: ViewProps) {
  switch (item.kind) {
    case "banner":
      return <Banner item={item} />;
    case "user":
      return <UserCard item={item} queued={queued} />;
    case "chat":
      return <ChatCard item={item} />;
    case "assistant":
      return <AssistantCard item={item} syntax={syntax} expanded={expanded} onToggle={() => onToggle(item.id)} />;
    case "tool":
      return <ToolCard item={item} expanded={expanded} onToggle={() => onToggle(item.id)} onCopy={onCopy} width={width} />;
    case "notice":
      return <NoticeCard item={item} />;
    case "briefing":
      return <BriefingCard item={item} expanded={expanded} onToggle={() => onToggle(item.id)} onCopy={onCopy} />;
  }
}
