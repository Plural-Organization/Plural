import { useEffect, useRef, useState } from "react";
import type { Invite } from "../hooks/useSession";
import { copyText } from "../lib/clipboard";
import { browserJoinLink } from "../lib/links";
import styles from "./InviteDialog.module.css";

export function InviteDialog({ invite, onClose }: { invite: Invite; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const web = browserJoinLink(invite.link, window.location);
  const terminal = `plural join "${invite.link}"`;
  const expires = invite.expiresAt === null ? null : new Date(invite.expiresAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  useEffect(() => {
    dialog.current?.showModal();
  }, []);

  const copy = (key: string, text: string) =>
    void copyText(text).then((ok) => {
      setCopied(ok ? key : null);
      setTimeout(() => setCopied(null), 1600);
    });

  const links = [
    { key: "web", label: "in the browser", text: web },
    { key: "terminal", label: "in a terminal", text: terminal },
  ];

  return (
    <dialog ref={dialog} className={styles.dialog} onClose={onClose} aria-labelledby="invite-title">
      <h2 id="invite-title">{invite.reusable ? "the room link" : `invite a ${invite.role}`}</h2>
      {invite.reusable ? (
        <p className="muted">
          This link stays the same and does not expire, so you can send it at any time. Each person who uses it waits until you let them in, and you
          choose whether they take part or only watch. <code>/invite revoke</code> ends it.
        </p>
      ) : (
        <p className="muted">
          The link works once and expires at {expires}. Anyone you send it to joins as a {invite.role}
          {invite.role === "viewer" ? " and can only watch." : " and can prompt the agent. Their writes and commands still ask you."}
        </p>
      )}
      <div className={styles.share}>
        {links.map((link) => (
          <div key={link.key} className={styles.link}>
            <span className="label">{link.label}</span>
            <div className={styles.row}>
              <code>{link.text}</code>
              <button className="button small" type="button" onClick={() => copy(link.key, link.text)}>
                {copied === link.key ? "copied" : "copy"}
              </button>
            </div>
          </div>
        ))}
      </div>
      <div className={styles.actions}>
        <button className="button" type="button" onClick={() => dialog.current?.close()}>
          done
        </button>
      </div>
    </dialog>
  );
}
