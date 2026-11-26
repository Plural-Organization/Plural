import { label } from "./presenter";
import type { AccessRequestView, ApprovalDecision, ApprovalView, BriefingRequestView, HandoverView, JoinRequestView, ProposalView, SessionState } from "./protocol";

// What waits for the host's answer. Each client adds its own kinds on top: the web one a plugin's question, the terminal one a finished plan.
export type InboxRequest =
  | { kind: "join"; id: string; request: JoinRequestView }
  | { kind: "access"; id: string; request: AccessRequestView }
  | { kind: "briefing"; id: string; request: BriefingRequestView }
  | { kind: "approval"; id: string; approval: ApprovalView }
  | { kind: "proposal"; id: string; proposal: ProposalView }
  | { kind: "handover"; id: string; offer: HandoverView };

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

/** The host's seat, when the host has offered it to this person and they have not answered: it waits for them, not for the host. */
export function handoverRequests(state: SessionState, meId: string | null): InboxRequest[] {
  const offer = state.handover;
  return offer !== null && !offer.accepted && meId !== null && offer.participant_id === meId ? [{ kind: "handover", id: "handover", offer }] : [];
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

// An approver the host named answers this call once or refuses it; a rule that lasts stays with the host.
const APPROVER_CHOICES: readonly ApprovalChoice[] = CALL_CHOICES.filter(({ decision }) => decision === "once" || decision === "reject");

/** What an approval may be answered with, in the order the answers are shown. `approver`: the asker is not the host. */
export function approvalChoices(approval: ApprovalView, approver = false): readonly ApprovalChoice[] {
  if (approval.folder) {
    return FOLDER_CHOICES;
  }
  return approver ? APPROVER_CHOICES : CALL_CHOICES;
}

/** The answer a key gives to this approval; a key of the other kind of approval gives none. */
export function approvalDecisionFor(approval: ApprovalView, key: string, approver = false): ApprovalDecision | undefined {
  return approvalChoices(approval, approver).find((choice) => choice.key === key)?.decision;
}

/** Whether this person is a participant the host named to approve tool calls, who is not the host. */
export function isApprover(state: SessionState, meId: string | null): boolean {
  const me = meId === null ? undefined : state.participants[meId];
  return me !== undefined && me.role === "participant" && state.approvers.includes(me.id);
}

/** The calls an approver may answer: someone else's, and never a folder outside the session. */
export function approverRequests(state: SessionState, meId: string | null): InboxRequest[] {
  return Object.values(state.approvals)
    .filter((approval) => !approval.folder && approval.provenance.initiator_id !== meId)
    .map((approval): InboxRequest => ({ kind: "approval", id: approval.id, approval }));
}

/** The answer Enter takes first. A folder request starts on the refusal, so a stray Enter opens nothing. */
export function defaultApprovalChoice(approval: ApprovalView): number {
  return approval.folder ? FOLDER_CHOICES.length - 1 : 0;
}
