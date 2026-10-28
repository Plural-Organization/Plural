import { label, shortTokens } from "./presenter";
import type { Projection } from "./projection";
import type { Event, Participant, Role, SessionState, ToolCallView, TranscriptEntry } from "./protocol";

export const TOOL_OUTPUT_LIMIT = 20_000;
export const LIVE_OUTPUT_LIMIT = 8000;

export type Tone = "dim" | "ok" | "warn" | "danger" | "accent";
export type ToolStatus = "running" | "ok" | "failed";

export type FeedItem =
  | { kind: "banner"; id: string; room: string; version: string; guestLink: string | null }
  | { kind: "user"; id: string; participantId: string; name: string; role: Role; viaProposal: boolean; text: string }
  | { kind: "assistant"; id: string; text: string; streaming: boolean }
  | { kind: "tool"; id: string; call: ToolCallView; status: ToolStatus; output: string; diff: string | null; live: string }
  | { kind: "notice"; id: string; tone: Tone; text: string };

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
      return loadHistory(feed, event.state, event.streaming);
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

function loadHistory(feed: Feed, state: SessionState, streaming: Record<string, string>): Feed {
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
      return entry.text ? { kind: "assistant", id: `h${counter}`, text: entry.text, streaming: false } : null;
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
