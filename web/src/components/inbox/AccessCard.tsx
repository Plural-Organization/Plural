import type { AccessRequestView, Command } from "@plural/client";
import { cx } from "../../lib/cx";
import { useNow } from "../../hooks/useNow";
import { Action } from "./Action";
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
        <Action hint="y" tone="primary" onPress={() => decide("allow")}>let them write</Action>
        <Action hint="n" onPress={() => decide("deny")}>not now</Action>
      </div>
    </div>
  );
}
