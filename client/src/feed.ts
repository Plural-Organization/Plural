import { withDefaults } from "./reduce";
import { mentionsMe } from "./chat";
import { label, shortTokens } from "./presenter";
import type { Projection } from "./projection";
import type { Event, Participant, Role, SessionState, ToolCallView, TranscriptEntry } from "./protocol";

export const TOOL_OUTPUT_LIMIT = 20_000;
export const LIVE_OUTPUT_LIMIT = 8000;

export type Tone = "dim" | "ok" | "warn" | "danger" | "accent";
export type ToolStatus = "running" | "ok" | "failed";

export type FeedItem =
  | { kind: "banner"; id: string; room: string; version: string; guestLink: string | null }
  | { kind: "user"; id: string; participantId: string; name: string; role: Role; viaProposal: boolean; text: string; files?: string[] }
  | {
      kind: "chat";
      id: string;
      authorId: string;
      name: string;
      text: string;
      to: string | null;
      toName: string | null;
      mine: boolean;
      mentioned: boolean;
    }
  | { kind: "assistant"; id: string; text: string; streaming: boolean }
  | { kind: "tool"; id: string; call: ToolCallView; status: ToolStatus; output: string; diff: string | null; live: string }
  | { kind: "notice"; id: string; tone: Tone; text: string; action?: "board" }
  | { kind: "briefing"; id: string; from: string; text: string; asOf: number; update: boolean };

export interface Feed {
  items: FeedItem[];
  approvals: Record<string, ToolCallView>;
  history: boolean;
  counter: number;
}

export function emptyFeed(): Feed {
  return { items: [], approvals: {}, history: false, counter: 0 };
}

export function withBanner(feed: Feed, banner: Extract<FeedItem, { kind: "banner" }>): Feed {
  return { ...feed, items: [banner, ...feed.items] };
}

export function withNotice(feed: Feed, tone: Tone, text: string): Feed {
  const counter = feed.counter + 1;
  return { ...feed, counter, items: [...feed.items, { kind: "notice", id: `n${counter}`, tone, text }] };
}

export function lastReply(feed: Feed): string {
  const parts: string[] = [];
  for (let index = feed.items.length - 1; index >= 0; index -= 1) {
    const item = feed.items[index];
    if (item?.kind === "user") {
      break;
    }
    if (item?.kind === "assistant" && item.text.trim() !== "") {
      parts.unshift(item.text.trim());
    }
  }
  return parts.join("\n\n");
}

function replace(items: FeedItem[], id: string, change: (item: FeedItem) => FeedItem): FeedItem[] {
  return items.map((item) => (item.id === id ? change(item) : item));
}

