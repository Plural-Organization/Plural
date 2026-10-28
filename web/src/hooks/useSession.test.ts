import { afterEach, expect, test, vi } from "vitest";
import { parseLink, SessionClient, type Event, type Role } from "@plural/client";
import { SessionStore } from "./useSession";
import { alertNotice } from "../lib/alert";

vi.mock("../lib/alert", () => ({ alertMention: vi.fn(), alertNotice: vi.fn() }));
vi.mock("../lib/saved", () => ({ forgetRoom: vi.fn(), rememberRoom: vi.fn() }));
afterEach(() => { vi.restoreAllMocks(); vi.clearAllMocks(); });

const requests: Event[] = [
  { type: "approval.requested", approval: { id: "ap_1", call: { id: "t1", name: "bash", risk: "exec", subject: "ls", args: {} }, provenance: { initiator_id: "p_guest", initiator_role: "participant", origin: "direct" }, timeout_at: "2026-10-28T23:00:00Z", suggested_patterns: [] } },
  { type: "proposal.created", proposal: { id: "pr_1", author_id: "p_guest", text: "Review this", delivery: "now", attachments: [] } },
  { type: "join.requested", request: { id: "j_1", name: "Newcomer", client: "web", requested_at: "2026-10-28T22:00:00Z" } },
];

async function deliver(role: Role, events: Event[]) {
  let done = false;
  vi.spyOn(SessionClient.prototype, "events").mockImplementation(async function* (this: SessionClient) {
    this.projection.meId = "p_me";
    this.projection.state = { ...this.projection.state, participants: { p_me: { id: "p_me", name: "Me", role, connected: true } } };
    let seq = 0;
    for (const event of events) {
      this.projection.apply({ seq: ++seq, id: `e${seq}`, ts: "2026-10-28T22:00:00Z", actor_id: null, event });
      yield event;
    }
    done = true;
  });
  const failure = vi.fn();
  const store = new SessionStore(parseLink("ws://localhost/r_1?token=test"), "Me", failure);
  const close = store.start();
  try {
    await vi.waitFor(() => expect(done).toBe(true));
    expect(failure).not.toHaveBeenCalled();
  } finally { close(); }
}

test("the web host hears tool approvals, participant proposals, and join requests", async () => {
  await deliver("host", requests);
  expect(alertNotice).toHaveBeenCalledTimes(3);
  expect(alertNotice).toHaveBeenCalledWith("A request needs your attention");
});

test.each(["participant", "viewer"] as const)("%s does not hear approval requests they cannot decide", async (role) => {
  await deliver(role, requests);
  expect(alertNotice).not.toHaveBeenCalled();
});

test("a guest joining alerts the web host, while the host's own join does not", async () => {
  await deliver("host", [
    { type: "participant.joined", participant: { id: "p_me", name: "Me", role: "host", connected: true } },
    { type: "participant.joined", participant: { id: "p_guest", name: "Alia", role: "participant", connected: true } },
  ]);
  expect(alertNotice).toHaveBeenCalledExactlyOnceWith("Alia joined");
});
