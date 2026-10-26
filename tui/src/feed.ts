import {
  label,
  type Event,
  type EventOf,
  type Participant,
  type Projection,
  type Role,
  type SessionState,
  type ToolCallView,
  type TranscriptEntry,
} from "@plural/client";
import { committableEnd } from "./lib/blocks";

export const HISTORY_ITEMS = 60;
export const TOOL_OUTPUT_LIMIT = 4000;

export type Tone = "dim" | "ok" | "warn" | "danger" | "accent";

export type FeedItem =
  | { kind: "banner"; id: string; room: string; version: string; guestLink: string | null }
  | { kind: "user"; id: string; participantId: string; name: string; role: Role; viaProposal: boolean; text: string }
  | { kind: "assistant"; id: string; text: string; first: boolean }
  | { kind: "tool"; id: string; call: ToolCallView; ok: boolean | null; output: string; diff: string | null }
  | { kind: "notice"; id: string; tone: Tone; text: string };

export interface Pending {
  messageId: string;
  text: string;
  committed: number;
  first: boolean;
}

export interface RunningTool {
  call: ToolCallView;
}

export interface Feed {
  items: FeedItem[];
  pending: Pending | null;
  tools: RunningTool[];
  approvals: Record<string, ToolCallView>;
  history: boolean;
  counter: number;
}

export function emptyFeed(): Feed {
  return { items: [], pending: null, tools: [], approvals: {}, history: false, counter: 0 };
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
    if (item?.kind === "assistant") {
      parts.unshift(item.text);
    }
  }
  const tail = feed.pending ? feed.pending.text.slice(feed.pending.committed).trim() : "";
  if (tail) {
    parts.push(tail);
  }
  return parts.join("\n\n");
}

export function withBanner(feed: Feed, banner: Extract<FeedItem, { kind: "banner" }>): Feed {
  return { ...feed, items: [banner, ...feed.items] };
}

export function absorb(feed: Feed, event: Event, projection: Projection): Feed {
  const state = projection.state;
  const next = { ...feed, items: [...feed.items] };
  const add = (item: FeedItem): void => {
    next.items.push(item);
  };
  const notice = (tone: Tone, text: string): void => {
    next.counter += 1;
    add({ kind: "notice", id: `n${next.counter}`, tone, text });
  };
  const nameOf = (participantId: string | null): string => {
    const participant = state.participants[participantId ?? ""];
    return participant ? label(state, participant) : (participantId ?? "system");
  };

  switch (event.type) {
    case "session.snapshot":
      return loadHistory(next, event.state, event.streaming);
    case "participant.joined":
      if (event.participant.id !== projection.meId) {
        notice("dim", `${label(state, event.participant)} joined as ${event.participant.role}`);
      }
      return next;
    case "participant.left":
      notice("dim", `${nameOf(event.participant_id)} left`);
      return next;
    case "participant.role_changed":
      notice("dim", `${nameOf(event.participant_id)} is now ${event.role}`);
      return next;
    case "participant.revoked":
      notice("danger", `access revoked for ${event.participant_id}`);
      return next;
    case "session.prompt_mode_changed":
      notice(
        "accent",
        event.mode === "open"
          ? "prompts are open: participants prompt the agent directly"
          : "prompts are in review: the host approves each participant prompt",
      );
      return next;
    case "proposal.created":
      notice("warn", `${nameOf(event.proposal.author_id)} proposes: ${event.proposal.text}`);
      return next;
    case "proposal.approved":
      notice("ok", `proposal approved by ${nameOf(event.decided_by)}`);
      return next;
    case "proposal.rejected":
      notice("danger", `proposal rejected by ${nameOf(event.decided_by)}`);
      return next;
    case "prompt.accepted": {
      const author = state.participants[event.author_id];
      add({
        kind: "user",
        id: event.prompt_id,
        participantId: event.author_id,
        name: author ? label(state, author) : event.author_id,
        role: author?.role ?? event.provenance.initiator_role,
        viaProposal: event.provenance.origin === "proposal",
        text: event.text,
      });
      return next;
    }
    case "run.ended":
      next.pending = null;
      next.tools = [];
      if (event.reason === "aborted") {
        notice("warn", "run aborted");
      } else if (event.reason === "error" || event.reason === "limit") {
        notice("danger", `run ${event.reason === "limit" ? "stopped" : "failed"}${event.error ? `: ${event.error}` : ""}`);
      }
      return next;
    case "message.started":
      next.pending = { messageId: event.message_id, text: "", committed: 0, first: true };
      return next;
    case "message.delta":
      if (event.thinking) {
        return next;
      }
      return streamed(next, event);
    case "message.ended":
      return endMessage(next, event);
    case "tool.started":
      next.tools = [...next.tools, { call: event.call }];
      return next;
    case "tool.ended": {
      const running = next.tools.find((tool) => tool.call.id === event.call_id);
      next.tools = next.tools.filter((tool) => tool.call.id !== event.call_id);
      if (running) {
        add({
          kind: "tool",
          id: event.call_id,
          call: running.call,
          ok: event.ok,
          output: event.output.slice(0, TOOL_OUTPUT_LIMIT),
          diff: event.diff,
        });
      }
      return next;
    }
    case "approval.requested":
      next.approvals = { ...next.approvals, [event.approval.id]: event.approval.call };
      return next;
    case "approval.resolved": {
      const call = next.approvals[event.approval_id];
      const { [event.approval_id]: _gone, ...rest } = next.approvals;
      next.approvals = rest;
      const subject = call ? `${call.name} ${call.subject}`.trim() : "tool call";
      const who = event.resolved_by === null ? "timeout" : nameOf(event.resolved_by);
      if (event.decision === "reject" || event.decision === "block") {
        notice("danger", `${subject}: ${event.decision === "block" ? "blocked" : "rejected"} (${who})`);
      } else if (event.resolved_by !== projection.meId) {
        notice("ok", `${subject}: allowed${event.decision === "always" ? " for the session" : ""} (${who})`);
      }
      return next;
    }
    case "policy.rule_added":
      notice("accent", `policy + ${event.rule.action} ${event.rule.tool} ${event.rule.pattern}  [${event.rule.id}]`);
      return next;
    case "policy.rule_removed":
      notice("accent", `policy - ${event.rule_id}`);
      return next;
    case "context.compacted":
      notice("dim", `context compacted (${event.tokens_before} tokens summarized)`);
      return next;
    case "attachment.added":
      notice("dim", `${nameOf(event.attachment.owner_id)} attached ${event.attachment.name}`);
      return next;
    case "invite.created":
      notice("ok", `invite for a ${event.role}: ${event.link}`);
      return next;
    case "error":
      notice("danger", event.message);
      return next;
    default:
      return next;
  }
}

