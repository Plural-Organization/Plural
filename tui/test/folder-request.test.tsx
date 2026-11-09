import { afterEach, expect, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { App } from "../src/App";
import { DEFAULT_SETTINGS } from "../src/settings";
import { CALL, FakeSession, GUEST, HOST } from "./support/fake-session";

type Setup = Awaited<ReturnType<typeof testRender>>;
const open: Setup[] = [];
const tick = (ms = 50) => new Promise((resolve) => setTimeout(resolve, ms));
afterEach(() => {
  while (open.length) open.pop()?.renderer.destroy();
});

function ask(fake: FakeSession, id: string, folder = { folder: "/srv/logs", write: false, broad: false }) {
  fake.emit({ type: "approval.requested", approval: {
    id, call: { ...CALL, name: "read", risk: "read", subject: "/srv/logs/app.log" }, provenance: GUEST,
    timeout_at: new Date(Date.now() + 60_000).toISOString(),
    suggested_patterns: [], warnings: [], folder,
  } });
}

async function frame(setup: Setup, expected: string) {
  for (let tries = 0; tries < 100; tries++) {
    await setup.renderOnce();
    const text = setup.captureCharFrame();
    if (text.includes(expected)) return text;
    await tick(25);
  }
  throw new Error(`Missing ${expected}: ${setup.captureCharFrame()}`);
}

async function mount(folder?: { folder: string; write: boolean; broad: boolean }) {
  const fake = new FakeSession();
  fake.emit({ type: "session.welcome", room: "r_1", token: "t", participant: HOST, base_policy: [], agent: "x" });
  fake.emit({ type: "participant.joined", participant: HOST });
  const setup = await testRender(
    <App client={fake} room="r_1" version="test" guestLink={null} settings={{ ...DEFAULT_SETTINGS, setupSeen: true }} onQuit={() => undefined} />,
    { width: 120, height: 40 },
  );
  open.push(setup);
  await setup.renderOnce();
  ask(fake, "ap1", folder);
  await frame(setup, "FOLDER OUTSIDE THE SESSION");
  await tick(500);
  return { fake, setup };
}

test("the card names the folder, who asks and what for", async () => {
  const { setup } = await mount();
  const text = await frame(setup, "/srv/logs");
  expect(text).toContain("READ files here");
  expect(text).toContain("read + write");
  expect(text).toContain("refuse");
  expect(text).toContain("nothing is remembered");
});

test("a request to change files says CHANGE, and a broad folder is called out", async () => {
  const { setup } = await mount({ folder: "/", write: true, broad: true });
  const text = await frame(setup, "CHANGE");
  expect(text).toContain("whole disk or your home folder");
});

test("a stray Enter refuses: the card starts on refuse", async () => {
  const { fake, setup } = await mount();
  await setup.mockInput.pressEnter();
  await tick();
  expect(fake.commands).toEqual([{ type: "approval.respond", approval_id: "ap1", decision: "reject" }]);
});

for (const [key, decision] of [["r", "read"], ["w", "write"], ["n", "reject"]] as const) {
  test(`hotkey ${key} answers ${decision}`, async () => {
    const { fake, setup } = await mount();
    await setup.mockInput.typeText(key);
    await tick();
    expect(fake.commands).toEqual([{ type: "approval.respond", approval_id: "ap1", decision }]);
  });
}

test("the tool-call keys do nothing on a folder card", async () => {
  const { fake, setup } = await mount();
  for (const key of ["y", "a", "b"]) {
    await setup.mockInput.typeText(key);
    await tick();
  }
  expect(fake.commands).toEqual([]);
});

test("arrows move from refuse to read + write to read, and Enter confirms", async () => {
  const { fake, setup } = await mount();
  await setup.mockInput.pressArrow("left");
  await tick();
  await setup.mockInput.pressEnter();
  await tick();
  expect(fake.commands).toEqual([{ type: "approval.respond", approval_id: "ap1", decision: "write" }]);
});
