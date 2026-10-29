import type { EventRecord, SessionState, TranscriptEntry, UsageLine } from "./protocol";

export const TRANSCRIPT_LIMIT = 200;
export const OUTPUT_PREVIEW_CHARS = 2000;
export const CHAT_LIMIT = 200;
export const IMPORTS_KEPT = 10;
export const BOARD_STROKES_LIMIT = 2000;
export const BOARD_TOTAL_POINTS = 200_000;

export function emptyState(): SessionState {
  return {
    last_seq: 0,
    prompt_mode: "open",
    permission_mode: "default",
    participants: {},
    proposals: {},
    approvals: {},
    attachments: {},
    policy: [],
    skills: [],
    context: null,
    mcp: [],
    usage: [],
    agents: [],
    loaded_tools: [],
    plugins: [],
    commands: [],
    queue: [],
    agent: "",
    fast_agent: "",
    summary: null,
    run: null,
    transcript: [],
    chat: [],
    admission: "approve",
    join_requests: {},
    access_requests: {},
    briefing_sharing: "ask",
    briefing_requests: {},
    briefings_imported: [],
    board: { open: false, strokes: [] },
  };
}

// A host from an older release leaves out fields added since, such as chat.
export function withDefaults(state: SessionState): SessionState {
  return { ...emptyState(), ...state };
}

// Mirrors the host: all strokes together keep at most BOARD_TOTAL_POINTS numbers, the oldest go first.
function withinBudget<T extends { points: unknown[] }>(strokes: T[]): T[] {
  let total = strokes.reduce((sum, stroke) => sum + stroke.points.length, 0);
  let start = 0;
  while (total > BOARD_TOTAL_POINTS && start < strokes.length - 1) {
    total -= strokes[start]!.points.length;
    start += 1;
  }
  return strokes.slice(start);
}

export function reduce(state: SessionState, record: EventRecord): SessionState {
  return { ...apply(state, record), last_seq: record.seq };
}

