import type { EventRecord, SessionState } from "../protocol/types";

export const initialState: SessionState = {
  last_seq: 0,
  participants: {},
  proposals: {},
  approvals: {},
  attachments: {},
  run: null,
  transcript: [],
};

const without = <V>(map: Record<string, V>, key: string): Record<string, V> => {
  const { [key]: _, ...rest } = map;
  return rest;
};

export function reduce(state: SessionState, record: EventRecord): SessionState {
  const event = record.event;
  const next = ((): SessionState => {
    switch (event.type) {
      case "participant.joined":
        return { ...state, participants: { ...state.participants, [event.participant.id]: event.participant } };
      case "participant.revoked":
        return { ...state, participants: without(state.participants, event.participant_id) };
      case "proposal.created":
        return { ...state, proposals: { ...state.proposals, [event.proposal.id]: event.proposal } };
      case "proposal.approved":
      case "proposal.rejected":
        return { ...state, proposals: without(state.proposals, event.proposal_id) };
      case "approval.requested":
        return { ...state, approvals: { ...state.approvals, [event.approval.id]: event.approval } };
      case "approval.resolved":
        return { ...state, approvals: without(state.approvals, event.approval_id) };
      case "run.started":
        return { ...state, run: { id: event.run_id, prompt_id: event.prompt_id, provenance: event.provenance } };
      case "run.ended":
        return { ...state, run: null };
      default:
        return state;
    }
  })();
  return { ...next, last_seq: record.seq };
}
