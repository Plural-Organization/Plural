import { afterEach, expect, test } from "bun:test";
import { createPrivateKey } from "node:crypto";
import { testRender } from "@opentui/react/test-utils";
import type { Session } from "@plural/client";
import { Shell } from "../src/Shell";
import { DEFAULT_SETTINGS } from "../src/settings";
import { TeamWatcher, type SessionCard, type Team } from "../src/team";
import { FakeSession, HOST } from "./support/fake-session";

type Setup = Awaited<ReturnType<typeof testRender>>;
const PEM = "-----BEGIN PRIVATE KEY-----\nMC4CAQAwBQYDK2VwBCIEIAABAgMEBQYHCAkKCwwNDg8QERITFBUWFxgZGhscHR4f\n-----END PRIVATE KEY-----\n";

const team: Team = {
  profile: { relay: "wss://r.example.com", team_id: "t_1", team_name: "Backend", team_key: "k", certificate: "C", member: { id: "m_vlad", name: "vlad", role: "owner" } },
  key: createPrivateKey(PEM),
};

const card = (owner: string, status: SessionCard["status"], branch: string | null, viewers = 0): SessionCard => ({
  room: `r_${owner}`,
  repo: "plural",
  branch,
  title: null,
  status,
  viewers,
  endpoints: [{ kind: "relay", url: `wss://r.example.com/r_${owner}` }],
  owner,
  owner_id: `m_${owner}`,
  updated_at: "2026-10-29T12:00:00Z",
});

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

async function gone(setup: Setup, text: string): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 150));
  await setup.renderOnce();
  expect(setup.captureCharFrame()).not.toContain(text);
}

function reply(fake: FakeSession, id: string, text: string): void {
  fake.emit({ type: "message.started", run_id: "r", message_id: id });
  fake.emit({ type: "message.delta", message_id: id, text, thinking: false });
  fake.emit({ type: "message.ended", run_id: "r", message_id: id, text, thinking: "" });
}

function ownSession(): FakeSession {
  const fake = new FakeSession();
  fake.emit({ type: "session.welcome", room: "r_1", token: "t", participant: HOST, base_policy: [], agent: "anthropic · claude-opus-5-5" });
  fake.emit({ type: "session.snapshot", state: { ...fake.projection.state, participants: { [HOST.id]: HOST } }, streaming: {}, typing: [] });
  return fake;
}

function visitSession(owner: string): FakeSession {
  const fake = new FakeSession();
  const me = { id: "p_team_vlad", name: "vlad", role: "viewer", connected: true } as const;
  const them = { id: "p_host", name: owner, role: "host", connected: true } as const;
  fake.emit({ type: "session.welcome", room: `r_${owner}`, token: "t", participant: me, base_policy: [], agent: "openai · gpt-5" });
  fake.emit({ type: "session.snapshot", state: { ...fake.projection.state, participants: { [me.id]: me, [them.id]: them } }, streaming: {}, typing: [] });
  reply(fake, "v1", `${owner}'s agent says hello`);
  return fake;
}

interface Mounted {
  setup: Setup;
  own: FakeSession;
  visits: Map<string, FakeSession>;
  watcher: TeamWatcher;
  connects: string[];
}

async function mount(sessions: SessionCard[], reachable = () => true): Promise<Mounted> {
  const own = ownSession();
  const visits = new Map<string, FakeSession>();
  const connects: string[] = [];
  const fetcher = (async () => {
    if (!reachable()) {
      throw new Error("connection refused");
    }
    return new Response(JSON.stringify({ sessions }));
  }) as unknown as typeof fetch;
  const watcher = new TeamWatcher(team, fetcher, 60_000);
  const setup = await testRender(
    <Shell
      team={team}
      watcher={watcher}
      home="api"
      connect={(entry): Session => {
        connects.push(entry.room);
        const fake = visitSession(entry.owner);
        visits.set(entry.room, fake);
        return fake;
      }}
      app={{ client: own, room: "r_1", version: "0.2.5", guestLink: null, settings: { ...DEFAULT_SETTINGS, setupSeen: true }, onQuit: () => undefined }}
    />,
    { width: 120, height: 40 },
  );
  open.push(setup);
  await watcher.refresh();
  return { setup, own, visits, watcher, connects };
}

