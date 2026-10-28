import type { EventRecord, SessionState, TranscriptEntry } from "./protocol";

export const TRANSCRIPT_LIMIT = 200;
export const OUTPUT_PREVIEW_CHARS = 2000;
export const CHAT_LIMIT = 200;

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
    queue: [],
    agent: "",
    summary: null,
    run: null,
    transcript: [],
    chat: [],
    admission: "approve",
    join_requests: {},
  };
}

// A host from an older release leaves out fields added since, such as chat.
export function withDefaults(state: SessionState): SessionState {
  return { ...emptyState(), ...state };
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
    case "participant.left":
      return patchParticipant(state, event.participant_id, { connected: false });
    case "participant.role_changed":
      return patchParticipant(state, event.participant_id, { role: event.role });
    case "participant.revoked":
      return { ...state, participants: without(state.participants, event.participant_id) };
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
    case "agent.changed":
      return { ...state, agent: event.agent };
    case "session.prompt_mode_changed":
      return { ...state, prompt_mode: event.mode };
    case "session.permission_mode_changed":
      return { ...state, permission_mode: event.mode };
    case "mcp.changed":
      return { ...state, mcp: event.servers };
    case "context.usage":
      return { ...state, context: event.context };
    case "skills.changed":
      return { ...state, skills: event.skills };
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

function without<V>(map: Record<string, V>, key: string): Record<string, V> {
  const { [key]: _removed, ...rest } = map;
  return rest;
}
