import { afterEach, expect, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import type { Command } from "@plural/client";
import { App } from "../src/App";
import { DEFAULT_SETTINGS } from "../src/settings";
import { ALIA, FakeSession, HOST } from "./support/fake-session";

type Setup = Awaited<ReturnType<typeof testRender>>;
const BEK = { id: "p_bek", name: "Bek", role: "participant", connected: true } as const;
const CLEO = { id: "p_cleo", name: "Cleo", role: "viewer", connected: true } as const;

class FlakySession extends FakeSession {
  failing: string | null = null;

  override async send(command: Command): Promise<void> {
    if (this.failing !== null && command.type !== "presence.typing") {
      throw new Error(this.failing);
    }
    await super.send(command);
  }
}

const open: Setup[] = [];
afterEach(() => {
  while (open.length > 0) {
    open.pop()?.renderer.destroy();
  }
});

function room<T extends FakeSession>(fake: T): T {
  fake.emit({ type: "session.welcome", room: "r_1", token: "t", participant: HOST, base_policy: [], agent: "anthropic · claude-opus-5-5" });
  fake.emit({
    type: "session.snapshot",
    state: { ...fake.projection.state, participants: { [HOST.id]: HOST, [ALIA.id]: ALIA, [BEK.id]: BEK, [CLEO.id]: CLEO } },
    streaming: {},
    typing: [],
  });
  return fake;
}

async function mount(fake: FakeSession): Promise<Setup> {
  const setup = await testRender(
    <App client={fake} room="r_1" version="0.2.4" guestLink={null} settings={{ ...DEFAULT_SETTINGS, setupSeen: true }} onQuit={() => undefined} />,
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

async function erase(setup: Setup, count: number): Promise<void> {
  for (let index = 0; index < count; index += 1) {
    await setup.mockInput.pressBackspace();
  }
}

async function settle(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 100));
}

function chat(fake: FakeSession, id: string, text: string): void {
  fake.emit({ type: "chat.posted", message_id: id, author_id: "p_alia", text, to: null, mentions: [] });
}

test("the box always says who will see the message", async () => {
  const setup = await mount(room(new FakeSession()));
  await frame(setup, "→ agent · everyone in the room sees it");

  await setup.mockInput.typeText("/team");
  await frame(setup, "→ room · everyone sees it, the agent does not");

  await erase(setup, 5);
  await setup.mockInput.typeText("@Bek hi");
  await frame(setup, "→ @Bek · private, the agent does not see it");

  await erase(setup, 7);
  await setup.mockInput.typeText("@Cleo hi");
  const blocked = await frame(setup, "→ @Cleo");
  expect(blocked).toContain("cannot get private messages");
});

test("a message that did not go through comes back into the box with the reason", async () => {
  const fake = room(new FlakySession());
  const setup = await mount(fake);
  fake.failing = "not connected";
  await setup.mockInput.typeText("refactor the parser");
  await setup.mockInput.pressEnter();
  const text = await frame(setup, "your text is back in the box");
  expect(text).toContain("✕ not sent: not connected");
  await frame(setup, "❯ refactor the parser");
  expect(fake.commands).toEqual([]);

  fake.failing = null;
  await setup.mockInput.pressEnter();
  await frame(setup, "✓ delivered");
  expect(fake.commands).toEqual([{ type: "prompt.submit", text: "refactor the parser", delivery: "now" }]);
});

test("a team message that failed comes back too", async () => {
  const fake = room(new FlakySession());
  const setup = await mount(fake);
  fake.failing = "slow consumer";
  await setup.mockInput.typeText("@Bek ping");
  await setup.mockInput.pressEnter();
  const text = await frame(setup, "your text is back in the box");
  expect(text).toContain("✕ not sent: slow consumer");
  await frame(setup, "❯ @Bek ping");
});

test("ctrl+f finds text, commands and paths and steps between the matches", async () => {
  const fake = room(new FakeSession());
  const setup = await mount(fake);
  chat(fake, "c1", "deploy the login fix");
  fake.emit({ type: "message.completed", message_id: "m1", text: "I changed src/auth/login.py" } as never);
  chat(fake, "c2", "lunch at one");
  chat(fake, "c3", "login is green now");
  await frame(setup, "login is green now");

  await setup.mockInput.pressKey("f", { ctrl: true });
  await frame(setup, "search");
  await setup.mockInput.typeText("login");
  const first = await frame(setup, "1/");
  expect(first).toContain("login is green now");

  await setup.mockInput.pressEnter();
  const second = await frame(setup, "2/");
  expect(second).toContain("deploy the login fix");

  await setup.mockInput.pressEnter();
  await frame(setup, "1/");
});

test("search says when nothing matches and esc brings the box back", async () => {
  const fake = room(new FakeSession());
  const setup = await mount(fake);
  chat(fake, "c1", "hello");
  await frame(setup, "hello");
  await setup.mockInput.pressKey("f", { ctrl: true });
  await frame(setup, "search");
  await setup.mockInput.typeText("zzzz");
  await frame(setup, "no matches");
  await setup.mockInput.pressEscape();
  await settle();
  expect(setup.captureCharFrame()).not.toContain("no matches");
  await setup.mockInput.typeText("hi");
  await frame(setup, "hi");
  await setup.mockInput.pressEnter();
  await settle();
  expect(fake.commands.at(-1)).toEqual({ type: "prompt.submit", text: "hi", delivery: "now" });
});

function reply(fake: FakeSession, id: string, text: string): void {
  fake.emit({ type: "message.started", run_id: "r", message_id: id });
  fake.emit({ type: "message.delta", message_id: id, text, thinking: false });
  fake.emit({ type: "message.ended", run_id: "r", message_id: id, text, thinking: "" });
}

test("a very long reply is folded and ctrl+o opens it", async () => {
  const fake = room(new FakeSession());
  const setup = await mount(fake);
  reply(fake, "m1", Array.from({ length: 80 }, (_, index) => `line ${index + 1}`).join("\n\n"));
  const folded = await frame(setup, "more lines");
  expect(folded).not.toContain("line 80");
  await setup.mockInput.pressKey("o", { ctrl: true });
  await frame(setup, "show less");
});

test("scrolled away from the end, a note counts what arrived and end brings you back", async () => {
  const fake = room(new FakeSession());
  const setup = await mount(fake);
  for (let index = 0; index < 60; index += 1) {
    chat(fake, `a${index}`, `old message ${index}`);
  }
  await frame(setup, "old message 59");
  await new Promise((resolve) => setTimeout(resolve, 300));
  for (let index = 0; index < 6; index += 1) {
    await setup.mockMouse.scroll(40, 15, "up");
  }
  chat(fake, "n1", "fresh one");
  chat(fake, "n2", "fresh two");
  const away = await frame(setup, "2 new");
  expect(away).toContain("✉ 2");
  await setup.mockInput.pressKey("\u001B[F");
  await frame(setup, "fresh two");
  await settle();
  await setup.renderOnce();
  expect(setup.captureCharFrame()).not.toContain("2 new");
});