async function clickRow(setup: Setup, owner: string): Promise<void> {
  const lines = setup.captureCharFrame().split("\n");
  const start = lines.findIndex((line) => line.includes("SPACES"));
  const row = lines.findIndex((line, index) => index > start && line.includes(owner) && line.indexOf(owner) > 90);
  if (row === -1) {
    throw new Error(`no row for ${owner}:\n${lines.join("\n")}`);
  }
  await setup.mockMouse.click(lines[row]!.indexOf(owner) + 1, row);
  await setup.renderOnce();
}

test("the panel lists my session and the team's with who, where and what", async () => {
  const { setup, watcher } = await mount([card("alia", "running", "feat/login", 2), card("bek", "waiting", "main"), card("vlad", "idle", "main")]);
  const text = await frame(setup, "alia");
  expect(text).toContain("SPACES · BACKEND");
  expect(text).toContain("you");
  expect(text).toContain("plural · feat/login");
  expect(text).toContain("running");
  expect(text).toContain("👁 2");
  expect(text).toContain("waiting");
  watcher.stop();
});

test("clicking a teammate opens their whole session beside mine, and clicking me comes back", async () => {
  const { setup, own, connects } = await mount([card("alia", "running", "feat/login")]);
  reply(own, "o1", "my own marker");
  await frame(setup, "my own marker");

  await clickRow(setup, "alia");
  await frame(setup, "viewing alia");
  const visiting = await frame(setup, "alia's agent says hello");
  expect(visiting).not.toContain("my own marker");
  expect(connects).toEqual(["r_alia"]);

  reply(own, "o2", "arrived while I was away");
  await clickRow(setup, "you");
  const back = await frame(setup, "arrived while I was away");
  expect(back).toContain("my own marker");
  expect(back).not.toContain("viewing alia");
  expect(back).not.toContain("alia's agent says hello");

  await clickRow(setup, "alia");
  await frame(setup, "alia's agent says hello");
  expect(connects).toEqual(["r_alia"]);
});

test("what I type goes to the session I am looking at and nowhere else", async () => {
  const { setup, own, visits } = await mount([card("alia", "idle", "main")]);
  await frame(setup, "alia");
  await clickRow(setup, "alia");
  await frame(setup, "viewing alia");
  await setup.mockInput.typeText("not for alia");
  await setup.mockInput.pressEnter();
  await new Promise((resolve) => setTimeout(resolve, 100));
  expect(own.commands).toEqual([]);
  expect(visits.get("r_alia")?.commands).toEqual([]);

  await clickRow(setup, "you");
  await frame(setup, "Message the agent");
  await setup.mockInput.typeText("for my agent");
  await setup.mockInput.pressEnter();
  await new Promise((resolve) => setTimeout(resolve, 100));
  expect(own.commands).toEqual([{ type: "prompt.submit", text: "for my agent", delivery: "now" }]);
  expect(visits.get("r_alia")?.commands).toEqual([]);
});

test("alt+right and alt+left move between spaces, ctrl+w closes the one I am in", async () => {
  const { setup, visits } = await mount([card("alia", "idle", "main"), card("bek", "idle", "main")]);
  await frame(setup, "bek");
  await setup.mockInput.pressKey("\u001b[1;3C");
  await frame(setup, "viewing alia");
  await setup.mockInput.pressKey("\u001b[1;3C");
  await frame(setup, "viewing bek");
  await setup.mockInput.pressKey("\u001b[1;3D");
  await frame(setup, "viewing alia");

  await setup.mockInput.pressKey("\u0017");
  await gone(setup, "viewing");
  expect(visits.get("r_alia")?.isClosed).toBe(true);
});

test("an empty team and an unreachable relay say so", async () => {
  let up = true;
  const { setup, watcher } = await mount([], () => up);
  await frame(setup, "SPACES · BACKEND");
  up = false;
  await watcher.refresh();
  const offline = await frame(setup, "team offline");
  expect(offline).toContain("refused");
});

