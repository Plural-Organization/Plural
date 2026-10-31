import { afterEach, expect, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { App } from "../src/App";
import { APPROVAL_DECISIONS } from "../src/components/Inbox";
import { DEFAULT_SETTINGS } from "../src/settings";
import { CALL, FakeSession, GUEST, HOST } from "./support/fake-session";

type Setup = Awaited<ReturnType<typeof testRender>>;
const open: Setup[] = [];
const tick = (ms = 50) => new Promise((resolve) => setTimeout(resolve, ms));
afterEach(() => {
  while (open.length) open.pop()?.renderer.destroy();
});

function request(fake: FakeSession, id: string) {
  fake.emit({ type: "approval.requested", approval: {
    id, call: CALL, provenance: GUEST,
    timeout_at: new Date(Date.now() + 60_000).toISOString(),
    suggested_patterns: [], warnings: [],
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

async function mount() {
  const fake = new FakeSession();
  fake.emit({ type: "session.welcome", room: "r_1", token: "t", participant: HOST, base_policy: [], agent: "x" });
  fake.emit({ type: "participant.joined", participant: HOST });
  const setup = await testRender(
    <App client={fake} room="r_1" version="test" guestLink={null} settings={{ ...DEFAULT_SETTINGS, setupSeen: true }} onQuit={() => undefined} />,
    { width: 120, height: 40 },
  );
  open.push(setup);
  await setup.renderOnce();
  request(fake, "ap1");
  await frame(setup, "←/→ choose");
  await tick(500);
  return { fake, setup };
}

for (const [index, decision] of APPROVAL_DECISIONS.entries()) {
  test(`arrows and Enter choose ${decision}`, async () => {
    const { fake, setup } = await mount();
    // One step too far to the left stays on the first choice.
    await setup.mockInput.pressArrow("left");
    await tick();
    for (let step = 0; step < index; step++) {
      await setup.mockInput.pressArrow("right");
      await tick();
    }
    expect(fake.commands).toEqual([]);
    await setup.mockInput.pressEnter();
    await tick();
    expect(fake.commands).toEqual([{ type: "approval.respond", approval_id: "ap1", decision }]);
  });
}

test("the choice stops at the last decision", async () => {
  const { fake, setup } = await mount();
  for (let step = 0; step < APPROVAL_DECISIONS.length + 2; step++) {
    await setup.mockInput.pressArrow("right");
    await tick();
  }
  await setup.mockInput.pressEnter();
  await tick();
  expect(fake.commands).toEqual([{ type: "approval.respond", approval_id: "ap1", decision: "block" }]);
});

for (const [key, decision] of [["y", "once"], ["a", "always"], ["n", "reject"], ["b", "block"]] as const) {
  test(`hotkey ${key} still chooses ${decision}`, async () => {
    const { fake, setup } = await mount();
    await setup.mockInput.pressArrow("right");
    await tick();
    await setup.mockInput.typeText(key);
    await tick();
    expect(fake.commands).toEqual([{ type: "approval.respond", approval_id: "ap1", decision }]);
  });
}

test("switching requests resets the choice and sends the displayed approval id", async () => {
  const { fake, setup } = await mount();
  request(fake, "ap2");
  await tick(550);
  await setup.mockInput.pressArrow("right");
  await tick();
  await setup.mockInput.pressArrow("down");
  await frame(setup, "2/2");
  await setup.mockInput.pressEnter();
  await tick();
  expect(fake.commands).toEqual([{ type: "approval.respond", approval_id: "ap2", decision: "once" }]);
});