function streamed(feed: Feed, event: EventOf<"message.delta">): Feed {
  const pending = feed.pending ?? { messageId: event.message_id, text: "", committed: 0, first: true };
  const text = pending.text + event.text;
  const end = committableEnd(text, pending.committed);
  if (end <= pending.committed) {
    return { ...feed, pending: { ...pending, text } };
  }
  const chunk = text.slice(pending.committed, end).replace(/\n+$/, "");
  const items = chunk ? [...feed.items, assistant(feed, chunk, pending.first)] : feed.items;
  return {
    ...feed,
    items,
    counter: feed.counter + 1,
    pending: { ...pending, text, committed: end, first: pending.first && !chunk },
  };
}

function endMessage(feed: Feed, event: EventOf<"message.ended">): Feed {
  const pending = feed.pending;
  const from = pending && pending.messageId === event.message_id ? pending.committed : 0;
  const first = pending && pending.messageId === event.message_id ? pending.first : true;
  const tail = event.text.slice(from).trim();
  const items = tail ? [...feed.items, assistant(feed, tail, first)] : feed.items;
  return { ...feed, items, counter: feed.counter + 1, pending: null };
}

function assistant(feed: Feed, text: string, first: boolean): FeedItem {
  return { kind: "assistant", id: `a${feed.counter + 1}`, text, first };
}

function loadHistory(feed: Feed, state: SessionState, streaming: Record<string, string>): Feed {
  const entries = feed.history ? [] : state.transcript.slice(-HISTORY_ITEMS);
  const items = [...feed.items];
  let counter = feed.counter;
  for (const entry of entries) {
    counter += 1;
    const item = fromEntry(entry, state, counter);
    if (item) {
      items.push(item);
    }
  }
  const messageId = Object.keys(streaming)[0];
  const pending: Pending | null =
    messageId === undefined
      ? null
      : { messageId, text: streaming[messageId] ?? "", committed: 0, first: true };
  const tools = state.transcript
    .filter((entry) => entry.kind === "tool" && entry.ok === null && entry.tool !== null)
    .map((entry) => ({ call: entry.tool as ToolCallView }));
  const approvals = Object.fromEntries(
    Object.values(state.approvals).map((approval) => [approval.id, approval.call]),
  );
  return { ...feed, items, counter, pending, tools, approvals, history: true };
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
      return entry.text ? { kind: "assistant", id: `h${counter}`, text: entry.text, first: true } : null;
    case "tool":
      if (entry.tool === null || entry.ok === null) {
        return null;
      }
      return { kind: "tool", id: entry.id, call: entry.tool, ok: entry.ok, output: entry.output, diff: null };
    case "compaction":
      return { kind: "notice", id: `h${counter}`, tone: "dim", text: entry.text };
  }
}
