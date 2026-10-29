import { label, PERMISSION_LABELS, type Participant, type Projection } from "@plural/client";
import { useState, type ReactNode } from "react";
import { colorFor, theme } from "../theme";
import { truncate } from "../lib/wrap";
import type { SpaceRow } from "../spaces";
import type { InboxItem } from "./Inbox";
import { Spinner, useElapsed } from "./Spinner";
import { ContextMeterView } from "./StatusBar";

export const SIDEBAR_WIDTH = 30;

function Section({ title, count, children }: { title: string; count?: number; children?: ReactNode }) {
  return (
    <box flexDirection="column" marginBottom={1}>
      <text fg={theme.dim}>
        {title.toUpperCase()}
        {count !== undefined ? `  ${count}` : ""}
      </text>
      {children}
    </box>
  );
}

function ParticipantRow({ participant, name, me, typing }: { participant: Participant; name: string; me: boolean; typing: boolean }) {
  const online = participant.connected;
  return (
    <box flexDirection="row">
      <text fg={online ? theme.ok : theme.dim}>● </text>
      <text fg={online ? colorFor(participant.id) : theme.dim}>{name}</text>
      <text fg={theme.dim}>
        {me ? " (you)" : ""}
        {participant.role === "host" ? "  host" : participant.role === "viewer" ? "  view" : ""}
      </text>
      {typing ? <text fg={theme.accent}>  typing…</text> : null}
    </box>
  );
}

const STATUS_MARK = { running: "●", waiting: "◆", idle: "○" } as const;

function SpacesSection({ rows, name, error, onOpen }: { rows: SpaceRow[]; name: string; error: string | null; onOpen?: (id: string) => void }) {
  return (
    <Section title={`spaces · ${truncate(name, 12)}`} count={rows.length}>
      {rows.slice(0, 8).map((row) => {
        const color = row.offline ? theme.line : row.status === "running" ? theme.ok : row.status === "waiting" ? theme.warn : theme.dim;
        return (
          <box key={row.id} flexDirection="column" backgroundColor={row.active ? theme.bg : undefined} onMouseDown={() => onOpen?.(row.id)}>
            <text>
              <span fg={color}>{STATUS_MARK[row.status]} </span>
              <span fg={row.active ? theme.accent : row.mine ? theme.text : colorFor(row.title)}>
                <b>{truncate(row.title, 14)}</b>
              </span>
              <span fg={color}>{row.status === "idle" ? "" : `  ${row.status}`}</span>
              <span fg={theme.dim}>{row.viewers > 0 ? `  👁 ${row.viewers}` : ""}</span>
            </text>
            <text fg={row.active ? theme.info : theme.dim}>  {truncate(row.detail, SIDEBAR_WIDTH - 8)}</text>
          </box>
        );
      })}
      {rows.length > 8 ? <text fg={theme.dim}>  +{rows.length - 8} more</text> : null}
      {error !== null ? (
        <text fg={theme.warn} wrapMode="word">
          team offline: {error}
        </text>
      ) : null}
    </Section>
  );
}

interface SidebarProps {
  spaces?: SpaceRow[];
  teamName?: string | null;
  teamError?: string | null;
  onOpenSpace?: (id: string) => void;
  onSettings: () => void;
  projection: Projection;
  room: string;
  inbox: InboxItem[];
  running: boolean;
  status: string;
}

