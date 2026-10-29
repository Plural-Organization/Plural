import type { BriefingRequestView, Command } from "@plural/client";
import { cx } from "../../lib/cx";
import { useNow } from "../../hooks/useNow";
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
        <button className="button primary" type="button" onClick={() => decide("allow")}>
          <kbd>y</kbd> write it
        </button>
        <button className="button" type="button" onClick={() => decide("deny")}>
          <kbd>n</kbd> not now
        </button>
      </div>
    </div>
  );
}
