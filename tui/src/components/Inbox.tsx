import { label, type ApprovalView, type ProposalView, type SessionState } from "@plural/client";
import { colorFor, theme } from "../theme";

export type InboxItem =
  | { kind: "approval"; id: string; approval: ApprovalView }
  | { kind: "proposal"; id: string; proposal: ProposalView };

export function inboxItems(state: SessionState): InboxItem[] {
  return [
    ...Object.values(state.approvals).map((approval): InboxItem => ({ kind: "approval", id: approval.id, approval })),
    ...Object.values(state.proposals).map((proposal): InboxItem => ({ kind: "proposal", id: proposal.id, proposal })),
  ];
}

function from(state: SessionState, participantId: string): string {
  const participant = state.participants[participantId];
  return participant ? label(state, participant) : participantId;
}

function Keys({ items }: { items: [string, string][] }) {
  return (
    <text>
      {items.map(([key, action], index) => (
        <span key={key}>
          {index > 0 ? "   " : ""}
          <span fg={theme.accent}>
            <b>{key}</b>
          </span>
          <span fg={theme.dim}> {action}</span>
        </span>
      ))}
    </text>
  );
}

interface InboxProps {
  items: InboxItem[];
  state: SessionState;
  selected: number;
  focused: boolean;
  now: number;
}

export function Inbox({ items, state, selected, focused, now }: InboxProps) {
  const index = Math.min(selected, items.length - 1);
  const item = items[index];
  if (!item) {
    return null;
  }
  return (
    <box
      flexDirection="column"
      border
      borderStyle="rounded"
      borderColor={focused ? theme.warn : theme.dim}
      paddingX={1}
      marginX={2}
      flexShrink={0}
    >
      <text>
        <span fg={theme.warn}>
          <b>{item.kind === "approval" ? "approval needed" : "proposal"}</b>
        </span>
        <span fg={theme.dim}>
          {"  "}
          {index + 1}/{items.length}
        </span>
      </text>
      {item.kind === "approval" ? (
        <ApprovalBody approval={item.approval} state={state} now={now} focused={focused} />
      ) : (
        <ProposalBody proposal={item.proposal} state={state} focused={focused} />
      )}
    </box>
  );
}

function ApprovalBody({ approval, state, now, focused }: { approval: ApprovalView; state: SessionState; now: number; focused: boolean }) {
  const call = approval.call;
  const seconds = Math.max(0, Math.round((Date.parse(approval.timeout_at) - now) / 1000));
  const origin = approval.provenance.origin === "proposal" ? "via proposal" : "direct";
  const pattern = approval.suggested_patterns[0];
  return (
    <>
      <text>
        <b>{call.name}</b>
        <span fg={call.risk === "exec" ? theme.danger : call.risk === "write" ? theme.warn : theme.dim}> {call.risk}</span>
        <span fg={theme.dim}>
          {" "}
          · {from(state, approval.provenance.initiator_id)} ({origin}) · expires in {seconds}s
        </span>
      </text>
      <text fg={theme.info}>{call.name === "bash" ? `$ ${call.subject}` : call.subject}</text>
      {focused ? (
        <Keys items={[["y", "once"], ["a", pattern ? `always ${pattern}` : "always"], ["n", "reject"], ["b", "block this kind"]]} />
      ) : (
        <text fg={theme.dim}>tab to answer</text>
      )}
    </>
  );
}

function ProposalBody({ proposal, state, focused }: { proposal: ProposalView; state: SessionState; focused: boolean }) {
  const author = state.participants[proposal.author_id];
  return (
    <>
      <text>
        <span fg={colorFor(proposal.author_id)}>
          <b>{from(state, proposal.author_id)}</b>
        </span>
        <span fg={theme.dim}> {author?.role ?? ""} proposes</span>
      </text>
      <text>{proposal.text}</text>
      {focused ? (
        <Keys items={[["y", "approve"], ["e", "edit first"], ["n", "reject"]]} />
      ) : (
        <text fg={theme.dim}>tab to answer</text>
      )}
    </>
  );
}