export function absorb(feed: Feed, event: Event, projection: Projection): Feed {
  const state = projection.state;
  const nameOf = (participantId: string | null): string => {
    const participant = state.participants[participantId ?? ""];
    return participant ? label(state, participant) : (participantId ?? "system");
  };
  const note = (tone: Tone, text: string): Feed => withNotice(feed, tone, text);

  switch (event.type) {
    case "session.welcome":
      return event.agent.startsWith("demo")
        ? note(
            "warn",
            "demo agent: it follows a fixed script, so any text just lists the folder and `$ cmd` runs a command.\nFor a real model set ANTHROPIC_API_KEY, or PLURAL_PROVIDER=openai with PLURAL_MODEL and PLURAL_BASE_URL.",
          )
        : feed;
    case "session.snapshot":
      return loadHistory(feed, withDefaults(event.state), event.streaming, projection.meId);
    case "board.opened": {
      const counter = feed.counter + 1;
      const who = event.by === projection.meId ? "you" : nameOf(event.by);
      const text = event.open ? `${who} opened the board` : `${who} closed the board`;
      return { ...feed, counter, items: [...feed.items, { kind: "notice", id: `n${counter}`, tone: "dim", text, ...(event.open ? { action: "board" as const } : {}) }] };
    }
    case "chat.posted":
      return {
        ...feed,
        items: [
          ...feed.items,
          chatItem(
            { id: event.message_id, author_id: event.author_id, text: event.text, to: event.to, mentions: event.mentions },
            state,
            projection.meId,
          ),
        ],
      };
    case "participant.joined":
      return event.participant.id === projection.meId
        ? feed
        : note("dim", `${label(state, event.participant)} joined as ${event.participant.role}`);
    case "participant.left":
      return note("dim", `${nameOf(event.participant_id)} left`);
    case "participant.role_changed":
      return note("dim", `${nameOf(event.participant_id)} is now ${event.role}`);
    case "participant.revoked":
      return note("danger", `access revoked for ${event.participant_id}`);
    case "briefing.requested":
      return event.request.participant_id === projection.meId
        ? note("dim", "you asked for a briefing of this session, waiting for the host")
        : note("warn", `${nameOf(event.request.participant_id)} asks for a briefing of this session${event.request.focus ? `: ${event.request.focus}` : ""}`);
    case "briefing.resolved":
      if (event.participant_id !== projection.meId) {
        return note("dim", `${event.decision === "granted" ? "you agreed to" : "you refused"} a briefing for ${nameOf(event.participant_id)}`);
      }
      return event.decision === "granted" ? note("dim", "the host agreed, the briefing is being written") : note("warn", "the host said no to the briefing");
    case "briefing.delivered": {
      if (event.to !== projection.meId) {
        return note("dim", `the briefing for ${nameOf(event.to)} ${event.error ? "could not be written" : "was written"}`);
      }
      if (event.error) {
        return note("danger", `the briefing could not be written: ${event.error}`);
      }
      const counter = feed.counter + 1;
      const host = Object.values(state.participants).find((person) => person.role === "host");
      const from = host ? label(state, host) : "the host";
      return { ...feed, counter, items: [...feed.items, { kind: "briefing", id: `b${counter}`, from, text: event.text, asOf: event.as_of_seq, update: event.update }] };
    }
    case "briefing.sharing_changed":
      return note("accent", { off: "this session shares no briefings", ask: "briefings of this session are given when you agree", team: "briefings of this session are given to anyone who asks" }[event.mode]);
    case "briefing.imported":
      return note("ok", `${event.item.source}'s briefing${event.item.as_of_seq === null ? "" : ` (as of event ${event.item.as_of_seq})`} is now in the agent's notes`);
    case "access.requested": {
      if (event.request.participant_id === projection.meId) {
        return note("dim", "you asked the host for the right to write, waiting for an answer");
      }
      const reason = event.request.note ? `: ${event.request.note}` : "";
      return note("warn", `${nameOf(event.request.participant_id)} asks for the right to write${reason}`);
    }
    case "access.resolved": {
      const granted = event.decision === "granted";
      if (event.participant_id === projection.meId) {
        return note(granted ? "ok" : "warn", granted ? "the host let you write" : "the host said no for now, you can ask again in a few minutes");
      }
      return note("dim", `${granted ? "you let" : "you said no to"} ${nameOf(event.participant_id)}${granted ? " write" : ""}`);
    }
    case "session.prompt_mode_changed":
      return note(
        "accent",
        event.mode === "open"
          ? "prompts are open: participants prompt the agent directly"
          : "prompts are in review: the host approves each participant prompt",
      );
    case "skills.changed": {
      const parts = [
        event.added.length > 0 ? `added ${event.added.join(", ")}` : "",
        event.removed.length > 0 ? `removed ${event.removed.join(", ")}` : "",
      ].filter(Boolean);
      return parts.length > 0 ? note("accent", `skills: ${parts.join(" · ")}`) : feed;
    }
    case "tools.loaded":
      return note("dim", `the agent loaded ${event.tools.join(", ")}`);
    case "plugins.changed": {
      const failed = event.plugins.filter((plugin) => plugin.status === "failed");
      return failed.length > 0
        ? note("warn", failed.map((plugin) => `plugin ${plugin.name} failed: ${plugin.error ?? "unknown error"}`).join("\n"))
        : feed;
    }
    case "command.invoked":
      return note("dim", `${nameOf(event.invoker_id)} ran /${event.command}${event.args ? ` ${event.args}` : ""}`);
    case "command.replied":
      return note(event.ok ? "accent" : "danger", `/${event.command} · ${event.text}`);
    case "prompt.dequeued":
      return event.reason === "cancelled" ? note("dim", "a queued prompt was cancelled") : feed;
    case "proposal.created":
      return note("warn", `${nameOf(event.proposal.author_id)} proposes: ${event.proposal.text}`);
    case "proposal.approved":
      return note("ok", `proposal approved by ${nameOf(event.decided_by)}`);
    case "proposal.rejected":
      return note("danger", `proposal rejected by ${nameOf(event.decided_by)}`);
    case "prompt.accepted": {
      const author = state.participants[event.author_id];
      return {
        ...feed,
        items: [
          ...feed.items,
          {
            kind: "user",
            id: event.prompt_id,
            participantId: event.author_id,
            name: author ? label(state, author) : event.author_id,
            role: author?.role ?? event.provenance.initiator_role,
            viaProposal: event.provenance.origin === "proposal",
            text: event.text,
            files: event.attachments.map((id) => state.attachments[id]?.name ?? "a file"),
          },
        ],
      };
    }
    case "run.ended": {
      const settled = {
        ...feed,
        items: feed.items.map((item): FeedItem => {
          if (item.kind === "assistant" && item.streaming) {
            return { ...item, streaming: false };
          }
          if (item.kind === "tool" && item.status === "running") {
            return { ...item, status: "failed" };
          }
          return item;
        }),
      };
      if (event.reason === "aborted") {
        return withNotice(settled, "warn", "run aborted");
      }
      if (event.reason === "error" || event.reason === "limit") {
        return withNotice(
          settled,
          "danger",
          `run ${event.reason === "limit" ? "stopped" : "failed"}${event.error ? `: ${event.error}` : ""}`,
        );
      }
      return settled;
    }
    case "message.started":
      return {
        ...feed,
        items: [...feed.items, { kind: "assistant", id: event.message_id, text: "", streaming: true }],
      };
    case "message.delta": {
      if (event.thinking) {
        return feed;
      }
      const exists = feed.items.some((item) => item.id === event.message_id);
      const items = exists
        ? replace(feed.items, event.message_id, (item) =>
            item.kind === "assistant" ? { ...item, text: item.text + event.text } : item,
          )
        : [...feed.items, { kind: "assistant" as const, id: event.message_id, text: event.text, streaming: true }];
      return { ...feed, items };
    }
    case "message.ended": {
      const exists = feed.items.some((item) => item.id === event.message_id);
      if (!exists) {
        return event.text
          ? { ...feed, items: [...feed.items, { kind: "assistant", id: event.message_id, text: event.text, streaming: false }] }
          : feed;
      }
      if (!event.text) {
        return { ...feed, items: feed.items.filter((item) => item.id !== event.message_id) };
      }
      return {
        ...feed,
        items: replace(feed.items, event.message_id, () => ({
          kind: "assistant",
          id: event.message_id,
          text: event.text,
          streaming: false,
        })),
      };
    }
    case "tool.started":
      return {
        ...feed,
        items: [
          ...feed.items,
          { kind: "tool", id: event.call.id, call: event.call, status: "running", output: "", diff: null, live: "" },
        ],
      };
    case "tool.output":
      return {
        ...feed,
        items: replace(feed.items, event.call_id, (item) =>
          item.kind === "tool" && item.status === "running"
            ? { ...item, live: (item.live + event.chunk).slice(-LIVE_OUTPUT_LIMIT) }
            : item,
        ),
      };
    case "tool.ended":
      return {
        ...feed,
        items: replace(feed.items, event.call_id, (item) =>
          item.kind === "tool"
            ? {
                ...item,
                status: event.ok ? "ok" : "failed",
                output: event.output.slice(0, TOOL_OUTPUT_LIMIT),
                diff: event.diff,
                live: "",
              }
            : item,
        ),
      };
    case "approval.requested":
      return { ...feed, approvals: { ...feed.approvals, [event.approval.id]: event.approval.call } };
    case "approval.resolved": {
      const call = feed.approvals[event.approval_id];
      const { [event.approval_id]: _gone, ...rest } = feed.approvals;
      const next = { ...feed, approvals: rest };
      const subject = call ? `${call.name} ${call.subject}`.trim() : "tool call";
      const who = event.resolved_by === null ? "timeout" : nameOf(event.resolved_by);
      if (event.decision === "reject" || event.decision === "block") {
        return withNotice(next, "danger", `${subject}: ${event.decision === "block" ? "blocked" : "rejected"} (${who})`);
      }
      if (event.resolved_by !== projection.meId) {
        return withNotice(next, "ok", `${subject}: allowed${event.decision === "always" ? " for the session" : ""} (${who})`);
      }
      return next;
    }
    case "policy.rule_added":
      return note("accent", `policy + ${event.rule.action} ${event.rule.tool} ${event.rule.pattern}  [${event.rule.id}]`);
    case "policy.rule_removed":
      return note("accent", `policy - ${event.rule_id}`);
    case "context.compacted":
      return note("dim", `context compacted: ${shortTokens(event.tokens_before)} tokens summarized`);
    case "attachment.added":
      return note("dim", `${nameOf(event.attachment.owner_id)} attached ${event.attachment.name}`);
    case "invite.created":
      return note("ok", `invite for a ${event.role}: ${event.link}`);
    case "error":
      return note("danger", event.message);
    default:
      return feed;
  }
}

