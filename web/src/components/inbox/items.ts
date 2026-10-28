import { label, type ApprovalView, type JoinRequestView, type ProposalView, type SessionState } from "@plural/client";

export type InboxItem =
  | { kind: "join"; id: string; request: JoinRequestView }
  | { kind: "approval"; id: string; approval: ApprovalView }
  | { kind: "proposal"; id: string; proposal: ProposalView };

export function inboxItems(state: SessionState): InboxItem[] {
  return [
    ...Object.values(state.join_requests).map((request): InboxItem => ({ kind: "join", id: request.id, request })),
    ...Object.values(state.approvals).map((approval): InboxItem => ({ kind: "approval", id: approval.id, approval })),
    ...Object.values(state.proposals).map((proposal): InboxItem => ({ kind: "proposal", id: proposal.id, proposal })),
  ];
}

export function nameOf(state: SessionState, participantId: string): string {
  const participant = state.participants[participantId];
  return participant ? label(state, participant) : participantId;
}
