import { label, lastReply, parseSlash, ruleLine, SlashError, type ProposalView } from "@plural/client";
import { copyText } from "../lib/clipboard";
import { commandName, helpText, isHostOnly } from "../lib/commands";
import type { Session } from "./useSession";

interface Submit {
  session: Session;
  editing: ProposalView | null;
  onEdited: () => void;
  onLeave: () => void;
  flash: (text: string) => void;
}

export function useSubmit({ session, editing, onEdited, onLeave, flash }: Submit) {
  const { projection, feed, send, notify } = session;
  const state = projection.state;
  const isHost = projection.me?.role === "host";

  const local = (text: string): boolean => {
    const [, ...rest] = text.slice(1).split(/\s+/);
    switch (commandName(text)) {
      case "help":
        notify("accent", helpText(projection.me?.role));
        return true;
      case "who":
        notify(
          "accent",
          Object.values(state.participants)
            .map((person) => `${person.connected ? "●" : "○"} ${label(state, person)} (${person.role})`)
            .join("\n"),
        );
        return true;
      case "invite":
        send({ type: "invite.create", role: rest[0] === "viewer" ? "viewer" : "participant", ttl_s: 3600 });
        return true;
      case "copy": {
        const reply = lastReply(feed);
        if (reply === "") {
          flash("nothing to copy yet");
        } else {
          void copyText(reply).then((ok) => flash(ok ? "copied the last reply" : "your browser blocked the clipboard"));
        }
        return true;
      }
      case "cancel": {
        const entry = state.queue[Number(rest[0]) - 1];
        if (entry === undefined) {
          notify("warn", state.queue.length === 0 ? "the queue is empty" : "usage: /cancel <number from the queue>");
        } else {
          send({ type: "queue.cancel", prompt_id: entry.prompt_id });
        }
        return true;
      }
      case "leave":
        onLeave();
        return true;
      default:
        return false;
    }
  };

  const slash = (text: string) => {
    if (isHostOnly(text) && !isHost) {
      notify("warn", `/${commandName(text)} is for the host`);
      return;
    }
    if (local(text)) {
      return;
    }
    try {
      const parsed = parseSlash(text);
      if (parsed === null) {
        return;
      }
      if (parsed.type === "show.policy") {
        const rules = state.policy.length > 0 ? state.policy.map((rule) => `${ruleLine(rule)}  [${rule.id}]`) : ["no session rules"];
        notify("accent", [`built-in rules: ${projection.basePolicy.length}`, ...rules].join("\n"));
        return;
      }
      send(parsed);
      if (parsed.type === "context.compact") {
        notify("dim", "the context will be compacted before the next prompt");
      }
    } catch (error) {
      notify("warn", error instanceof SlashError ? error.message : String(error));
    }
  };

  return (text: string) => {
    if (editing) {
      send({ type: "proposal.decide", proposal_id: editing.id, decision: "approve", edited_text: text });
      onEdited();
    } else if (text.startsWith("/")) {
      slash(text);
    } else {
      send({ type: "prompt.submit", text, delivery: "now" });
    }
  };
}
