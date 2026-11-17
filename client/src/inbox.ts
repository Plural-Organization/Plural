import { label } from "./presenter";
import type { AccessRequestView, ApprovalDecision, ApprovalView, BriefingRequestView, JoinRequestView, ProposalView, SessionState } from "./protocol";

// What waits for the host's answer. Each client adds its own kinds on top: the web one a plugin's question, the terminal one a finished plan.
export type InboxRequest =
  | { kind: "join"; id: string; request: JoinRequestView }
  | { kind: "access"; id: string; request: AccessRequestView }
  | { kind: "briefing"; id: string; request: BriefingRequestView }
  | { kind: "approval"; id: string; approval: ApprovalView }
  | { kind: "proposal"; id: string; proposal: ProposalView };

/** Everything in the session that waits for the host, in the order both clients show it. */
export function inboxRequests(state: SessionState): InboxRequest[] {
  return [
    ...Object.values(state.join_requests).map((request): InboxRequest => ({ kind: "join", id: request.id, request })),
    ...Object.values(state.access_requests).map((request): InboxRequest => ({ kind: "access", id: request.participant_id, request })),
    ...Object.values(state.briefing_requests).map((request): InboxRequest => ({ kind: "briefing", id: request.id, request })),
    ...Object.values(state.approvals).map((approval): InboxRequest => ({ kind: "approval", id: approval.id, approval })),
    ...Object.values(state.proposals).map((proposal): InboxRequest => ({ kind: "proposal", id: proposal.id, proposal })),
  ];
}

/** The name a person is shown under, or their id when they are not in the session any more. */
export function participantName(state: SessionState, participantId: string): string {
  const participant = state.participants[participantId];
  return participant ? label(state, participant) : participantId;
}

export interface ApprovalChoice {
  decision: ApprovalDecision;
  /** The key that gives this answer. */
  key: string;
}

const CALL_CHOICES: readonly ApprovalChoice[] = [
  { decision: "once", key: "y" },
  { decision: "always", key: "a" },
  { decision: "reject", key: "n" },
  { decision: "block", key: "b" },
];

// A folder outside the session is answered with how far it opens, or not at all.
const FOLDER_CHOICES: readonly ApprovalChoice[] = [
  { decision: "read", key: "r" },
  { decision: "write", key: "w" },
  { decision: "reject", key: "n" },
];

/** What an approval may be answered with, in the order the answers are shown. */
export function approvalChoices(approval: ApprovalView): readonly ApprovalChoice[] {
  return approval.folder ? FOLDER_CHOICES : CALL_CHOICES;
}

/** The answer a key gives to this approval; a key of the other kind of approval gives none. */
export function approvalDecisionFor(approval: ApprovalView, key: string): ApprovalDecision | undefined {
  return approvalChoices(approval).find((choice) => choice.key === key)?.decision;
}

/** The answer Enter takes first. A folder request starts on the refusal, so a stray Enter opens nothing. */
export function defaultApprovalChoice(approval: ApprovalView): number {
  return approval.folder ? FOLDER_CHOICES.length - 1 : 0;
}
