import { cacheHitLabel, commandName, isHostOnly, isSkillCommand, label, lastReply, localCommand, parseChat, parseSlash, pluginHints, routeOf, ruleLine, SlashError, type LocalEffect, type ProposalView } from "@plural/client";
import { copyText } from "../lib/clipboard";
import { helpText } from "../lib/commands";
import { contextText } from "../lib/context";
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
  const plugins = pluginHints(state.commands);

  const perform = (effect: LocalEffect): void => {
    if (effect.kind === "send") {
      send(effect.command);
    } else if (effect.kind === "notify") {
      notify(effect.tone, effect.text);
    } else if (effect.action === "access-requests") {
      const waiting = Object.values(state.access_requests);
      notify("accent", waiting.length === 0 ? "nobody is asking to write" : waiting.map((ask) => `${ask.name}${ask.note ? `: ${ask.note}` : ""}`).join("\n"));
    } else if (effect.action === "briefings") {
      notify("accent", `this session shares briefings: ${state.briefing_sharing} (/brief share off|ask|team)`);
    }
  };

  const local = (text: string): boolean => {
    const effects = localCommand("browser", text, projection);
    if (effects !== null) {
      effects.forEach(perform);
      return true;
    }
    switch (commandName(text)) {
      case "help":
        notify("accent", helpText(projection.me?.role, plugins));
        return true;
      case "who":
        notify(
          "accent",
          Object.values(state.participants)
            .map((person) => `${person.connected ? "●" : "○"} ${label(state, person)} (${person.role})`)
            .join("\n"),
        );
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
    if (isHostOnly("browser", text, plugins) && !isHost) {
      notify("warn", `/${commandName(text)} is for the host`);
      return;
    }
    if (local(text)) {
      return;
    }
    try {
      const parsed = parseSlash(text, new Set(state.commands.map((command) => command.name)));
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
            `  ${line.role} · ${line.model}  ${line.agent || "conversation"}  ${line.uses}×  in ${line.usage.input_tokens}  out ${line.usage.output_tokens}  cache ${line.usage.cache_read_tokens}  wrote ${line.usage.cache_write_tokens}  ${cacheHitLabel(line.usage)}`.trimEnd(),
        );
        notify("accent", lines.length > 0 ? ["usage", ...lines].join("\n") : "nothing spent yet in this session");
        return;
      }
      if (parsed.type === "show.context") {
        notify("accent", contextText(state.context));
        return;
      }
      if (parsed.type === "show.plugins") {
        const lines = state.plugins.map(
          (plugin) =>
            `  ${plugin.status === "loaded" ? "✓" : "✕"} ${plugin.name}  ${plugin.status === "loaded" ? [...plugin.commands.map((command) => `/${command}`), ...(plugin.tools ?? []).map((tool) => `${tool}()`)].join(" ") || "no commands or tools" : (plugin.error ?? "failed to load")}`,
        );
        notify("accent", lines.length > 0 ? ["plugins", ...lines].join("\n") : "no plugins yet: the host creates one with /plugins new <name>");
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
        const lines = state.skills.map((skill) => `  ${skill.name}${skill.builtin ? " (built-in)" : skill.scope === "global" ? " (global)" : ""}${skill.hidden ? ` (/skill:${skill.name} only)` : ""}  ${skill.description}`);
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
    if (routeOf(text, state, projection.meId).label === "watching") {
      notify("warn", "you are only watching. /access asks the host for the right to write");
      return;
    }
    if (editing) {
      send({ type: "proposal.decide", proposal_id: editing.id, decision: "approve", edited_text: text });
      onEdited();
    } else if (chat(text)) {
      return;
    } else if (text.startsWith("/") && !isSkillCommand(text)) {
      slash(text);
    } else {
      send({ type: "prompt.submit", text, delivery: "now" });
    }
  };
}
