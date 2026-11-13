import { afterEach, expect, spyOn, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { App } from "../src/App";
import { DEFAULT_SETTINGS, type Settings } from "../src/settings";
import { ALIA, FakeSession, HOST } from "./support/fake-session";

type Setup = Awaited<ReturnType<typeof testRender>>;
const BEK = { id: "p_bek", name: "Bek", role: "participant", connected: true } as const;
const CLEO = { id: "p_cleo", name: "Cleo", role: "viewer", connected: true } as const;

const open: Setup[] = [];
afterEach(() => {
  while (open.length > 0) {
    open.pop()?.renderer.destroy();
  }
});

function room(role: "host" | "participant" = "host", replies: "mention" | "all" = "all"): FakeSession {
  const fake = new FakeSession();
  const me = role === "host" ? HOST : ALIA;
  fake.emit({ type: "session.welcome", room: "r_1", token: "t", participant: me, base_policy: [], agent: "anthropic · claude-opus-5-5" });
  fake.emit({
    type: "session.snapshot",
    state: { ...fake.projection.state, chat_mode: replies, participants: { [HOST.id]: HOST, [ALIA.id]: ALIA, [BEK.id]: BEK, [CLEO.id]: CLEO } },
    streaming: {},
    typing: [],
  });
  return fake;
}

async function mount(fake: FakeSession, settings: Partial<Settings> = {}): Promise<Setup> {
  const setup = await testRender(
    <App client={fake} room="r_1" version="0.2.1" guestLink={null} settings={{ ...DEFAULT_SETTINGS, setupSeen: true, ...settings }} onQuit={() => undefined} />,
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
}

test("/team goes to the room and not to the agent", async () => {
  const fake = room();
  const setup = await mount(fake);
  await say(setup, "/team lunch at one");
  await new Promise((resolve) => setTimeout(resolve, 100));
  expect(fake.commands).toEqual([{ type: "chat.send", text: "lunch at one", to: null, mentions: [] }]);
  expect(fake.commands.some((command) => command.type === "prompt.submit")).toBe(false);
  void setup;
});

test("a tag inside /team is carried so that person is alerted", async () => {
  const fake = room();
  const setup = await mount(fake);
  await say(setup, "/team @Alia please look");
  await new Promise((resolve) => setTimeout(resolve, 100));
  expect(fake.commands).toEqual([{ type: "chat.send", text: "@Alia please look", to: null, mentions: ["p_alia"] }]);
});

test("@name at the start writes to that person only", async () => {
  const fake = room();
  const setup = await mount(fake);
  await say(setup, "@Bek can you cover my review");
  await new Promise((resolve) => setTimeout(resolve, 100));
  expect(fake.commands).toEqual([{ type: "chat.send", text: "can you cover my review", to: "p_bek", mentions: [] }]);
  void setup;
});

test("an @ that names no one in the room is still a prompt for the agent", async () => {
  const fake = room();
  const setup = await mount(fake);
  await say(setup, "@src/app.ts has a bug");
  await new Promise((resolve) => setTimeout(resolve, 100));
  expect(fake.commands).toEqual([{ type: "prompt.submit", text: "@src/app.ts has a bug", delivery: "now" }]);
  void setup;
});

test("typing @ lists the people and tab completes the name", async () => {
  const fake = room();
  const setup = await mount(fake);
  await setup.mockInput.typeText("@b");
  const listed = await frame(setup, "@Bek");
  expect(listed).not.toContain("@Alia");
  await setup.mockInput.pressTab();
  await frame(setup, "@Bek ");
  await setup.mockInput.typeText("hello");
  await setup.mockInput.pressEnter();
  await new Promise((resolve) => setTimeout(resolve, 100));
  expect(fake.commands.at(-1)).toEqual({ type: "chat.send", text: "hello", to: "p_bek", mentions: [] });
});

test("someone who watches cannot be written to and the reason is shown", async () => {
  const fake = room();
  const setup = await mount(fake);
  await say(setup, "@Cleo hi");
  await frame(setup, "cannot get private messages");
  expect(fake.commands).toEqual([]);
});

test("a message for the room and a private one look different and say the agent cannot see them", async () => {
  const fake = room();
  const setup = await mount(fake);
  fake.emit({ type: "chat.posted", message_id: "c1", author_id: "p_alia", text: "standup in five", to: null, mentions: [], agent_sees: false });
  fake.emit({ type: "chat.posted", message_id: "c2", author_id: "p_alia", text: "psst, a secret", to: "p_host", mentions: [], agent_sees: false });
  fake.emit({ type: "chat.posted", message_id: "c3", author_id: "p_host", text: "on my way", to: "p_alia", mentions: [], agent_sees: false });
  const text = await frame(setup, "on my way");
  expect(text).toContain("Alia · to the room");
  expect(text).toContain("standup in five");
  expect(text).toContain("Alia → you");
  expect(text).toContain("you → Alia");
  expect(text).toContain("private, the agent does not see it");
});

test("being written to rings the bell and raises a message; the room's chat does not", async () => {
  const written = spyOn(process.stdout, "write");
  const fake = room();
  const setup = await mount(fake);
  const bells = (): number => written.mock.calls.filter(([chunk]) => chunk === "\u0007").length;
  fake.emit({ type: "chat.posted", message_id: "c1", author_id: "p_alia", text: "no one in particular", to: null, mentions: [], agent_sees: false });
  await new Promise((resolve) => setTimeout(resolve, 150));
  expect(bells()).toBe(0);

  fake.emit({ type: "chat.posted", message_id: "c2", author_id: "p_alia", text: "this one is for you", to: "p_host", mentions: [], agent_sees: false });
  const toast = await frame(setup, "Alia wrote to you");
  expect(toast).toContain("this one is for you");
  expect(bells()).toBe(1);

  fake.emit({ type: "chat.posted", message_id: "c3", author_id: "p_bek", text: "@vlad see this", to: null, mentions: ["p_host"], agent_sees: false });
  await frame(setup, "Bek mentioned you");
  expect(bells()).toBe(2);
  written.mockRestore();
});

test("with the bell off the message still appears and nothing rings", async () => {
  const written = spyOn(process.stdout, "write");
  const fake = room();
  const setup = await mount(fake, { mentionBell: false });
  fake.emit({ type: "chat.posted", message_id: "c2", author_id: "p_alia", text: "quietly", to: "p_host", mentions: [], agent_sees: false });
  await frame(setup, "Alia wrote to you");
  expect(written.mock.calls.filter(([chunk]) => chunk === "\u0007")).toHaveLength(0);
  written.mockRestore();
});

test("what I wrote myself never rings", async () => {
  const written = spyOn(process.stdout, "write");
  const fake = room();
  const setup = await mount(fake);
  fake.emit({ type: "chat.posted", message_id: "c1", author_id: "p_host", text: "@Alia hi", to: null, mentions: ["p_alia", "p_host"], agent_sees: false });
  await frame(setup, "you · to the room");
  expect(written.mock.calls.filter(([chunk]) => chunk === "\u0007")).toHaveLength(0);
  written.mockRestore();
});

test("/kick removes the named person and says so; an unknown name changes nothing", async () => {
  const fake = room();
  const setup = await mount(fake);
  await say(setup, "/kick bek");
  await frame(setup, "Bek was removed from the session");
  expect(fake.commands).toEqual([{ type: "participant.revoke", participant_id: "p_bek" }]);
  await say(setup, "/kick nobody");
  await frame(setup, "usage: /kick <name>");
  expect(fake.commands).toHaveLength(1);
});

test("a guest cannot kick anyone", async () => {
  const fake = room("participant");
  const setup = await mount(fake);
  await say(setup, "/kick bek");
  await frame(setup, "/kick is for the host");
  expect(fake.commands).toEqual([]);
});

test("in mention mode a plain message is chat the agent reads, and @plrl reaches the agent", async () => {
  const fake = room("host", "mention");
  const setup = await mount(fake);
  await frame(setup, "replies @plrl");
  await say(setup, "lunch at one?");
  await new Promise((resolve) => setTimeout(resolve, 100));
  expect(fake.commands).toEqual([{ type: "chat.send", text: "lunch at one?", to: null, mentions: [] }]);
  await say(setup, "@plrl fix the failing test");
  await new Promise((resolve) => setTimeout(resolve, 100));
  expect(fake.commands.at(-1)).toEqual({ type: "prompt.submit", text: "@plrl fix the failing test", delivery: "now" });
});

test("typing @ offers the agent next to the people, and tab completes it", async () => {
  const fake = room("host", "mention");
  const setup = await mount(fake);
  await setup.mockInput.typeText("@pl");
  await frame(setup, "answers this message");
  await setup.mockInput.pressTab();
  await frame(setup, "@plrl ");
  await setup.mockInput.typeText("why is CI red");
  await setup.mockInput.pressEnter();
  await new Promise((resolve) => setTimeout(resolve, 100));
  expect(fake.commands.at(-1)).toEqual({ type: "prompt.submit", text: "@plrl why is CI red", delivery: "now" });
});

test("a room message in mention mode says the agent reads it", async () => {
  const fake = room("host", "mention");
  const setup = await mount(fake);
  fake.emit({ type: "chat.posted", message_id: "c1", author_id: "p_alia", text: "standup in five", to: null, mentions: [], agent_sees: true });
  const text = await frame(setup, "standup in five");
  expect(text).toContain("the agent reads it");
});

test("/replies switches the mode for the room, and only the host may", async () => {
  const fake = room();
  const setup = await mount(fake);
  await say(setup, "/replies mention");
  await new Promise((resolve) => setTimeout(resolve, 100));
  expect(fake.commands).toEqual([{ type: "session.set_chat_mode", mode: "mention" }]);
  fake.emit({ type: "session.chat_mode_changed", mode: "mention" });
  await frame(setup, "the agent answers messages that tag @plrl");

  const guest = room("participant");
  const other = await mount(guest);
  await say(other, "/replies all");
  await frame(other, "/replies is for the host");
  expect(guest.commands).toEqual([]);
});

test("the Session tab shows when the agent answers and the host switches it there", async () => {
  const fake = room("host", "mention");
  const setup = await mount(fake);
  await setup.mockInput.pressKey("F2");
  await frame(setup, "Model");
  await setup.mockInput.pressTab();
  await frame(setup, "only @plrl");
  await setup.mockInput.pressArrow("down");
  await setup.mockInput.pressArrow("down");
  await frame(setup, "it answers @plrl");
  await setup.mockInput.pressEnter();
  await new Promise((resolve) => setTimeout(resolve, 100));
  expect(fake.commands).toEqual([{ type: "session.set_chat_mode", mode: "all" }]);
});