function chatItem(
  entry: { id: string; author_id: string; text: string; to: string | null; mentions: string[] },
  state: SessionState,
  meId: string | null,
): FeedItem {
  const nameOf = (participantId: string): string => {
    const participant = state.participants[participantId];
    return participant ? label(state, participant) : participantId;
  };
  return {
    kind: "chat",
    id: entry.id,
    authorId: entry.author_id,
    name: nameOf(entry.author_id),
    text: entry.text,
    to: entry.to,
    toName: entry.to === null ? null : nameOf(entry.to),
    mine: entry.author_id === meId,
    mentioned: mentionsMe(entry, meId),
  };
}

function loadHistory(
  feed: Feed,
  state: SessionState,
  streaming: Record<string, string>,
  meId: string | null,
): Feed {
  if (feed.history) {
    return feed;
  }
  const items: FeedItem[] = [...feed.items];
  let counter = feed.counter;
  for (const entry of state.transcript) {
    counter += 1;
    const item = fromEntry(entry, state, counter);
    if (item) {
      items.push(item);
    }
  }
  for (const [messageId, text] of Object.entries(streaming)) {
    items.push({ kind: "assistant", id: messageId, text, streaming: true });
  }
  for (const entry of state.chat) {
    items.push(chatItem(entry, state, meId));
  }
  const approvals = Object.fromEntries(Object.values(state.approvals).map((approval) => [approval.id, approval.call]));
  return { ...feed, items, counter, approvals, history: true };
}

function fromEntry(entry: TranscriptEntry, state: SessionState, counter: number): FeedItem | null {
  switch (entry.kind) {
    case "prompt": {
      const author: Participant | undefined = state.participants[entry.author_id ?? ""];
      return {
        kind: "user",
        id: entry.id,
        participantId: entry.author_id ?? "",
        name: author ? label(state, author) : (entry.author_id ?? "system"),
        role: author?.role ?? "participant",
        viaProposal: false,
        text: entry.text,
      };
    }
    case "assistant":
      // The message id, as in the live feed, so every client names the same reply the same way.
      return entry.text ? { kind: "assistant", id: entry.id, text: entry.text, streaming: false } : null;
    case "tool":
      if (entry.tool === null) {
        return null;
      }
      return {
        kind: "tool",
        id: entry.id,
        call: entry.tool,
        status: entry.ok === null ? "running" : entry.ok ? "ok" : "failed",
        output: entry.output,
        diff: null,
        live: "",
      };
    case "compaction":
      return { kind: "notice", id: `h${counter}`, tone: "dim", text: entry.text };
  }
}
