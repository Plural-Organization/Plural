import { afterEach, expect, test } from "bun:test";
import { createPrivateKey } from "node:crypto";
import { testRender } from "@opentui/react/test-utils";
import { App } from "../src/App";
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

async function mount(watcher: TeamWatcher | undefined): Promise<Setup> {
  const fake = new FakeSession();
  fake.emit({ type: "session.welcome", room: "r_1", token: "t", participant: HOST, base_policy: [], agent: "anthropic · claude-opus-5-5" });
  fake.emit({ type: "session.snapshot", state: { ...fake.projection.state, participants: { [HOST.id]: HOST } }, streaming: {}, typing: [] });
  const setup = await testRender(
    <App client={fake} room="r_1" version="0.2.5" guestLink={null} team={watcher} settings={{ ...DEFAULT_SETTINGS, setupSeen: true }} onQuit={() => undefined} />,
    { width: 120, height: 40 },
  );
  open.push(setup);
  return setup;
}

test("the side panel lists the team's live sessions with who, where and what", async () => {
  const sessions = [card("alia", "running", "feat/login", 2), card("bek", "waiting", "main"), card("cleo", "idle", null), card("vlad", "idle", "main")];
  const fetcher = (async () => new Response(JSON.stringify({ sessions }))) as unknown as typeof fetch;
  const watcher = new TeamWatcher(team, fetcher, 60_000);
  const setup = await mount(watcher);
  watcher.start();
  const text = await frame(setup, "alia");
  expect(text).toContain("TEAM · BACKEND");
  expect(text).toContain("plural · feat/login");
  expect(text).toContain("running");
  expect(text).toContain("👁 2");
  expect(text).toContain("bek");
  expect(text).toContain("waiting");
  expect(text).toContain("vlad (you)");
  watcher.stop();
});

test("an empty team says nobody shares, and an unreachable relay says so", async () => {
  let reachable = true;
  const fetcher = (async () => {
    if (!reachable) {
      throw new Error("connection refused");
    }
    return new Response(JSON.stringify({ sessions: [] }));
  }) as unknown as typeof fetch;
  const watcher = new TeamWatcher(team, fetcher, 60_000);
  const setup = await mount(watcher);
  await watcher.refresh();
  await frame(setup, "nobody shares a session");
  reachable = false;
  await watcher.refresh();
  const offline = await frame(setup, "team offline");
  expect(offline).toContain("refused");
});

test("without a team there is no team section", async () => {
  const setup = await mount(undefined);
  await setup.renderOnce();
  expect(setup.captureCharFrame().toLowerCase()).not.toContain("team ·");
});
