import { afterEach, expect, test } from "bun:test";
import { createPrivateKey } from "node:crypto";
import { testRender } from "@opentui/react/test-utils";
import { TeamWatcher, type Session, type SessionCard } from "@plural/client";
import { App } from "../src/App";
import { Shell } from "../src/Shell";
import { DEFAULT_SETTINGS } from "../src/settings";
import { fetchSessions, type Team } from "../src/team";
import { ALIA, FakeSession, HOST } from "./support/fake-session";

type Setup = Awaited<ReturnType<typeof testRender>>;
const CLEO = { id: "p_cleo", name: "Cleo", role: "viewer", connected: true } as const;
const NOW = "2026-10-29T12:00:00Z";
const PEM = "-----BEGIN PRIVATE KEY-----\nMC4CAQAwBQYDK2VwBCIEIAABAgMEBQYHCAkKCwwNDg8QERITFBUWFxgZGhscHR4f\n-----END PRIVATE KEY-----\n";
const BRIEFING = "Briefing from alia's session, as of event 42.\n\nGoal: fix login. Done: added a retry in login.py.";

const open: Setup[] = [];
afterEach(() => {
  while (open.length > 0) {
    open.pop()?.renderer.destroy();
  }
});

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

function room(me: typeof HOST | typeof CLEO | typeof ALIA, peers: Record<string, unknown> = {}): FakeSession {
  const fake = new FakeSession();
  fake.emit({ type: "session.welcome", room: "r_1", token: "t", participant: me, base_policy: [], agent: "x" });
  fake.emit({ type: "session.snapshot", state: { ...fake.projection.state, participants: { [HOST.id]: HOST, [ALIA.id]: ALIA, [CLEO.id]: CLEO, ...peers } }, streaming: {}, typing: [] } as never);
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

test("a viewer asks for a briefing, optionally about something, and for an update", async () => {
  const fake = room(CLEO);
  const setup = await mount(fake);
  await say(setup, "/brief how was the login fixed?");
  await say(setup, "/brief update");
  await say(setup, "/brief update what is left?");
  expect(fake.commands).toEqual([
    { type: "briefing.request", focus: "how was the login fixed?", update: false },
    { type: "briefing.request", focus: null, update: true },
    { type: "briefing.request", focus: "what is left?", update: true },
  ]);
});

test("the briefing arrives as a card with where it is from and how fresh, and says how to use it", async () => {
  const fake = room(CLEO);
  const setup = await mount(fake);
  fake.emit({ type: "briefing.requested", request: { id: "b_1", participant_id: CLEO.id, name: "Cleo", focus: null, update: false, requested_at: NOW } });
  await frame(setup, "waiting for the host");
  fake.emit({ type: "briefing.resolved", request_id: "b_1", participant_id: CLEO.id, decision: "granted", decided_by: "p_host" });
  await frame(setup, "being written");
  fake.emit({ type: "briefing.delivered", request_id: "b_1", to: CLEO.id, text: BRIEFING, as_of_seq: 42, update: false, error: null });
  const card = await frame(setup, "answer from vlad");
  expect(card).toContain("as of event 42");
  expect(card).toContain("Goal: fix login. Done: added a retry in login.py.");
  expect(card).toContain("give to my agent");
});

test("a refusal and a failure are told plainly", async () => {
  const fake = room(CLEO);
  const setup = await mount(fake);
  fake.emit({ type: "briefing.resolved", request_id: "b_1", participant_id: CLEO.id, decision: "denied", decided_by: "p_host" });
  await frame(setup, "the host said no to the briefing");
  fake.emit({ type: "briefing.delivered", request_id: "b_2", to: CLEO.id, text: "", as_of_seq: 5, update: false, error: "the model could not write it" });
  await frame(setup, "the briefing could not be written: the model could not write it");
});

test("the host gets a card for the request and answers with y", async () => {
  const fake = room(HOST);
  const setup = await mount(fake);
  fake.emit({ type: "briefing.requested", request: { id: "b_1", participant_id: CLEO.id, name: "Cleo", focus: "what is left?", update: true, requested_at: NOW } });
  const card = await frame(setup, "wants a briefing");
  expect(card).toContain("Cleo");
  expect(card).toContain("what is left?");
  expect(card).toContain("an update");
  await setup.mockInput.pressTab();
  await frame(setup, "write it");
  await new Promise((resolve) => setTimeout(resolve, 450));
  await setup.mockInput.pressKey("y");
  await new Promise((resolve) => setTimeout(resolve, 100));
  expect(fake.commands).toEqual([{ type: "briefing.decide", request_id: "b_1", decision: "allow" }]);
});

test("the host sets who may ask and sees the setting", async () => {
  const fake = room(HOST);
  const setup = await mount(fake);
  await say(setup, "/brief share team");
  expect(fake.commands).toEqual([{ type: "session.set_briefing_sharing", mode: "team" }]);
  await say(setup, "/brief");
  await frame(setup, "this session shares briefings: ask");
  fake.emit({ type: "briefing.sharing_changed", mode: "off" });
  await frame(setup, "this session shares no briefings");
});

test("giving a briefing outside a visit explains where it goes", async () => {
  const fake = room(CLEO);
  const setup = await mount(fake);
  fake.emit({ type: "briefing.delivered", request_id: "b_1", to: CLEO.id, text: BRIEFING, as_of_seq: 42, update: false, error: null });
  await frame(setup, "answer from vlad");
  await say(setup, "/brief give");
  await frame(setup, "goes to your own agent");
  await say(setup, "/brief give");
});

const team: Team = {
  profile: { relay: "wss://r.example.com", team_id: "t_1", team_name: "Backend", team_key: "k", certificate: "C", member: { id: "m_vlad", name: "vlad", role: "owner" } },
  key: createPrivateKey(PEM),
};

const alia: SessionCard = {
  room: "r_alia",
  repo: "plural",
  branch: "main",
  title: null,
  status: "idle",
  viewers: 0,
  endpoints: [{ kind: "relay", url: "wss://r.example.com/r_alia" }],
  owner: "alia",
  owner_id: "m_alia",
  updated_at: NOW,
};

test("from a teammate's session /ask give puts the answer in my own agent's notes", async () => {
  const own = room(HOST);
  const visit = new FakeSession();
  const me = { id: "p_team_vlad", name: "vlad", role: "viewer", connected: true } as const;
  const them = { id: "p_host", name: "alia", role: "host", connected: true } as const;
  visit.emit({ type: "session.welcome", room: "r_alia", token: "t", participant: me, base_policy: [], agent: "openai · gpt-5" });
  visit.emit({ type: "session.snapshot", state: { ...visit.projection.state, participants: { [me.id]: me, [them.id]: them } }, streaming: {}, typing: [] });
  const fetcher = (async () => new Response(JSON.stringify({ sessions: [alia] }))) as unknown as typeof fetch;
  const watcher = new TeamWatcher(team.profile, () => fetchSessions(team, fetcher), 60_000);
  const setup = await testRender(
    <Shell
      team={team}
      watcher={watcher}
      home="api"
      connect={(): Session => visit}
      app={{ client: own, room: "r_1", version: "0.2.5", guestLink: null, settings: { ...DEFAULT_SETTINGS, setupSeen: true }, onQuit: () => undefined }}
    />,
    { width: 120, height: 40 },
  );
  open.push(setup);
  await watcher.refresh();
  await frame(setup, "alia");
  const lines = setup.captureCharFrame().split("\n");
  const start = lines.findIndex((line) => line.includes("SPACES"));
  const row = lines.findIndex((line, index) => index > start && line.includes("alia") && line.indexOf("alia") > 90);
  await setup.mockMouse.click(lines[row]!.indexOf("alia") + 1, row);
  await frame(setup, "viewing alia");

  visit.emit({ type: "briefing.delivered", request_id: "b_1", to: me.id, text: BRIEFING, as_of_seq: 42, update: false, error: null });
  await frame(setup, "answer from alia");
  await say(setup, "/ask give");
  await frame(setup, "is in your agent's notes");
  expect(own.commands).toEqual([{ type: "briefing.import", source: "alia", as_of_seq: 42, text: BRIEFING }]);
  expect(visit.commands).toEqual([]);

  own.emit({ type: "briefing.imported", item: { id: "bi_1", source: "alia", as_of_seq: 42, chars: BRIEFING.length, at: NOW }, text: BRIEFING });
  watcher.stop();
});

// Asking a teammate without opening their session: the courier.
function teammate(): FakeSession {
  const visit = new FakeSession();
  const me = { id: "p_team_vlad", name: "vlad", role: "viewer", connected: true } as const;
  const them = { id: "p_host", name: "alia", role: "host", connected: true } as const;
  visit.emit({ type: "session.welcome", room: "r_alia", token: "t", participant: me, base_policy: [], agent: "openai · gpt-5" });
  visit.emit({ type: "session.snapshot", state: { ...visit.projection.state, participants: { [me.id]: me, [them.id]: them } }, streaming: {}, typing: [] });
  return visit;
}

async function mountTeam(connect: () => Session, sessions: SessionCard[] = [alia]): Promise<{ setup: Setup; own: FakeSession; watcher: TeamWatcher }> {
  const own = room(HOST);
  const fetcher = (async () => new Response(JSON.stringify({ sessions }))) as unknown as typeof fetch;
  const watcher = new TeamWatcher(team.profile, () => fetchSessions(team, fetcher), 60_000);
  const setup = await testRender(
    <Shell
      team={team}
      watcher={watcher}
      home="api"
      connect={connect}
      app={{ client: own, room: "r_1", version: "0.2.5", guestLink: null, settings: { ...DEFAULT_SETTINGS, setupSeen: true }, onQuit: () => undefined }}
    />,
    { width: 120, height: 40 },
  );
  open.push(setup);
  await watcher.refresh();
  await frame(setup, "alia");
  return { setup, own, watcher };
}

test("/ask @name asks a teammate's agent from my own session, and the answer comes to my chat", async () => {
  const visit = teammate();
  const { setup, own, watcher } = await mountTeam(() => visit);
  await say(setup, "/ask @alia how does /orders work?");
  await frame(setup, "asking @alia: how does /orders work?");
  expect(visit.commands).toEqual([{ type: "briefing.request", focus: "how does /orders work?", update: false }]);
  visit.emit({ type: "briefing.requested", request: { id: "b_1", participant_id: "p_team_vlad", name: "vlad", focus: null, update: false, requested_at: NOW } });
  await frame(setup, "waiting for alia to agree");
  visit.emit({ type: "briefing.resolved", request_id: "b_1", participant_id: "p_team_vlad", decision: "granted", decided_by: "p_host" });
  await frame(setup, "alia agreed");
  visit.emit({ type: "briefing.delivered", request_id: "b_1", to: "p_team_vlad", text: BRIEFING, as_of_seq: 42, update: false, error: null });
  const card = await frame(setup, "answer from alia");
  expect(card).toContain("Goal: fix login.");
  expect(visit.isClosed).toBe(true);
  expect(own.commands).toEqual([]);

  await say(setup, "/ask give");
  await frame(setup, "is in your agent's notes");
  expect(own.commands).toEqual([{ type: "briefing.import", source: "alia", as_of_seq: 42, text: BRIEFING }]);
  watcher.stop();
});

test("the card's own button gives the answer to my agent", async () => {
  const visit = teammate();
  const { setup, own, watcher } = await mountTeam(() => visit);
  await say(setup, "/ask @alia --update");
  expect(visit.commands).toEqual([{ type: "briefing.request", focus: null, update: true }]);
  visit.emit({ type: "briefing.delivered", request_id: "b_1", to: "p_team_vlad", text: BRIEFING, as_of_seq: 7, update: true, error: null });
  const card = await frame(setup, "give to my agent");
  const lines = card.split("\n");
  const row = lines.findIndex((line) => line.includes("give to my agent"));
  await setup.mockMouse.click(lines[row]!.indexOf("give to my agent") + 1, row);
  await frame(setup, "is in your agent's notes");
  expect(own.commands).toEqual([{ type: "briefing.import", source: "alia", as_of_seq: 7, text: BRIEFING }]);
  watcher.stop();
});

test("a teammate who is not sharing, or who says no, is told in plain words", async () => {
  const visit = teammate();
  const { setup, watcher } = await mountTeam(() => visit);
  await say(setup, "/ask @bek what is up?");
  await frame(setup, "bek is not sharing a session right now");
  await say(setup, "/ask @alia hello");
  visit.emit({ type: "briefing.resolved", request_id: "b_1", participant_id: "p_team_vlad", decision: "denied", decided_by: "p_host" });
  await frame(setup, "alia said no to the briefing");
  watcher.stop();
});

test("outside a team /ask says what it needs", async () => {
  const fake = room(HOST);
  const setup = await mount(fake);
  await say(setup, "/ask @alia hello");
  await frame(setup, "once you are in a team");
  expect(fake.commands).toEqual([]);
});

test("typing @ after /ask lists the people who share a session, with where they are", async () => {
  const visit = teammate();
  const { setup, watcher } = await mountTeam(() => visit, [alia, { ...alia, owner: "bek", owner_id: "m_bek", room: "r_bek", branch: "feat/x", status: "running" }]);
  await setup.mockInput.typeText("/ask @");
  const hints = await frame(setup, "@bek");
  expect(hints).toContain("@alia");
  expect(hints).toContain("plural · feat/x · running");
  await setup.mockInput.typeText("b");
  await new Promise((resolve) => setTimeout(resolve, 150));
  await setup.renderOnce();
  await setup.mockInput.pressTab();
  await frame(setup, "❯ /ask @bek");
  watcher.stop();
});
