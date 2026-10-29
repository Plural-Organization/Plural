import { afterEach, expect, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { App } from "../src/App";
import { DEFAULT_SETTINGS } from "../src/settings";
import { ALIA, FakeSession, HOST } from "./support/fake-session";

type Setup = Awaited<ReturnType<typeof testRender>>;
const CLEO = { id: "p_cleo", name: "Cleo", role: "viewer", connected: true } as const;
const NOW = "2026-10-29T12:00:00Z";

const open: Setup[] = [];
afterEach(() => {
  while (open.length > 0) {
    open.pop()?.renderer.destroy();
  }
});

function room(me: typeof HOST | typeof CLEO): FakeSession {
  const fake = new FakeSession();
  fake.emit({ type: "session.welcome", room: "r_1", token: "t", participant: me, base_policy: [], agent: "anthropic · claude-opus-5-5" });
  fake.emit({
    type: "session.snapshot",
    state: { ...fake.projection.state, participants: { [HOST.id]: HOST, [ALIA.id]: ALIA, [CLEO.id]: CLEO } },
    streaming: {},
    typing: [],
  });
  return fake;
}

async function mount(fake: FakeSession): Promise<Setup> {
  const setup = await testRender(
    <App client={fake} room="r_1" version="0.2.5" guestLink={null} settings={{ ...DEFAULT_SETTINGS, setupSeen: true }} onQuit={() => undefined} />,
    { width: 120, height: 40 },
  );
  open.push(setup);
  await setup.renderOnce();
  return setup;
}

async function frame(setup: Setup, includes: string, timeout = 3000): Promise<string> {
  const deadline = Date.now() + timeout;
  for (;;) {
    await setup.renderOnce();
    const text = setup.captureCharFrame();
    if (text.includes(includes)) {
      return text;
    }
    if (Date.now() > deadline) {
      throw new Error(`"${includes}" never appeared in:\n${text}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
}

async function say(setup: Setup, text: string): Promise<void> {
  await setup.mockInput.typeText(text);
  await setup.mockInput.pressEnter();
  await new Promise((resolve) => setTimeout(resolve, 100));
}

test("a viewer can type, is told they only watch, and /access asks the host", async () => {
  const fake = room(CLEO);
  const setup = await mount(fake);
  await frame(setup, "→ watching");
  await say(setup, "can I add a test?");
  await frame(setup, "you are only watching");
  expect(fake.commands).toEqual([]);

  await say(setup, "/team hello");
  expect(fake.commands).toEqual([]);

  await say(setup, "/access I can fix the login test");
  expect(fake.commands).toEqual([{ type: "access.request", note: "I can fix the login test" }]);
});

test("a viewer sees that they asked, and what the host answered", async () => {
  const fake = room(CLEO);
  const setup = await mount(fake);
  fake.emit({ type: "access.requested", request: { participant_id: CLEO.id, name: "Cleo", note: null, requested_at: NOW } });
  await frame(setup, "you asked the host for the right to write");
  await frame(setup, "waiting for the host");

  fake.emit({ type: "access.resolved", participant_id: CLEO.id, decision: "granted", decided_by: "p_host" });
  fake.emit({ type: "participant.role_changed", participant_id: CLEO.id, role: "participant" });
  await frame(setup, "the host let you write");
  await frame(setup, "Message the agent");
});

test("a refusal says so and the viewer stays a viewer", async () => {
  const fake = room(CLEO);
  const setup = await mount(fake);
  fake.emit({ type: "access.requested", request: { participant_id: CLEO.id, name: "Cleo", note: null, requested_at: NOW } });
  fake.emit({ type: "access.resolved", participant_id: CLEO.id, decision: "denied", decided_by: "p_host" });
  await frame(setup, "the host said no for now");
  await frame(setup, "/access asks the host");
});

test("the host gets a card, answers with y or n, and the answer goes out", async () => {
  const fake = room(HOST);
  const setup = await mount(fake);
  fake.emit({ type: "access.requested", request: { participant_id: CLEO.id, name: "Cleo", note: "I can fix the test", requested_at: NOW } });
  const card = await frame(setup, "wants to write");
  expect(card).toContain("Cleo");
  expect(card).toContain("I can fix the test");
  expect(card).toContain("Cleo asks for the right to write");

  await setup.mockInput.pressTab();
  await frame(setup, "let them write");
  await new Promise((resolve) => setTimeout(resolve, 450));
  await setup.mockInput.pressKey("y");
  await new Promise((resolve) => setTimeout(resolve, 100));
  expect(fake.commands).toEqual([{ type: "access.decide", participant_id: CLEO.id, decision: "allow" }]);
});

test("the host can refuse with n and answer by name with /access", async () => {
  const fake = room(HOST);
  const setup = await mount(fake);
  fake.emit({ type: "access.requested", request: { participant_id: CLEO.id, name: "Cleo", note: null, requested_at: NOW } });
  await frame(setup, "wants to write");
  await setup.mockInput.pressTab();
  await new Promise((resolve) => setTimeout(resolve, 450));
  await setup.mockInput.pressKey("n");
  await new Promise((resolve) => setTimeout(resolve, 100));
  expect(fake.commands.at(-1)).toEqual({ type: "access.decide", participant_id: CLEO.id, decision: "deny" });

  await setup.mockInput.pressTab();
  await say(setup, "/access allow cleo");
  expect(fake.commands.at(-1)).toEqual({ type: "access.decide", participant_id: CLEO.id, decision: "allow" });
  await say(setup, "/access revoke cleo");
  expect(fake.commands.at(-1)).toEqual({ type: "participant.set_role", participant_id: CLEO.id, role: "viewer" });
  await say(setup, "/access allow nobody");
  await frame(setup, "usage: /access");
});

test("a participant is told they can already write", async () => {
  const fake = new FakeSession();
  fake.emit({ type: "session.welcome", room: "r_1", token: "t", participant: ALIA, base_policy: [], agent: "x" });
  fake.emit({ type: "session.snapshot", state: { ...fake.projection.state, participants: { [HOST.id]: HOST, [ALIA.id]: ALIA } }, streaming: {}, typing: [] });
  const setup = await mount(fake);
  await say(setup, "/access");
  await frame(setup, "you can already write");
  expect(fake.commands).toEqual([]);
});
