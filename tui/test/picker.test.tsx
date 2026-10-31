import { afterEach, expect, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import type { JoinedRoom } from "../src/joined";
import { Picker, rowsFor, type Pick } from "../src/picker";
import type { SessionInfo } from "../src/sessions";

type Setup = Awaited<ReturnType<typeof testRender>>;
const open: Setup[] = [];
afterEach(() => {
  while (open.length > 0) {
    open.pop()?.renderer.destroy();
  }
});

const NOW = new Date("2026-10-28T13:00:00Z");

function info(room: string, title: string, workspace: string, updated: string, prompts = 3, people = 1, team: string | null = null): SessionInfo {
  return { room, title, workspace, host_name: "vlad", team, created_at: updated, updated_at: updated, prompts, people };
}

const SESSIONS = [
  info("r_01A", "fix the login bug", "/work/app", "2026-10-28T12:30:00Z", 4, 2, "Backend"),
  info("r_01B", "refactor auth", "/work/app", "2026-10-28T09:00:00Z"),
  info("r_01C", "billing report", "/work/shop", "2026-10-26T09:00:00Z"),
];
const JOINED: JoinedRoom[] = [{ room: "r_01JOINEDROOM0001", url: "wss://r.example.com/r_01JOINEDROOM0001", token: "t", name: "alia", savedAt: "2026-10-28T11:00:00Z" }];

async function mount(sessions = SESSIONS, joined = JOINED, folder = "/work/app"): Promise<{ setup: Setup; chosen: (Pick | null)[] }> {
  const chosen: (Pick | null)[] = [];
  const setup = await testRender(<Picker sessions={sessions} joined={joined} folder={folder} onChoose={(pick) => chosen.push(pick)} />, { width: 100, height: 24 });
  open.push(setup);
  await setup.renderOnce();
  return { setup, chosen };
}

const tick = (ms = 60) => new Promise((resolve) => setTimeout(resolve, ms));

test("rows say how long ago, how many prompts and people and which folder", () => {
  const rows = rowsFor(SESSIONS, JOINED, null, NOW);
  expect(rows[0]?.title).toBe("fix the login bug");
  expect(rows[0]?.detail).toBe("30m ago · 4 prompts · 2 people · /work/app");
  expect(rows[1]?.detail).toBe("4h ago · 3 prompts · /work/app");
  expect(rows[3]?.title).toContain("joined room r_01JOINEDROOM");
  expect(rows[3]?.detail).toContain("as alia");
});

test("every row says how the session was raised: in a team, private, or joined", async () => {
  const rows = rowsFor(SESSIONS, JOINED, null, NOW);
  expect(rows.map((row) => row.badge)).toEqual(["◆ team Backend", "○ private", "○ private", "↗ joined"]);
  const { setup } = await mount();
  const frame = setup.captureCharFrame();
  expect(frame).toContain("◆ team Backend");
  expect(frame).toContain("○ private");
  expect(frame).toContain("↗ joined");
});

test("typing the team's name finds its sessions", async () => {
  const { setup } = await mount();
  await setup.mockInput.typeText("backend");
  await tick();
  await setup.renderOnce();
  const frame = setup.captureCharFrame();
  expect(frame).toContain("fix the login bug");
  expect(frame).not.toContain("refactor auth");
});

test("the folder's sessions come first and the rooms I joined follow", async () => {
  const { setup } = await mount();
  const frame = setup.captureCharFrame();
  expect(frame).toContain("resume a session");
  expect(frame).toContain("/work/app");
  expect(frame).toContain("fix the login bug");
  expect(frame).toContain("refactor auth");
  expect(frame).toContain("joined room");
  expect(frame).not.toContain("billing report");
});

test("tab shows every folder and shows the folder again", async () => {
  const { setup } = await mount();
  await setup.mockInput.pressTab();
  await tick();
  await setup.renderOnce();
  expect(setup.captureCharFrame()).toContain("billing report");
  expect(setup.captureCharFrame()).toContain("all folders");
  await setup.mockInput.pressTab();
  await tick();
  await setup.renderOnce();
  expect(setup.captureCharFrame()).not.toContain("billing report");
});

test("arrows move and enter chooses that session", async () => {
  const { setup, chosen } = await mount();
  await setup.mockInput.pressArrow("down");
  await setup.mockInput.pressEnter();
  await tick();
  expect(chosen).toHaveLength(1);
  expect(chosen[0]).toMatchObject({ kind: "host", info: { room: "r_01B" } });
  void setup;
});

test("the first one is chosen when nothing is pressed but enter", async () => {
  const { setup, chosen } = await mount();
  await setup.mockInput.pressEnter();
  await tick();
  expect(chosen[0]).toMatchObject({ kind: "host", info: { room: "r_01A" } });
});

test("typing filters and a room I joined can be chosen", async () => {
  const { setup, chosen } = await mount();
  await setup.mockInput.typeText("joined");
  await tick();
  await setup.renderOnce();
  expect(setup.captureCharFrame()).toContain("filter: joined");
  expect(setup.captureCharFrame()).not.toContain("fix the login bug");
  await setup.mockInput.pressEnter();
  await tick();
  expect(chosen[0]).toMatchObject({ kind: "joined", room: { room: "r_01JOINEDROOM0001" } });
});

test("a filter that matches nothing says so and enter chooses nothing", async () => {
  const { setup, chosen } = await mount();
  await setup.mockInput.typeText("zzzz");
  await tick();
  await setup.renderOnce();
  expect(setup.captureCharFrame()).toContain("nothing matches");
  await setup.mockInput.pressEnter();
  await tick();
  expect(chosen).toEqual([null]);
});

test("esc cancels", async () => {
  const { setup, chosen } = await mount();
  await setup.mockInput.pressEscape();
  await tick(120);
  expect(chosen).toEqual([null]);
  void setup;
});

test("with no session in the folder every folder is shown at once", async () => {
  const { setup } = await mount(SESSIONS, [], "/work/none");
  expect(setup.captureCharFrame()).toContain("all folders");
  expect(setup.captureCharFrame()).toContain("billing report");
});

test("with nothing at all it says so", async () => {
  const { setup } = await mount([], [], "/work/app");
  expect(setup.captureCharFrame()).toContain("no sessions yet");
});