export function Sidebar({ projection, room, inbox, running, status, spaces, teamName, teamError, onOpenSpace, onSettings }: SidebarProps) {
  const state = projection.state;
  const [hover, setHover] = useState(false);
  const elapsed = useElapsed(running);
  const rank = (participant: Participant): number =>
    participant.id === projection.meId ? 0 : participant.role === "host" ? 1 : participant.connected ? 2 : 3;
  const people = Object.values(state.participants).sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
  const online = people.filter((participant) => participant.connected).length;
  return (
    <box
      width={SIDEBAR_WIDTH}
      flexShrink={0}
      flexDirection="column"
      backgroundColor={theme.panel}
      paddingX={2}
      paddingY={1}
      border={["left"]}
      borderColor={theme.line}
    >
      <Section title="participants" count={online}>
        {people.map((participant) => (
          <ParticipantRow
            key={participant.id}
            participant={participant}
            name={label(state, participant)}
            me={participant.id === projection.meId}
            typing={projection.typing.has(participant.id) && participant.id !== projection.meId}
          />
        ))}
      </Section>
      {spaces && spaces.length > 0 && teamName ? <SpacesSection rows={spaces} name={teamName} error={teamError ?? null} onOpen={onOpenSpace} /> : null}
      {inbox.length > 0 ? (
        <Section title="needs you" count={inbox.length}>
          {inbox.slice(0, 4).map((item) =>
            item.kind === "join" ? (
              <box key={item.id} flexDirection="column">
                <text fg={theme.warn}>+ {truncate(item.request.name, SIDEBAR_WIDTH - 8)}</text>
                <text fg={theme.dim}>  wants to join</text>
              </box>
            ) : item.kind === "approval" ? (
              <box key={item.id} flexDirection="column">
                <text fg={theme.warn}>! {truncate(`${item.approval.call.name} ${item.approval.call.subject}`, SIDEBAR_WIDTH - 8)}</text>
                <text fg={theme.dim}>  from {nameOf(projection, item.approval.provenance.initiator_id)}</text>
              </box>
            ) : item.kind === "plan" ? (
              <text key={item.id} fg={theme.info}>
                ⏸ the plan is ready to start
              </text>
            ) : (
              <box key={item.id} flexDirection="column">
                <text fg={theme.warn}>? {nameOf(projection, item.proposal.author_id)} proposes</text>
                <text fg={theme.dim}>  {truncate(item.proposal.text, SIDEBAR_WIDTH - 8)}</text>
              </box>
            ),
          )}
        </Section>
      ) : null}
      {state.queue.length > 0 ? (
        <Section title="queue" count={state.queue.length}>
          {state.queue.slice(0, 4).map((entry, index) => (
            <box key={entry.prompt_id} flexDirection="column">
              <text>
                <span fg={theme.dim}>{index + 1} </span>
                <span fg={colorFor(entry.author_id)}>{truncate(nameOf(projection, entry.author_id), 14)}</span>
                {entry.delivery === "follow_up" ? <span fg={theme.dim}>  after</span> : null}
              </text>
              <text fg={theme.text}>  {truncate(entry.text.replace(/\s+/g, " "), SIDEBAR_WIDTH - 8)}</text>
            </box>
          ))}
          {state.queue.length > 4 ? <text fg={theme.dim}>  +{state.queue.length - 4} more</text> : null}
          <text fg={theme.dim}>/cancel &lt;n&gt; removes one</text>
        </Section>
      ) : null}
      <Section title="session">
        <text fg={theme.dim}>room {room.slice(0, 14)}…</text>
        <text fg={theme.dim}>
          prompts <span fg={state.prompt_mode === "open" ? theme.ok : theme.warn}>{state.prompt_mode}</span>
        </text>
        <text fg={theme.dim}>
          permissions <span fg={state.permission_mode === "default" ? theme.dim : theme.warn}>{PERMISSION_LABELS[state.permission_mode]}</span>
        </text>
        <text fg={theme.dim}>
          skills <span fg={state.skills.length > 0 ? theme.text : theme.dim}>{state.skills.length}</span>
        </text>
        {state.mcp.length > 0 ? (
          <text fg={theme.dim}>
            mcp{" "}
            <span fg={state.mcp.some((server) => server.status === "failed") ? theme.warn : theme.text}>
              {state.mcp.filter((server) => server.status === "ready").length}/{state.mcp.length}
            </span>
            {` · ${state.mcp.reduce((sum, server) => sum + server.tools, 0)} tools`}
          </text>
        ) : null}
        <ContextMeterView state={state} width={8} />
        <text fg={theme.dim}>{truncate(projection.agentLabel || "agent", SIDEBAR_WIDTH - 4)}</text>
        {state.fast_agent ? (
          <text fg={theme.dim}>
            fast <span fg={theme.info}>{truncate(state.fast_agent, SIDEBAR_WIDTH - 9)}</span>
          </text>
        ) : null}
        <text fg={theme.dim}>
          {"  "}
          {running ? <Spinner color={theme.info} /> : null}
          <span fg={running ? theme.info : theme.dim}>{running ? ` working ${elapsed}s` : "idle"}</span>
        </text>
        {running ? <text fg={theme.dim}>  {truncate(brief(status), SIDEBAR_WIDTH - 8)}</text> : null}
      </Section>
      <box flexGrow={1} />
      <box
        border
        borderStyle="rounded"
        borderColor={hover ? theme.accent : theme.line}
        paddingX={1}
        onMouseDown={onSettings}
        onMouseOver={() => setHover(true)}
        onMouseOut={() => setHover(false)}
      >
        <text fg={hover ? theme.accent : theme.text}>⚙  settings</text>
      </box>
      <text fg={theme.dim}>f2 settings · ctrl+b</text>
    </box>
  );
}

function nameOf(projection: Projection, participantId: string): string {
  const participant = projection.state.participants[participantId];
  return participant ? label(projection.state, participant) : participantId;
}

function brief(status: string): string {
  const text = status.replace(/^…\s*/, "");
  return text === "waiting for host approval" ? "needs approval" : text;
}
