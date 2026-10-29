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
const { TOAST_MS } = await import("../src/components/Toast");

type Setup = Awaited<ReturnType<typeof testRender>>;
const open: Setup[] = [];
afterEach(() => {
  copied.length = 0;
  while (open.length > 0) {
    open.pop()?.renderer.destroy();
  }
});

function session(): FakeSession {
  const fake = new FakeSession();
  fake.emit({ type: "session.welcome", room: "r_1", token: "t", participant: HOST, base_policy: [], agent: "anthropic · claude-opus-5-5" });
  fake.emit({ type: "participant.joined", participant: HOST });
  return fake;
}

async function mount(fake: FakeSession, copyOnSelect = true): Promise<Setup> {
  const setup = await testRender(
    <App client={fake} room="r_1" version="0.2.1" guestLink={null} settings={{ ...DEFAULT_SETTINGS, setupSeen: true, copyOnSelect }} onQuit={() => undefined} />,
    { width: 120, height: 36 },
  );
  open.push(setup);
  await setup.renderOnce();
  return setup;
}

async function until(setup: Setup, check: (frame: string) => boolean, timeout = 4000): Promise<string> {
  const deadline = Date.now() + timeout;
  for (;;) {
    await setup.renderOnce();
    const text = setup.captureCharFrame();
    if (check(text)) {
      return text;
    }
    if (Date.now() > deadline) {
      throw new Error(`condition not met in:\n${text}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
}

test("a new invite link is copied and a message says so, then goes away", async () => {
  const fake = session();
  const setup = await mount(fake);
  fake.emit({ type: "invite.created", role: "participant", link: "ws://h/r_1?invite=abc", expires_at: "2026-10-28T13:00:00Z" } as never);
  const shown = await until(setup, (text) => text.includes("Invite link copied"));
  expect(shown).toContain("✓");
  expect(copied).toEqual(["ws://h/r_1?invite=abc"]);
  await until(setup, (text) => !text.includes("Invite link copied"), TOAST_MS + 3000);
});

test("selecting text copies it and the message names the amount and the start", async () => {
  const fake = session();
  fake.emit({ type: "prompt.accepted", prompt_id: "p1", author_id: HOST.id, text: "rename the helper to parse_link everywhere", provenance: { initiator_id: HOST.id, initiator_role: "host", origin: "direct" }, attachments: [] } as never);
  const setup = await mount(fake);
  const frame = await until(setup, (text) => text.includes("rename the helper"));
  const row = frame.split("\n").findIndex((line) => line.includes("rename the helper"));
  const column = frame.split("\n")[row]!.indexOf("rename");
  await setup.mockMouse.drag(column, row, column + 17, row);
  const shown = await until(setup, (text) => text.includes("Copied"));
  expect(shown).toMatch(/\d+ characters/);
  expect(copied.join("")).toContain("rename the helper");
});

test("nothing is copied or announced when copy on select is off", async () => {
  const fake = session();
  fake.emit({ type: "prompt.accepted", prompt_id: "p1", author_id: HOST.id, text: "rename the helper to parse_link everywhere", provenance: { initiator_id: HOST.id, initiator_role: "host", origin: "direct" }, attachments: [] } as never);
  const setup = await mount(fake, false);
  const frame = await until(setup, (text) => text.includes("rename the helper"));
  const row = frame.split("\n").findIndex((line) => line.includes("rename the helper"));
  const column = frame.split("\n")[row]!.indexOf("rename");
  await setup.mockMouse.drag(column, row, column + 17, row);
  await new Promise((resolve) => setTimeout(resolve, 500));
  await setup.renderOnce();
  expect(setup.captureCharFrame()).not.toContain("Copied");
  expect(copied).toEqual([]);
});

void ALIA;
