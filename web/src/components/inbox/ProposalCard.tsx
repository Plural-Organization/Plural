import type { Command, ProposalView, SessionState } from "@plural/client";
import { cx } from "../../lib/cx";
import { nameOf } from "./items";
import { Action } from "./Action";
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
          <b>{nameOf(state, proposal.author_id)}</b> proposes a prompt
        </span>
        <span className="muted">review mode</span>
      </div>
      <div className={styles.text}>{proposal.text}</div>
      <div className={styles.actions}>
        <Action hint="y" tone="primary" onPress={() => decide("approve")}>send to the agent</Action>
        <Action hint="e" onPress={() => onEdit(proposal)}>edit first</Action>
        <Action hint="n" onPress={() => decide("reject")}>reject</Action>
      </div>
    </div>
  );
}
