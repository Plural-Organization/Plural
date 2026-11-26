import { describe, expect, test } from "vitest";
import { approvalChoices, approvalDecisionFor, approverRequests, emptyState, isApprover, reduce } from "../src";
import type { ApprovalView, Event, SessionState } from "../src";

const fold = (state: SessionState, event: object, seq: number): SessionState =>
  reduce(state, { seq, id: `e${seq}`, ts: "2026-11-26T00:00:00Z", actor_id: null, event: event as Event });

const ASKING = (id: string, initiator: string, folder = false): ApprovalView =>
  ({
    id,
    call: { id: "c1", name: "bash", risk: "exec", subject: "make test", args: {} },
    provenance: { initiator_id: initiator, initiator_role: "participant", origin: "direct" },
    timeout_at: "2026-11-26T00:05:00Z",
    suggested_patterns: [],
    warnings: [],
    folder: folder ? { folder: "/etc", write: false, broad: false } : null,
  }) as ApprovalView;

function room(over: Partial<SessionState> = {}): SessionState {
  return {
    ...emptyState(),
    participants: {
      p_host: { id: "p_host", name: "Host", role: "host", connected: true },
      p_alia: { id: "p_alia", name: "Alia", role: "participant", connected: true },
      p_bek: { id: "p_bek", name: "Bek", role: "participant", connected: true },
      p_cleo: { id: "p_cleo", name: "Cleo", role: "viewer", connected: true },
    },
    ...over,
  };
}

describe("approvers", () => {
  test("only a named participant is an approver", () => {
    const state = room({ approvers: ["p_bek", "p_cleo"] });
    expect(isApprover(state, "p_bek")).toBe(true);
    expect(isApprover(state, "p_alia")).toBe(false);
    expect(isApprover(state, "p_cleo")).toBe(false);
    expect(isApprover(state, null)).toBe(false);
  });

  test("an approver sees other people's calls, never their own or a folder outside the session", () => {
    const state = room({
      approvers: ["p_bek"],
      approvals: { a1: ASKING("a1", "p_alia"), a2: ASKING("a2", "p_bek"), a3: ASKING("a3", "p_alia", true) },
    });
    expect(approverRequests(state, "p_bek").map((item) => item.id)).toEqual(["a1"]);
  });

  test("an approver answers once or refuses, and has no key for a rule", () => {
    const approval = ASKING("a1", "p_alia");
    expect(approvalChoices(approval, true).map((choice) => choice.decision)).toEqual(["once", "reject"]);
    expect(approvalChoices(approval).map((choice) => choice.decision)).toEqual(["once", "always", "reject", "block"]);
    expect(approvalDecisionFor(approval, "a", true)).toBeUndefined();
    expect(approvalDecisionFor(approval, "y", true)).toBe("once");
    expect(approvalDecisionFor(approval, "a")).toBe("always");
  });

  test("the reducer names and unnames an approver, and a lost seat or right to write ends it", () => {
    const named = fold(room(), { type: "approver.changed", participant_id: "p_bek", enabled: true }, 1);
    expect(named.approvers).toEqual(["p_bek"]);
    const twice = fold(named, { type: "approver.changed", participant_id: "p_bek", enabled: true }, 2);
    expect(twice.approvers).toEqual(["p_bek"]);
    const demoted = fold(twice, { type: "participant.role_changed", participant_id: "p_bek", role: "viewer" }, 3);
    expect(demoted.approvers).toEqual([]);
    const kicked = fold(twice, { type: "participant.revoked", participant_id: "p_bek" }, 4);
    expect(kicked.approvers).toEqual([]);
    const off = fold(twice, { type: "approver.changed", participant_id: "p_bek", enabled: false }, 5);
    expect(off.approvers).toEqual([]);
  });
});
