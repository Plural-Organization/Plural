import { useEffect, useRef, useState } from "react";
import { copyText } from "./clipboard";
import type { Invite } from "./useSession";

export function InviteDialog({ invite, onClose }: { invite: Invite; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const web = `${window.location.origin}${window.location.pathname}?join=${encodeURIComponent(invite.link)}`;
  const terminal = `plural join "${invite.link}"`;
  const expires = new Date(invite.expiresAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  useEffect(() => {
    dialog.current?.showModal();
  }, []);

  const copy = (key: string, text: string) =>
    void copyText(text).then((ok) => {
      setCopied(ok ? key : null);
      setTimeout(() => setCopied(null), 1600);
    });

  return (
    <dialog ref={dialog} className="dialog" onClose={onClose} aria-labelledby="invite-title">
      <h2 id="invite-title">invite a {invite.role}</h2>
      <p className="muted">
        The link works once and expires at {expires}. Anyone you send it to joins as a {invite.role}
        {invite.role === "viewer" ? " and can only watch." : " and can prompt the agent. Their writes and commands still ask you."}
      </p>
      <div className="share">
        <label>in the browser</label>
        <div className="copy-row">
          <code>{web}</code>
          <button className="button small" type="button" onClick={() => copy("web", web)}>
            {copied === "web" ? "copied" : "copy"}
          </button>
        </div>
        <label>in a terminal</label>
        <div className="copy-row">
          <code>{terminal}</code>
          <button className="button small" type="button" onClick={() => copy("terminal", terminal)}>
            {copied === "terminal" ? "copied" : "copy"}
          </button>
        </div>
      </div>
      <div className="dialog-actions">
        <button className="button" type="button" onClick={() => dialog.current?.close()}>
          done
        </button>
      </div>
    </dialog>
  );
}
