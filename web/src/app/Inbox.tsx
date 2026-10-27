import { useEffect, useState } from "react";
import { label, type ApprovalView, type Command, type ProposalView, type SessionState } from "@plural/client";

export type InboxItem =
  | { kind: "approval"; id: string; approval: ApprovalView }
  | { kind: "proposal"; id: string; proposal: ProposalView };

export function inboxItems(state: SessionState): InboxItem[] {
  return [
    ...Object.values(state.approvals).map((approval): InboxItem => ({ kind: "approval", id: approval.id, approval })),
    ...Object.values(state.proposals).map((proposal): InboxItem => ({ kind: "proposal", id: proposal.id, proposal })),
  ];
}

function nameOf(state: SessionState, participantId: string): string {
  const participant = state.participants[participantId];
  return participant ? label(state, participant) : participantId;
}

function useNow(active: boolean): number {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!active) {
      return;
    }
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  return now;
}

function left(timeoutAt: string, now: number): string {
  const seconds = Math.max(0, Math.round((Date.parse(timeoutAt) - now) / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

interface InboxProps {
  items: InboxItem[];
  state: SessionState;
  send: (command: Command) => void;
  onEdit: (proposal: ProposalView) => void;
}

export function Inbox({ items, state, send, onEdit }: InboxProps) {
  const now = useNow(items.some((item) => item.kind === "approval"));
  const first = items[0];
  if (first === undefined) {
    return null;
  }
  return (
    <section className="inbox" aria-label="Waits for you">
      {items.length > 1 ? <div className="inbox-count">{items.length} things wait for you · the oldest is first</div> : null}
      {first.kind === "approval" ? (
        <ApprovalCard approval={first.approval} state={state} now={now} send={send} />
      ) : (
        <ProposalCard proposal={first.proposal} state={state} send={send} onEdit={onEdit} />
      )}
    </section>
  );
}

function ApprovalCard({ approval, state, now, send }: { approval: ApprovalView; state: SessionState; now: number; send: (command: Command) => void }) {
  const call = approval.call;
  const guest = approval.provenance.initiator_role !== "host";
  const respond = (decision: "once" | "always" | "reject" | "block") => send({ type: "approval.respond", approval_id: approval.id, decision });
  const args = Object.entries(call.args).filter(([key]) => key !== "command" && key !== "path");
  return (
    <div className="card approval">
      <div className="card-head">
        <span>
          approval · <b>{call.name}</b>
        </span>
        <span className="muted mono">{left(approval.timeout_at, now)}</span>
      </div>
      <pre className="subject">{call.subject || JSON.stringify(call.args, null, 2)}</pre>
      {args.length > 0 && call.subject ? (
        <details className="args">
          <summary>arguments</summary>
          <pre>{JSON.stringify(Object.fromEntries(args), null, 2)}</pre>
        </details>
      ) : null}
      <p className="why">
        {guest
          ? `${nameOf(state, approval.provenance.initiator_id)}'s prompt started this run, so it asks you whatever the rules say.`
          : `${call.risk} actions ask the host.`}
        {approval.suggested_patterns.length > 0 ? ` "for the session" allows ${approval.suggested_patterns.join(", ")}.` : ""}
      </p>
      <div className="actions">
        <button className="button primary" type="button" onClick={() => respond("once")}>
          <kbd>y</kbd> allow once
        </button>
        <button className="button" type="button" onClick={() => respond("always")}>
          <kbd>a</kbd> for the session
        </button>
        <button className="button" type="button" onClick={() => respond("reject")}>
          <kbd>n</kbd> reject
        </button>
        <button className="button danger" type="button" onClick={() => respond("block")}>
          <kbd>b</kbd> block
        </button>
      </div>
    </div>
  );
}

function ProposalCard({ proposal, state, send, onEdit }: { proposal: ProposalView; state: SessionState; send: (command: Command) => void; onEdit: (proposal: ProposalView) => void }) {
  const decide = (decision: "approve" | "reject") => send({ type: "proposal.decide", proposal_id: proposal.id, decision });
  return (
    <div className="card proposal">
      <div className="card-head">
        <span>
          proposal from <b>{nameOf(state, proposal.author_id)}</b>
        </span>
        <span className="muted">review mode</span>
      </div>
      <div className="proposal-text">{proposal.text}</div>
      <div className="actions">
        <button className="button primary" type="button" onClick={() => decide("approve")}>
          <kbd>y</kbd> send to the agent
        </button>
        <button className="button" type="button" onClick={() => onEdit(proposal)}>
          <kbd>e</kbd> edit first
        </button>
        <button className="button" type="button" onClick={() => decide("reject")}>
          <kbd>n</kbd> reject
        </button>
      </div>
    </div>
  );
}
