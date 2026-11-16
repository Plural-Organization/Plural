import { approvalChoices, type ApprovalDecision, type ApprovalView, type Command, type SessionState } from "@plural/client";
import { cx } from "../../lib/cx";
import { nameOf } from "./items";
import { Action } from "./Action";
import styles from "./Inbox.module.css";

// The answers and their keys come from @plural/client; here is only how each one reads and looks on a button.
type Look = Partial<Record<ApprovalDecision, { label: string; tone?: string }>>;

const LOOK: Look = {
  once: { label: "allow once", tone: "primary" },
  always: { label: "for the session" },
  reject: { label: "reject" },
  block: { label: "block", tone: "danger" },
};

// A folder outside the session is answered with how far it opens, or not at all.
const FOLDER_LOOK: Look = {
  read: { label: "read" },
  write: { label: "read + write", tone: "danger" },
  reject: { label: "refuse", tone: "primary" },
};

function buttons(approval: ApprovalView): { decision: ApprovalDecision; key: string; label: string; tone?: string }[] {
  const look = approval.folder ? FOLDER_LOOK : LOOK;
  return approvalChoices(approval).map((choice) => ({ ...choice, label: choice.decision, ...look[choice.decision] }));
}

// A command can be a whole script, and so can the pattern "for the session" would allow. Only its first line is said in a sentence,
// the full text sits in the scrollable box above, so the buttons never move out of sight.
const PATTERN_CHARS = 72;
function clip(text: string): string {
  const line = (text.split("\n")[0] ?? "").trim();
  return line.length > PATTERN_CHARS || text.includes("\n") ? `${line.slice(0, PATTERN_CHARS)}…` : line;
}

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

function FolderCard({ approval, state, now, send }: ApprovalCardProps) {
  const folder = approval.folder;
  if (!folder) {
    return null;
  }
  const call = approval.call;
  const who = nameOf(state, approval.provenance.initiator_id);
  return (
    <div className={cx(styles.card, styles.folder)} role="alertdialog" aria-label="folder outside the session">
      <div className={styles.head}>
        <span className={styles.folderTitle}>
          ⚠ Folder outside the session: {who} asks the agent to {folder.write ? "CHANGE" : "READ"} files here
        </span>
        <span className="muted mono">{timeLeft(approval.timeout_at, now)}</span>
      </div>
      <pre className={cx(styles.subject, styles.folderPath)}>{folder.folder}</pre>
      <p className={styles.why}>
        for <b>{call.name}</b> {call.subject}
      </p>
      {folder.broad ? (
        <p className={styles.warning} role="alert">
          ⚠ This is your whole disk or your home folder, not a project.
        </p>
      ) : null}
      <p className={styles.why}>Asked every time, nothing is remembered. “read” opens it for this one call only; “read + write” also lets the agent change files here.</p>
      <div className={styles.actions}>
        {buttons(approval).map((button) => (
          <Action key={button.decision} hint={button.key} tone={button.tone} onPress={() => send({ type: "approval.respond", approval_id: approval.id, decision: button.decision })}>
            {button.label}
          </Action>
        ))}
      </div>
    </div>
  );
}

export function ApprovalCard({ approval, state, now, send }: ApprovalCardProps) {
  if (approval.folder) {
    return <FolderCard approval={approval} state={state} now={now} send={send} />;
  }
  const call = approval.call;
  const guest = approval.provenance.initiator_role !== "host";
  const extra = Object.entries(call.args).filter(([key]) => key !== "command" && key !== "path");
  const why = guest
    ? `${nameOf(state, approval.provenance.initiator_id)}'s prompt started this run, so it asks you whatever the rules say.`
    : `${call.risk} actions ask the host.`;
  const patterns = approval.suggested_patterns;
  const session = patterns.length > 0 ? ` "for the session" allows ${clip(patterns[0] ?? "")}${patterns.length > 1 ? ` and ${patterns.length - 1} more` : ""}.` : "";

  return (
    <div className={styles.card}>
      <div className={styles.head}>
        <span>
          The agent asks to use <b>{call.name}</b>
        </span>
        <span className="muted mono">{timeLeft(approval.timeout_at, now)}</span>
      </div>
      <div className={styles.body}>
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
      </div>
      <div className={styles.actions}>
        {buttons(approval).map((button) => (
          <Action key={button.decision} hint={button.key} tone={button.tone} onPress={() => send({ type: "approval.respond", approval_id: approval.id, decision: button.decision })}>
            {button.label}
          </Action>
        ))}
      </div>
    </div>
  );
}
