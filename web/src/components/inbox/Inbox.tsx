import type { Command, ProposalView, SessionState } from "@plural/client";
import { useNow } from "../../hooks/useNow";
import { ApprovalCard } from "./ApprovalCard";
import type { InboxItem } from "./items";
import { ProposalCard } from "./ProposalCard";
import styles from "./Inbox.module.css";

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
    <section className={styles.inbox} aria-label="Waits for you">
      {items.length > 1 ? <div className={styles.count}>{items.length} things wait for you · the oldest is first</div> : null}
      {first.kind === "approval" ? (
        <ApprovalCard approval={first.approval} state={state} now={now} send={send} />
      ) : (
        <ProposalCard proposal={first.proposal} state={state} send={send} onEdit={onEdit} />
      )}
    </section>
  );
}