function apply(state: SessionState, record: EventRecord): SessionState {
  const event = record.event;
  switch (event.type) {
    case "participant.joined":
      return {
        ...state,
        participants: { ...state.participants, [event.participant.id]: event.participant },
      };
    case "participant.left": {
      const left = patchParticipant(state, event.participant_id, { connected: false });
      return { ...left, briefing_requests: withoutAsker(left.briefing_requests, event.participant_id) };
    }
    case "participant.role_changed": {
      const patched = patchParticipant(state, event.participant_id, { role: event.role });
      return { ...patched, access_requests: without(patched.access_requests, event.participant_id) };
    }
    case "participant.revoked":
      return {
        ...state,
        participants: without(state.participants, event.participant_id),
        access_requests: without(state.access_requests, event.participant_id),
        briefing_requests: withoutAsker(state.briefing_requests, event.participant_id),
      };
    case "briefing.requested":
      return { ...state, briefing_requests: { ...state.briefing_requests, [event.request.id]: event.request } };
    case "briefing.resolved":
      return { ...state, briefing_requests: without(state.briefing_requests, event.request_id) };
    case "briefing.sharing_changed":
      return { ...state, briefing_sharing: event.mode };
    case "briefing.imported":
      return { ...state, briefings_imported: [...state.briefings_imported, event.item].slice(-IMPORTS_KEPT) };
    case "access.requested":
      return { ...state, access_requests: { ...state.access_requests, [event.request.participant_id]: event.request } };
    case "access.resolved":
      return { ...state, access_requests: without(state.access_requests, event.participant_id) };
    case "link.admission_changed":
      return { ...state, admission: event.mode };
    case "join.requested":
      return { ...state, join_requests: { ...state.join_requests, [event.request.id]: event.request } };
    case "join.resolved":
      return { ...state, join_requests: without(state.join_requests, event.request_id) };
    case "chat.posted":
      return {
        ...state,
        chat: [
          ...state.chat,
          {
            id: event.message_id,
            author_id: event.author_id,
            text: event.text,
            ts: record.ts,
            to: event.to,
            mentions: event.mentions,
          },
        ].slice(-CHAT_LIMIT),
      };
    case "board.opened":
      return { ...state, board: { ...state.board, open: event.open } };
    case "board.stroked":
      return { ...state, board: { ...state.board, strokes: withinBudget([...state.board.strokes, event.stroke].slice(-BOARD_STROKES_LIMIT)) } };
    case "board.moved":
      return {
        ...state,
        board: { ...state.board, strokes: state.board.strokes.map((stroke) => (stroke.id === event.stroke_id ? { ...stroke, points: event.points as typeof stroke.points } : stroke)) },
      };
    case "board.erased":
      return { ...state, board: { ...state.board, strokes: state.board.strokes.filter((stroke) => stroke.id !== event.stroke_id) } };
    case "board.cleared":
      return {
        ...state,
        board: { ...state.board, strokes: event.author_id ? state.board.strokes.filter((stroke) => stroke.author_id !== event.author_id) : [] },
      };
    case "agent.changed":
      return { ...state, agent: event.agent, fast_agent: event.fast };
    case "session.prompt_mode_changed":
      return { ...state, prompt_mode: event.mode };
    case "session.permission_mode_changed":
      return { ...state, permission_mode: event.mode };
    case "agents.changed":
      return { ...state, agents: event.agents };
    case "usage.recorded":
      return { ...state, usage: addUsage(state.usage, event.lines) };
    case "mcp.changed":
      return { ...state, mcp: event.servers };
    case "context.usage":
      return { ...state, context: event.context };
    case "skills.changed":
      return { ...state, skills: event.skills };
    case "tools.loaded":
      return { ...state, loaded_tools: [...new Set([...state.loaded_tools, ...event.tools])] };
    case "plugins.changed":
      return { ...state, plugins: event.plugins, commands: event.commands };
    case "proposal.created":
      return { ...state, proposals: { ...state.proposals, [event.proposal.id]: event.proposal } };
    case "proposal.approved":
    case "proposal.rejected":
      return { ...state, proposals: without(state.proposals, event.proposal_id) };
    case "prompt.accepted":
      return append(
        state.run === null
          ? state
          : {
              ...state,
              queue: [
                ...state.queue,
                { prompt_id: event.prompt_id, author_id: event.author_id, text: event.text, delivery: event.delivery },
              ],
            },
        {
          id: event.prompt_id,
          kind: "prompt",
          author_id: event.author_id,
          text: event.text,
          tool: null,
          ok: null,
          output: "",
        },
      );
    case "prompt.dequeued":
      return { ...state, queue: state.queue.filter((entry) => entry.prompt_id !== event.prompt_id) };
    case "run.started":
      return {
        ...state,
        run: { id: event.run_id, prompt_id: event.prompt_id, provenance: event.provenance },
      };
    case "run.ended":
      return { ...state, run: null };
    case "message.ended":
      return append(state, {
        id: event.message_id,
        kind: "assistant",
        author_id: null,
        text: event.text,
        tool: null,
        ok: null,
        output: "",
      });
    case "context.compacted":
      return append(
        { ...state, summary: event.summary },
        {
          id: record.id,
          kind: "compaction",
          author_id: null,
          text: `context compacted (${event.tokens_before} tokens summarized)`,
          tool: null,
          ok: null,
          output: "",
        },
      );
    case "tool.started":
      return append(state, {
        id: event.call.id,
        kind: "tool",
        author_id: null,
        text: "",
        tool: event.call,
        ok: null,
        output: "",
      });
    case "tool.ended":
      return {
        ...state,
        transcript: state.transcript.map((entry) =>
          entry.id === event.call_id
            ? { ...entry, ok: event.ok, output: event.output.slice(0, OUTPUT_PREVIEW_CHARS) }
            : entry,
        ),
      };
    case "approval.requested":
      return { ...state, approvals: { ...state.approvals, [event.approval.id]: event.approval } };
    case "approval.resolved":
      return { ...state, approvals: without(state.approvals, event.approval_id) };
    case "policy.rule_added":
      return { ...state, policy: [...state.policy, event.rule] };
    case "policy.rule_removed":
      return { ...state, policy: state.policy.filter((rule) => rule.id !== event.rule_id) };
    case "attachment.added":
      return {
        ...state,
        attachments: { ...state.attachments, [event.attachment.id]: event.attachment },
      };
    default:
      return state;
  }
}

function patchParticipant(
  state: SessionState,
  participantId: string,
  changes: Partial<SessionState["participants"][string]>,
): SessionState {
  const participant = state.participants[participantId];
  if (participant === undefined) {
    return state;
  }
  return {
    ...state,
    participants: { ...state.participants, [participantId]: { ...participant, ...changes } },
  };
}

function append(state: SessionState, entry: TranscriptEntry): SessionState {
  return { ...state, transcript: [...state.transcript, entry].slice(-TRANSCRIPT_LIMIT) };
}

function withoutAsker<V extends { participant_id: string }>(map: Record<string, V>, participantId: string): Record<string, V> {
  return Object.fromEntries(Object.entries(map).filter(([, ask]) => ask.participant_id !== participantId));
}

function without<V>(map: Record<string, V>, key: string): Record<string, V> {
  const { [key]: _removed, ...rest } = map;
  return rest;
}

function addUsage(total: UsageLine[], lines: UsageLine[]): UsageLine[] {
  const merged = new Map(total.map((line) => [`${line.role}\u0000${line.model}\u0000${line.agent}`, line]));
  for (const line of lines) {
    const key = `${line.role}\u0000${line.model}\u0000${line.agent}`;
    const previous = merged.get(key);
    merged.set(
      key,
      previous === undefined
        ? line
        : {
            ...previous,
            uses: previous.uses + line.uses,
            usage: {
              input_tokens: previous.usage.input_tokens + line.usage.input_tokens,
              output_tokens: previous.usage.output_tokens + line.usage.output_tokens,
              cache_read_tokens: previous.usage.cache_read_tokens + line.usage.cache_read_tokens,
              cache_write_tokens: previous.usage.cache_write_tokens + line.usage.cache_write_tokens,
            },
          },
    );
  }
  return [...merged.values()];
}
