import { findPerson, label, lastReply, mentionable, parseChat, parseSlash, ruleLine, SlashError, type ProposalView } from "@plural/client";
import { copyText } from "../lib/clipboard";
import { commandName, helpText, isHostOnly } from "../lib/commands";
import type { Session } from "./useSession";

interface Submit {
  session: Session;
  editing: ProposalView | null;
  onEdited: () => void;
  onLeave: () => void;
  flash: (text: string) => void;
  onDraw: () => void;
}

export function useSubmit({ session, editing, onEdited, onLeave, flash, onDraw }: Submit) {
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
        switch (rest[0]) {
          case undefined:
          case "link":
            send({ type: "invite.create", role: "participant", ttl_s: 3600, reusable: true });
            break;
          case "once":
            send({ type: "invite.create", role: "participant", ttl_s: 3600 });
            break;
          case "viewer":
            send({ type: "invite.create", role: "viewer", ttl_s: 3600 });
            break;
          case "revoke":
            send({ type: "link.revoke" });
            break;
          case "open":
          case "approve":
            send({ type: "link.set_admission", mode: rest[0] });
            notify("accent", rest[0] === "open" ? "the room link lets people in at once" : "you will be asked to let each person in");
            break;
          default:
            notify("warn", "usage: /invite [link | once | viewer | revoke | open | approve]");
        }
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
      case "kick": {
        const person = findPerson(rest.join(" "), mentionable(state, projection.meId));
        if (person === null) {
          notify("warn", "usage: /kick <name> (see /who)");
        } else {
          send({ type: "participant.revoke", participant_id: person.id });
          notify("dim", `${person.label} was removed from the session`);
        }
        return true;
      }
      case "leave":
        onLeave();
        return true;
      case "draw":
        onDraw();
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
      if (parsed.type === "show.agents") {
        const lines = state.agents.map((agent) => `  ${agent.name}  ${agent.role}${agent.read_only ? "  read-only" : ""}  ${agent.description}`);
        notify("accent", ["agents", ...lines].join("\n"));
        return;
      }
      if (parsed.type === "show.usage") {
        const lines = state.usage.map(
          (line) =>
            `  ${line.role} · ${line.model}  ${line.agent || "conversation"}  ${line.uses}×  in ${line.usage.input_tokens}  out ${line.usage.output_tokens}`,
        );
        notify("accent", lines.length > 0 ? ["usage", ...lines].join("\n") : "nothing spent yet in this session");
        return;
      }
      if (parsed.type === "show.mcp") {
        const lines = state.mcp.map(
          (server) =>
            `  ${server.status === "ready" ? "●" : server.status === "failed" ? "✕" : "○"} ${server.name}  ${server.status === "ready" ? `${server.tools} tools` : server.status}${server.error ? `: ${server.error}` : ""}`,
        );
        notify("accent", lines.length > 0 ? ["mcp", ...lines].join("\n") : "no MCP servers yet: /mcp import or /mcp add <name> <command|url>");
        return;
      }
      if (parsed.type === "show.skills") {
        const lines = state.skills.map((skill) => `  ${skill.name}${skill.scope === "global" ? " (global)" : ""}  ${skill.description}`);
        notify(
          "accent",
          lines.length > 0 ? ["skills", ...lines, "", "/skills search <query> finds more on skills.sh"].join("\n") : "no skills yet: /skills search <query> finds some on skills.sh",
        );
        return;
      }
      if (parsed.type === "show.policy") {
        const rules = state.policy.length > 0 ? state.policy.map((rule) => `${ruleLine(rule)}  [${rule.id}]`) : ["no session rules"];
        notify("accent", [`built-in rules: ${projection.basePolicy.length}`, ...rules].join("\n"));
        return;
      }
      send(parsed);
      if (parsed.type === "context.compact" && state.run !== null) {
        notify("dim", "the agent compacts the context before its next step");
      }
    } catch (error) {
      notify("warn", error instanceof SlashError ? error.message : String(error));
    }
  };

  const chat = (text: string): boolean => {
    try {
      const intent = parseChat(text, state, projection.meId);
      if (intent === null) {
        return false;
      }
      send(intent.command);
    } catch (error) {
      notify("warn", error instanceof SlashError ? error.message : String(error));
    }
    return true;
  };

  return (text: string) => {
    if (editing) {
      send({ type: "proposal.decide", proposal_id: editing.id, decision: "approve", edited_text: text });
      onEdited();
    } else if (chat(text)) {
      return;
    } else if (text.startsWith("/")) {
      slash(text);
    } else {
      send({ type: "prompt.submit", text, delivery: "now" });
    }
  };
}
