import { label, type Participant, type Projection } from "@plural/client";
import type { ReactNode } from "react";
import { colorFor, theme } from "../theme";
import type { InboxItem } from "./Inbox";
import { Spinner, useElapsed } from "./Spinner";

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

function ParticipantRow({ participant, name, me }: { participant: Participant; name: string; me: boolean }) {
  const online = participant.connected;
  return (
    <box flexDirection="row">
      <text fg={online ? theme.ok : theme.dim}>● </text>
      <text fg={online ? colorFor(participant.id) : theme.dim}>{name}</text>
      <text fg={theme.dim}>
        {me ? " (you)" : ""}
        {participant.role === "host" ? "  host" : participant.role === "viewer" ? "  view" : ""}
      </text>
    </box>
  );
}

interface SidebarProps {
  projection: Projection;
  room: string;
  inbox: InboxItem[];
  running: boolean;
  status: string;
}

export function Sidebar({ projection, room, inbox, running, status }: SidebarProps) {
  const state = projection.state;
  const elapsed = useElapsed(running);
  const people = Object.values(state.participants).sort(
    (a, b) => Number(b.connected) - Number(a.connected) || a.name.localeCompare(b.name),
  );
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
          />
        ))}
      </Section>
      {inbox.length > 0 ? (
        <Section title="needs you" count={inbox.length}>
          {inbox.slice(0, 4).map((item) =>
            item.kind === "approval" ? (
              <box key={item.id} flexDirection="column">
                <text fg={theme.warn}>
                  ! {item.approval.call.name} {item.approval.call.subject}
                </text>
                <text fg={theme.dim}>  from {nameOf(projection, item.approval.provenance.initiator_id)}</text>
              </box>
            ) : (
              <box key={item.id} flexDirection="column">
                <text fg={theme.warn}>? {nameOf(projection, item.proposal.author_id)} proposes</text>
                <text fg={theme.dim}>  {item.proposal.text.slice(0, 22)}</text>
              </box>
            ),
          )}
        </Section>
      ) : null}
      <Section title="session">
        <text fg={theme.dim}>room {room.slice(0, 14)}…</text>
        <text fg={theme.dim}>
          prompts <span fg={state.prompt_mode === "open" ? theme.ok : theme.warn}>{state.prompt_mode}</span>
        </text>
        <text fg={theme.dim}>
          agent{"  "}
          {running ? (
            <span fg={theme.info}>
              <Spinner color={theme.info} /> {status.replace(/^…\s*/, "")} {elapsed}s
            </span>
          ) : (
            <span fg={theme.dim}>idle</span>
          )}
        </text>
      </Section>
      <box flexGrow={1} />
      <text fg={theme.dim}>ctrl+b hide panel</text>
    </box>
  );
}

function nameOf(projection: Projection, participantId: string): string {
  const participant = projection.state.participants[participantId];
  return participant ? label(projection.state, participant) : participantId;
}
