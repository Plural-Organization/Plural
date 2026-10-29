import type { ApprovalView, Command, SessionState } from "@plural/client";
import { cx } from "../../lib/cx";
import { nameOf } from "./items";
import styles from "./Inbox.module.css";

type Decision = "once" | "always" | "reject" | "block";

const BUTTONS: { decision: Decision; key: string; label: string; tone?: string }[] = [
  { decision: "once", key: "y", label: "allow once", tone: "primary" },
  { decision: "always", key: "a", label: "for the session" },
  { decision: "reject", key: "n", label: "reject" },
  { decision: "block", key: "b", label: "block", tone: "danger" },
];

function timeLeft(timeoutAt: string, now: number): string {
  const seconds = Math.max(0, Math.round((Date.parse(timeoutAt) - now) / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

interface ApprovalCardProps {
  approval: ApprovalView;
  state: SessionState;
  now: number;
  send: (command: Command) => void;
}

export function ApprovalCard({ approval, state, now, send }: ApprovalCardProps) {
  const call = approval.call;
  const guest = approval.provenance.initiator_role !== "host";
  const extra = Object.entries(call.args).filter(([key]) => key !== "command" && key !== "path");
  const why = guest
    ? `${nameOf(state, approval.provenance.initiator_id)}'s prompt started this run, so it asks you whatever the rules say.`
    : `${call.risk} actions ask the host.`;
  const session = approval.suggested_patterns.length > 0 ? ` "for the session" allows ${approval.suggested_patterns.join(", ")}.` : "";

  return (
    <div className={styles.card}>
      <div className={styles.head}>
        <span>
          The agent asks to use <b>{call.name}</b>
        </span>
        <span className="muted mono">{timeLeft(approval.timeout_at, now)}</span>
      </div>
      <pre className={styles.subject}>{call.subject || JSON.stringify(call.args, null, 2)}</pre>
      {extra.length > 0 && call.subject ? (
        <details className={styles.args}>
          <summary>arguments</summary>
          <pre>{JSON.stringify(Object.fromEntries(extra), null, 2)}</pre>
        </details>
      ) : null}
      {(approval.warnings ?? []).map((warning) => (
        <p key={warning} className={styles.warning} role="alert">
          ⚠ {warning}
        </p>
      ))}
      <p className={styles.why}>
        {why}
        {session}
      </p>
      <div className={styles.actions}>
        {BUTTONS.map((button) => (
          <button
            key={button.decision}
            className={cx("button", button.tone)}
            type="button"
            onClick={() => send({ type: "approval.respond", approval_id: approval.id, decision: button.decision })}
          >
            <kbd>{button.key}</kbd> {button.label}
          </button>
        ))}
      </div>
    </div>
  );
}