test("without a team the panel has no spaces", async () => {
  const own = ownSession();
  const setup = await testRender(
    <Shell team={null} home="api" connect={() => own} app={{ client: own, room: "r_1", version: "0.2.5", guestLink: null, settings: { ...DEFAULT_SETTINGS, setupSeen: true }, onQuit: () => undefined }} />,
    { width: 120, height: 40 },
  );
  open.push(setup);
  await setup.renderOnce();
  expect(setup.captureCharFrame().toLowerCase()).not.toContain("spaces");
});

test("a file my teammate changed too is flagged on my row, theirs and in the conversation", async () => {
  const own: SessionCard = {
    ...card("vlad", "idle", "main"),
    conflicts: [{ owner: "alia", room: "r_alia", branch: "feat/x", paths: ["src/auth.py"], same_branch: false, latest: "2026-10-29T12:00:00Z" }],
  };
  const { setup } = await mount([own, card("alia", "running", "feat/x")]);
  const text = await frame(setup, "alia also changed src/auth.py");
  expect(text).toContain("⚠");
  await frame(setup, "on feat/x");
  await frame(setup, "Same file");
});

test("the panel is two halves: the people and the agent above the line, the team's rooms below it", async () => {
  const { setup, watcher } = await mount([card("vlad", "idle", "main"), card("alia", "running", "feat/login", 2)]);
  const lines = (await frame(setup, "alia")).split("\n");
  const at = (needle: string): number => lines.findIndex((line) => line.includes(needle) && line.indexOf(needle) > 90);
  const divider = lines.findIndex((line) => line.slice(90).includes("─".repeat(25)));
  expect(at("PARTICIPANTS")).toBeLessThan(at("anthropic · opus 5.5"));
  expect(at("anthropic · opus 5.5")).toBeLessThan(at("+ invite"));
  expect(at("+ invite")).toBeLessThan(divider);
  expect(divider).toBeLessThan(at("SPACES · BACKEND"));
  expect(lines[at("+ invite")]).toMatch(/\+ invite\s+menu/);
  const mine = lines.findIndex((line, index) => index > divider && line.includes("vlad (you)"));
  expect(lines[mine + 1]).toContain("plural · main");
  expect(lines.findIndex((line, index) => index > divider && line.includes("alia") && line.includes("running"))).toBeGreaterThan(mine);
  watcher.stop();
});

test("the invite button opens a dialog, and the room card makes the room link; the menu button opens the settings", async () => {
  const { setup, own, watcher } = await mount([card("alia", "idle", "main")]);
  const lines = (await frame(setup, "+ invite")).split("\n");
  const row = lines.findIndex((line) => line.includes("+ invite"));
  await setup.mockMouse.click(lines[row]!.indexOf("+ invite") + 2, row);
  const dialog = (await frame(setup, "Invite to this room")).split("\n");
  expect(own.commands).toEqual([]);
  const cardRow = dialog.findIndex((line) => line.includes("Invite to this room"));
  await setup.mockMouse.click(dialog[cardRow]!.indexOf("Invite to this room") + 2, cardRow);
  await new Promise((resolve) => setTimeout(resolve, 100));
  expect(own.commands).toEqual([{ type: "invite.create", role: "participant", ttl_s: 3600, reusable: true }]);
  await setup.mockMouse.click(lines[row]!.indexOf("menu") + 1, row);
  await frame(setup, "○ Appearance");
  watcher.stop();
});

test("a guest has no invite button", async () => {
  const fake = new FakeSession();
  const me = { id: "p_alia", name: "alia", role: "participant", connected: true } as const;
  fake.emit({ type: "session.welcome", room: "r_1", token: "t", participant: me, base_policy: [], agent: "openai · gpt-5" });
  fake.emit({ type: "session.snapshot", state: { ...fake.projection.state, participants: { [me.id]: me } }, streaming: {}, typing: [] });
  const setup = await testRender(<Shell team={null} home="api" connect={() => fake} app={{ client: fake, room: "r_1", version: "0.2.5", guestLink: null, settings: { ...DEFAULT_SETTINGS, setupSeen: true }, onQuit: () => undefined }} />, { width: 120, height: 40 });
  open.push(setup);
  const text = await frame(setup, "menu");
  expect(text).not.toContain("+ invite");
});
