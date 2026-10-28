import { useEffect } from "react";
import type { Command, ProposalView } from "@plural/client";
import type { InboxItem } from "../components/inbox/items";

const DECISIONS = { y: "once", a: "always", n: "reject", b: "block" } as const;

interface Hotkeys {
  enabled: boolean;
  first: InboxItem | undefined;
  canAbort: boolean;
  send: (command: Command) => void;
  onEdit: (proposal: ProposalView) => void;
  onFocusInput: () => void;
}

export function useHotkeys({ enabled, first, canAbort, send, onEdit, onFocusInput }: Hotkeys) {
  useEffect(() => {
    if (!enabled) {
      return;
    }
    const onKey = (event: KeyboardEvent) => {
      const target = event.target;
      const typing = target instanceof Element && target.closest("input, textarea, select, [contenteditable]") !== null;
      if (typing || event.metaKey || event.ctrlKey || event.altKey) {
        return;
      }
      if (event.key === "Escape" && canAbort) {
        send({ type: "run.abort" });
      } else if (first?.kind === "join" && (event.key === "y" || event.key === "v" || event.key === "n")) {
        event.preventDefault();
        send({ type: "join.decide", request_id: first.id, decision: event.key === "y" ? "allow" : event.key === "v" ? "viewer" : "deny" });
      } else if (first?.kind === "approval" && event.key in DECISIONS) {
        event.preventDefault();
        send({ type: "approval.respond", approval_id: first.id, decision: DECISIONS[event.key as keyof typeof DECISIONS] });
      } else if (first?.kind === "proposal" && (event.key === "y" || event.key === "n")) {
        event.preventDefault();
        send({ type: "proposal.decide", proposal_id: first.id, decision: event.key === "y" ? "approve" : "reject" });
      } else if (first?.kind === "proposal" && event.key === "e") {
        event.preventDefault();
        onEdit(first.proposal);
      } else if (event.key === "/" || (first === undefined && event.key.length === 1 && /\S/.test(event.key))) {
        onFocusInput();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled, first, canAbort, send, onEdit, onFocusInput]);
}
