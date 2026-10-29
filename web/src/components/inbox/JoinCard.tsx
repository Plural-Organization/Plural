import type { Command, JoinRequestView } from "@plural/client";
import { cx } from "../../lib/cx";
import { useNow } from "../../hooks/useNow";
import styles from "./Inbox.module.css";

interface JoinCardProps {
  request: JoinRequestView;
  send: (command: Command) => void;
}

export function JoinCard({ request, send }: JoinCardProps) {
  const now = useNow(true);
  const seconds = Math.max(0, Math.round((now - Date.parse(request.requested_at)) / 1000));
  const decide = (decision: "allow" | "viewer" | "deny") => send({ type: "join.decide", request_id: request.id, decision });
  return (
    <div className={cx(styles.card, styles.join)}>
      <div className={styles.head}>
        <span>
          <b>{request.name}</b> wants to join
        </span>
        <span className="muted">
          {request.client} · waiting {seconds}s
        </span>
      </div>
      <div className={styles.actions}>
        <button className="button primary" type="button" onClick={() => decide("allow")}>
          <kbd>y</kbd> let in
        </button>
        <button className="button" type="button" onClick={() => decide("viewer")}>
          <kbd>v</kbd> as a viewer
        </button>
        <button className="button" type="button" onClick={() => decide("deny")}>
          <kbd>n</kbd> refuse
        </button>
      </div>
    </div>
  );
}
