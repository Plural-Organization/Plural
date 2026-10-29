import type { AccessRequestView, Command } from "@plural/client";
import { cx } from "../../lib/cx";
import { useNow } from "../../hooks/useNow";
import styles from "./Inbox.module.css";

interface AccessCardProps {
  request: AccessRequestView;
  send: (command: Command) => void;
}

export function AccessCard({ request, send }: AccessCardProps) {
  const now = useNow(true);
  const seconds = Math.max(0, Math.round((now - Date.parse(request.requested_at)) / 1000));
  const decide = (decision: "allow" | "deny") => send({ type: "access.decide", participant_id: request.participant_id, decision });
  return (
    <div className={cx(styles.card, styles.join)}>
      <div className={styles.head}>
        <span>
          <b>{request.name}</b> wants to write
        </span>
        <span className="muted">watching · asked {seconds}s ago</span>
      </div>
      {request.note ? <div>{request.note}</div> : null}
      <div className={styles.actions}>
        <button className="button primary" type="button" onClick={() => decide("allow")}>
          <kbd>y</kbd> let them write
        </button>
        <button className="button" type="button" onClick={() => decide("deny")}>
          <kbd>n</kbd> not now
        </button>
      </div>
    </div>
  );
}
