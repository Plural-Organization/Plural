import { afterAll, afterEach, expect, spyOn, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { App } from "../src/App";
import * as sound from "../src/lib/sound";
import { DEFAULT_SETTINGS } from "../src/settings";
import { ALIA, CALL, FakeSession, GUEST, HOST } from "./support/fake-session";

type Setup = Awaited<ReturnType<typeof testRender>>;
const open: Setup[] = [];
const ringing = spyOn(sound, "ring").mockImplementation(() => undefined);
afterAll(() => ringing.mockRestore());
afterEach(() => {
  while (open.length) open.pop()?.renderer.destroy();
  ringing.mockClear();
});

async function mount(host = true, joinBell = true, bell = DEFAULT_SETTINGS.bell) {
  const fake = new FakeSession();
  fake.emit({ type: "session.welcome", room: "r_1", token: "t", participant: host ? HOST : ALIA, base_policy: [], agent: "test" });
  fake.emit({ type: "session.snapshot", state: { ...fake.projection.state, participants: { [HOST.id]: HOST, [ALIA.id]: ALIA } }, streaming: {}, typing: [] });
  const setup = await testRender(<App client={fake} room="r_1" version="test" guestLink={null} settings={{ ...DEFAULT_SETTINGS, setupSeen: true, bell, joinBell }} onQuit={() => undefined} />, { width: 120, height: 40 });
  open.push(setup);
  await settle(setup);
  return { fake, setup };
}

async function settle(setup: Setup) {
  await new Promise((resolve) => setTimeout(resolve, 30));
  await setup.renderOnce();
}

test("a snapshot and the host's own join are silent; a guest join alerts the host", async () => {
  const { fake, setup } = await mount();
  expect(ringing).not.toHaveBeenCalled();
  fake.emit({ type: "participant.joined", participant: HOST });
  await settle(setup);
  expect(ringing).not.toHaveBeenCalled();
  fake.emit({ type: "participant.joined", participant: ALIA });
  await settle(setup);
  expect(ringing).toHaveBeenCalledTimes(1);
  expect(setup.captureCharFrame()).toContain("Alia joined");
});

test("muting joins preserves the host's visible notification", async () => {
  const { fake, setup } = await mount(true, false);
  fake.emit({ type: "participant.joined", participant: ALIA });
  await settle(setup);
  expect(ringing).not.toHaveBeenCalled();
  expect(setup.captureCharFrame()).toContain("Alia joined");
});

test("guests do not receive the host's join alert", async () => {
  const { fake, setup } = await mount(false);
  fake.emit({ type: "participant.joined", participant: { id: "p_new", name: "Newcomer", role: "viewer", connected: true } });
  await settle(setup);
  expect(ringing).not.toHaveBeenCalled();
  expect(setup.captureCharFrame()).toContain("Newcomer joined as viewer");
});

test("tool approvals and participant proposals each ring for the host by default", async () => {
  const { fake, setup } = await mount();
  fake.emit({ type: "approval.requested", approval: { id: "ap_1", call: CALL, provenance: GUEST, timeout_at: new Date(Date.now() + 60000).toISOString(), suggested_patterns: [], warnings: [] } });
  await settle(setup);
  expect(ringing).toHaveBeenCalledTimes(1);
  fake.emit({ type: "proposal.created", proposal: { id: "pr_1", author_id: ALIA.id, text: "Please review", delivery: "now", attachments: [] } });
  await settle(setup);
  expect(ringing).toHaveBeenCalledTimes(2);
});

test("muting requests keeps approval cards visible without ringing", async () => {
  const { fake, setup } = await mount(true, true, false);
  fake.emit({ type: "approval.requested", approval: { id: "ap_1", call: CALL, provenance: GUEST, timeout_at: new Date(Date.now() + 60000).toISOString(), suggested_patterns: [], warnings: [] } });
  await settle(setup);
  expect(ringing).not.toHaveBeenCalled();
  expect(setup.captureCharFrame()).toContain("approval needed");
});

test("replacing a pending request rings even when the inbox count stays the same", async () => {
  const { fake, setup } = await mount();
  const request = { id: "j_1", name: "First", client: "web", requested_at: new Date().toISOString() };
  fake.emit({ type: "join.requested", request });
  await settle(setup);
  expect(ringing).toHaveBeenCalledTimes(1);
  fake.emit({ type: "join.resolved", request_id: "j_1", decision: "deny", decided_by: HOST.id });
  fake.emit({ type: "join.requested", request: { ...request, id: "j_2", name: "Second" } });
  await settle(setup);
  expect(ringing).toHaveBeenCalledTimes(2);
  await settle(setup);
  expect(ringing).toHaveBeenCalledTimes(2);
});
