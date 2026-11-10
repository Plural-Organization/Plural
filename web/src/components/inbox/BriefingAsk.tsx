import type { BriefingRequestView, Command } from "@plural/client";
import { cx } from "../../lib/cx";
import { useNow } from "../../hooks/useNow";
import { Action } from "./Action";
import styles from "./Inbox.module.css";

interface BriefingAskProps {
  request: BriefingRequestView;
  send: (command: Command) => void;
}

export function BriefingAsk({ request, send }: BriefingAskProps) {
  const now = useNow(true);
  const seconds = Math.max(0, Math.round((now - Date.parse(request.requested_at)) / 1000));
  const decide = (decision: "allow" | "deny") => send({ type: "briefing.decide", request_id: request.id, decision });
  return (
    <div className={cx(styles.card, styles.join)}>
      <div className={styles.head}>
        <span>
          <b>{request.name}</b> asks your agent to brief them{request.update ? " (an update)" : ""}
        </span>
        <span className="muted">asked {seconds}s ago</span>
      </div>
      {request.focus ? <div>{request.focus}</div> : null}
      <div className={styles.actions}>
        <Action hint="y" tone="primary" onPress={() => decide("allow")}>write it</Action>
        <Action hint="n" onPress={() => decide("deny")}>not now</Action>
      </div>
    </div>
  );
}
