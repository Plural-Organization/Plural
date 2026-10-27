import type { Command, ProposalView, SessionState } from "@plural/client";
import { cx } from "../../lib/cx";
import { nameOf } from "./items";
import styles from "./Inbox.module.css";

interface ProposalCardProps {
  proposal: ProposalView;
  state: SessionState;
  send: (command: Command) => void;
  onEdit: (proposal: ProposalView) => void;
}

export function ProposalCard({ proposal, state, send, onEdit }: ProposalCardProps) {
  const decide = (decision: "approve" | "reject") => send({ type: "proposal.decide", proposal_id: proposal.id, decision });
  return (
    <div className={cx(styles.card, styles.proposal)}>
      <div className={styles.head}>
        <span>
          proposal from <b>{nameOf(state, proposal.author_id)}</b>
        </span>
        <span className="muted">review mode</span>
      </div>
      <div className={styles.text}>{proposal.text}</div>
      <div className={styles.actions}>
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
