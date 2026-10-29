import { afterEach, expect, mock, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { ALIA, FakeSession, HOST } from "./support/fake-session";

const copied: string[] = [];
mock.module("../src/lib/clipboard", () => ({
  copyToClipboard: async (text: string) => {
    copied.push(text);
  },
  pasteImage: async () => null,
  IMAGE_LIMIT_BYTES: 2_500_000,
}));
const { App } = await import("../src/App");
const { DEFAULT_SETTINGS } = await import("../src/settings");

type Setup = Awaited<ReturnType<typeof testRender>>;
const open: Setup[] = [];
afterEach(() => {
  copied.length = 0;
  while (open.length > 0) {
    open.pop()?.renderer.destroy();
  }
});

const REQUEST = { id: "j_1", name: "Dana", client: "tui 0.2.2", requested_at: new Date().toISOString() };

function room(role: "host" | "participant" = "host"): FakeSession {
  const fake = new FakeSession();
  fake.emit({ type: "session.welcome", room: "r_1", token: "t", participant: role === "host" ? HOST : ALIA, base_policy: [], agent: "anthropic · claude-opus-5-5" });
  fake.emit({ type: "participant.joined", participant: HOST });
  return fake;
}

async function mount(fake: FakeSession, splash = false): Promise<Setup> {
  const setup = await testRender(
    <App client={fake} room="r_1" version="0.2.2" guestLink={null} splash={splash} settings={{ ...DEFAULT_SETTINGS, setupSeen: true }} onQuit={() => undefined} />,
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

const wait = (ms = 120) => new Promise((resolve) => setTimeout(resolve, ms));

async function knock(): Promise<{ fake: FakeSession; setup: Setup }> {
  const fake = room();
  const setup = await mount(fake);
  fake.emit({ type: "join.requested", request: REQUEST });
  await frame(setup, "wants to join");
  await setup.mockInput.pressTab();
  await wait(500);
  return { fake, setup };
}

test("the host sees who is waiting and from which client", async () => {
  const fake = room();
  const setup = await mount(fake);
  fake.emit({ type: "join.requested", request: REQUEST });
  const text = await frame(setup, "wants to join");
  expect(text).toContain("Dana");
  expect(text).toContain("tui 0.2.2");
  expect(text).toContain("tab to answer");
});

test("a guest never sees the card", async () => {
  const fake = room("participant");
  const setup = await mount(fake);
  fake.emit({ type: "join.requested", request: REQUEST });
  await wait(200);
  await setup.renderOnce();
  expect(setup.captureCharFrame()).not.toContain("wants to join");
});

test("y lets in as a participant, v as a viewer and n refuses", async () => {
  for (const [key, decision] of [["y", "allow"], ["v", "viewer"], ["n", "deny"]] as const) {
    const { fake, setup } = await knock();
    await setup.mockInput.pressKey(key);
    await wait();
    expect(fake.commands.at(-1)).toEqual({ type: "join.decide", request_id: "j_1", decision });
    setup.renderer.destroy();
    open.pop();
  }
});

test("enter lets in like y", async () => {
  const { fake, setup } = await knock();
  await setup.mockInput.pressEnter();
  await wait();
  expect(fake.commands.at(-1)).toEqual({ type: "join.decide", request_id: "j_1", decision: "allow" });
  void setup;
});

test("the card goes away when the host answers elsewhere", async () => {
  const fake = room();
  const setup = await mount(fake);
  fake.emit({ type: "join.requested", request: REQUEST });
  await frame(setup, "wants to join");
  fake.emit({ type: "join.resolved", request_id: "j_1", decision: "allow", decided_by: "p_host" });
  await wait(200);
  await setup.renderOnce();
  expect(setup.captureCharFrame()).not.toContain("wants to join");
});

async function typed(fake: FakeSession, text: string): Promise<Setup> {
  const setup = await mount(fake);
  await setup.mockInput.typeText(text);
  await setup.mockInput.pressEnter();
  await wait();
  return setup;
}

test("/invite asks for the room link and the other words for the other things", async () => {
  const cases: [string, unknown][] = [
    ["/invite", { type: "invite.create", role: "participant", ttl_s: 3600, reusable: true }],
    ["/invite link", { type: "invite.create", role: "participant", ttl_s: 3600, reusable: true }],
    ["/invite once", { type: "invite.create", role: "participant", ttl_s: 3600 }],
    ["/invite viewer", { type: "invite.create", role: "viewer", ttl_s: 3600 }],
    ["/invite revoke", { type: "link.revoke" }],
    ["/invite open", { type: "link.set_admission", mode: "open" }],
    ["/invite approve", { type: "link.set_admission", mode: "approve" }],
  ];
  for (const [line, expected] of cases) {
    const fake = room();
    await typed(fake, line);
    expect(fake.commands).toEqual([expected as never]);
    open.pop()?.renderer.destroy();
  }
});

test("a word that is not an option is explained", async () => {
  const fake = room();
  const setup = await typed(fake, "/invite forever");
  await frame(setup, "usage: /invite");
  expect(fake.commands).toEqual([]);
});

test("the room link is copied with a note about who lets people in", async () => {
  const fake = room();
  const setup = await mount(fake);
  fake.emit({ type: "invite.created", code: "c", role: "participant", expires_at: null, link: "wss://h/r_1?join=ABC", reusable: true } as never);
  const text = await frame(setup, "Room link copied");
  expect(text).toContain("you will be asked to let each person in");
  expect(copied).toEqual(["wss://h/r_1?join=ABC"]);

  fake.emit({ type: "link.admission_changed", mode: "open" });
  fake.emit({ type: "invite.created", code: "c", role: "participant", expires_at: null, link: "wss://h/r_1?join=ABC", reusable: true } as never);
  await frame(setup, "anyone with it joins at once");
});

test("a one-time invite is still copied as before", async () => {
  const fake = room();
  const setup = await mount(fake);
  fake.emit({ type: "invite.created", code: "c", role: "viewer", expires_at: "2026-10-28T13:00:00Z", link: "wss://h/r_1?invite=X", reusable: false } as never);
  await frame(setup, "Invite link copied");
  expect(copied).toEqual(["wss://h/r_1?invite=X"]);
});

test("a guest at the door is told that the host has to let them in", async () => {
  const fake = new FakeSession();
  fake.status = "online";
  fake.projection.waiting = true;
  const setup = await mount(fake, true);
  await setup.mockInput.pressKey("x");
  const text = await frame(setup, "waiting for the host to let you in");
  expect(text).not.toContain("reconnecting");
});

test("the settings let the host choose between letting each person in and an open link", async () => {
  const fake = room();
  const setup = await mount(fake);
  await setup.mockInput.pressKey("F2");
  await frame(setup, "Model");
  await setup.mockInput.pressTab();
  const text = await frame(setup, "People who use the room link");
  expect(text).toContain("I let each person in");
  expect(text).toContain("Anyone with the link joins at once");
  await setup.mockInput.pressArrow("down");
  await setup.mockInput.pressArrow("down");
  await setup.mockInput.pressArrow("down");
  await setup.mockInput.pressArrow("down");
  await setup.mockInput.pressEnter();
  await wait();
  expect(fake.commands.at(-1)).toEqual({ type: "link.set_admission", mode: "open" });
});
