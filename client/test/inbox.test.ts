import { expect, test } from "vitest";
import { approvalChoices, approvalDecisionFor, defaultApprovalChoice, emptyState, inboxRequests, participantName, type ApprovalView, type SessionState } from "../src";

const call = { id: "ap1", folder: null } as unknown as ApprovalView;
const folder = { id: "ap2", folder: { folder: "/srv", write: false, broad: false } } as unknown as ApprovalView;

test("requests come in one order: joins, access, briefings, approvals, proposals", () => {
  const state = {
    ...emptyState(),
    proposals: { pr1: { id: "pr1" } },
    approvals: { ap1: call },
    join_requests: { j1: { id: "j1" } },
    access_requests: { p_cleo: { participant_id: "p_cleo" } },
  } as unknown as SessionState;
  expect(inboxRequests(state).map((item) => [item.kind, item.id])).toEqual([
    ["join", "j1"],
    ["access", "p_cleo"],
    ["approval", "ap1"],
    ["proposal", "pr1"],
  ]);
});

test("a person who left is named by their id", () => {
  expect(participantName(emptyState(), "p_gone")).toBe("p_gone");
});

test("a key answers only the kind of approval it belongs to", () => {
  expect(approvalChoices(call).map((choice) => choice.decision)).toEqual(["once", "always", "reject", "block"]);
  expect(approvalDecisionFor(call, "y")).toBe("once");
  expect(approvalDecisionFor(call, "r")).toBeUndefined();
  expect(approvalDecisionFor(folder, "w")).toBe("write");
  expect(approvalDecisionFor(folder, "y")).toBeUndefined();
});

test("enter refuses a folder request until a wider answer is chosen", () => {
  expect(approvalChoices(folder)[defaultApprovalChoice(folder)]?.decision).toBe("reject");
  expect(approvalChoices(call)[defaultApprovalChoice(call)]?.decision).toBe("once");
});
