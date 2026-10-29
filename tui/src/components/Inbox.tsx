import { label, type AccessRequestView, type ApprovalView, type JoinRequestView, type ProposalView, type SessionState } from "@plural/client";
import { colorFor, theme } from "../theme";

export type InboxItem =
  | { kind: "join"; id: string; request: JoinRequestView }
  | { kind: "access"; id: string; request: AccessRequestView }
  | { kind: "approval"; id: string; approval: ApprovalView }
  | { kind: "proposal"; id: string; proposal: ProposalView }
  | { kind: "plan"; id: string };

export function inboxItems(state: SessionState): InboxItem[] {
  return [
    ...Object.values(state.join_requests).map((request): InboxItem => ({ kind: "join", id: request.id, request })),
    ...Object.values(state.access_requests).map((request): InboxItem => ({ kind: "access", id: request.participant_id, request })),
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
          <b>{item.kind === "join" ? "wants to join" : item.kind === "access" ? "wants to write" : item.kind === "approval" ? "approval needed" : item.kind === "plan" ? "plan ready" : "proposal"}</b>
        </span>
        <span fg={theme.dim}>
          {"  "}
          {index + 1}/{items.length}
        </span>
      </text>
      {item.kind === "join" ? (
        <JoinBody request={item.request} now={now} focused={focused} />
      ) : item.kind === "access" ? (
        <AccessBody request={item.request} now={now} focused={focused} />
      ) : item.kind === "approval" ? (
        <ApprovalBody approval={item.approval} state={state} now={now} focused={focused} />
      ) : item.kind === "plan" ? (
        <PlanBody focused={focused} />
      ) : (
        <ProposalBody proposal={item.proposal} state={state} focused={focused} />
      )}
    </box>
  );
}

function JoinBody({ request, now, focused }: { request: JoinRequestView; now: number; focused: boolean }) {
  const seconds = Math.max(0, Math.round((now - Date.parse(request.requested_at)) / 1000));
  return (
    <>
      <text>
        <span fg={colorFor(request.id)}>
          <b>{request.name}</b>
        </span>
        <span fg={theme.dim}>
          {" "}
          · {request.client} · waiting {seconds}s · came in with the room link
        </span>
      </text>
      {focused ? (
        <Keys items={[["y", "let in"], ["v", "as a viewer"], ["n", "refuse"]]} />
      ) : (
        <text fg={theme.dim}>tab to answer</text>
      )}
    </>
  );
}

function AccessBody({ request, now, focused }: { request: AccessRequestView; now: number; focused: boolean }) {
  const seconds = Math.max(0, Math.round((now - Date.parse(request.requested_at)) / 1000));
  return (
    <>
      <text>
        <span fg={colorFor(request.participant_id)}>
          <b>{request.name}</b>
        </span>
        <span fg={theme.dim}> · watching · asked {seconds}s ago</span>
      </text>
      {request.note ? <text>{request.note}</text> : null}
      {focused ? <Keys items={[["y", "let them write"], ["n", "not now"]]} /> : <text fg={theme.dim}>tab to answer</text>}
    </>
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
      {(approval.warnings ?? []).map((warning) => (
        <text key={warning} fg={theme.warn}>
          ⚠ {warning}
        </text>
      ))}
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

function PlanBody({ focused }: { focused: boolean }) {
  return (
    <>
      <text>The agent finished planning. Start the work?</text>
      {focused ? (
        <Keys items={[["a", "yes, auto mode"], ["e", "yes, accept edits"], ["y", "yes, ask before changes"], ["n", "keep planning"]]} />
      ) : (
        <text fg={theme.dim}>tab to answer</text>
      )}
    </>
  );
}
