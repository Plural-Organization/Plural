import { afterEach, expect, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { App } from "../src/App";
import { DEFAULT_SETTINGS } from "../src/settings";
import { theme } from "../src/theme";
import { ALIA, FakeSession, HOST } from "./support/fake-session";

type Setup = Awaited<ReturnType<typeof testRender>>;
const open: Setup[] = [];
afterEach(() => {
  while (open.length > 0) {
    open.pop()?.renderer.destroy();
  }
});

const hex = (color: { toInts: () => [number, number, number, number] }): string =>
  `#${color
    .toInts()
    .slice(0, 3)
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("")}`;

async function conversation(): Promise<Setup> {
  const fake = new FakeSession();
  fake.emit({ type: "session.welcome", room: "r_1", token: "t", participant: HOST, base_policy: [], agent: "anthropic · claude-opus-5-5" });
  fake.emit({ type: "participant.joined", participant: HOST });
  fake.emit({ type: "participant.joined", participant: ALIA });
  const provenance = { initiator_id: "p_alia", initiator_role: "participant", origin: "direct" } as never;
  fake.emit({ type: "prompt.accepted", prompt_id: "pm1", author_id: "p_alia", text: "fix the login bug", delivery: "now", provenance, attachments: [] });
  fake.emit({ type: "message.started", run_id: "r", message_id: "m1" });
  fake.emit({ type: "message.ended", run_id: "r", message_id: "m1", text: "I will look at the retry logic", thinking: "" });
  fake.emit({ type: "tool.started", run_id: "r", call: { id: "t1", name: "bash", risk: "exec", subject: "pytest -q", args: {} } });
  fake.emit({ type: "tool.ended", run_id: "r", call_id: "t1", ok: true, output: "a\n[exit 0]", diff: null });
  fake.emit({ type: "chat.posted", message_id: "c1", author_id: "p_alia", text: "standup in five", to: null, mentions: [] });
  fake.emit({ type: "chat.posted", message_id: "c2", author_id: "p_alia", text: "a secret for you", to: "p_host", mentions: [] });
  const setup = await testRender(<App client={fake} room="r_1" version="0.2.9" guestLink={null} settings={{ ...DEFAULT_SETTINGS, setupSeen: true }} onQuit={() => undefined} />, { width: 130, height: 46 });
  open.push(setup);
  await new Promise((resolve) => setTimeout(resolve, 300));
  await setup.renderOnce();
  return setup;
}

function backgroundOf(setup: Setup, text: string): string {
  const line = [...setup.captureSpans().lines].reverse().find((entry) => entry.spans.some((span) => span.text.includes(text)));
  const span = line?.spans.find((entry) => entry.text.includes(text));
  if (span === undefined) {
    throw new Error(`"${text}" is not on the screen`);
  }
  return hex(span.bg);
}

test("no message sits inside a box", async () => {
  const text = (await conversation()).captureCharFrame();
  expect(text).not.toMatch(/[┌┐└┘]/);
});

test("people's messages share one background and what is written to you has its own", async () => {
  const setup = await conversation();
  expect(backgroundOf(setup, "fix the login bug")).toBe(theme.bubble.toLowerCase());
  expect(backgroundOf(setup, "standup in five")).toBe(theme.bubble.toLowerCase());
  expect(backgroundOf(setup, "a secret for you")).toBe(theme.you.toLowerCase());
  expect(theme.bubble).not.toBe(theme.you);
});

test("the agent and its tools have no background and start with a marker", async () => {
  const setup = await conversation();
  expect(backgroundOf(setup, "I will look at the retry logic")).not.toBe(theme.bubble.toLowerCase());
  expect(backgroundOf(setup, "I will look at the retry logic")).not.toBe(theme.you.toLowerCase());
  expect(backgroundOf(setup, "Bash")).not.toBe(theme.bubble.toLowerCase());
  const text = setup.captureCharFrame();
  expect(text).toContain("⏺ I will look at the retry logic");
  expect(text).toContain("⏺ Bash(pytest -q)");
});

test("the top bar says Plural in the middle and no longer prints the room id", async () => {
  const setup = await conversation();
  const first = setup.captureCharFrame().split("\n")[0] ?? "";
  expect(first).not.toContain("r_1");
  const at = first.indexOf("Plural");
  expect(at).toBeGreaterThan(45);
  expect(at).toBeLessThan(75);
});

test("the welcome plate is text only: the name and version in the frame, then the keys", async () => {
  const setup = await conversation();
  const text = setup.captureCharFrame();
  expect(text).toMatch(/╭─ Plural {2}v0\.2\.9 ─+/);
  expect(text).toMatch(/KEYS[\s\S]*\/help\s+commands/);
  expect(text).not.toContain("shared agent sessions");
  expect(text).not.toMatch(/▄▄▀▀▀▀▀▀▄▄/);
});
