import { afterEach, describe, expect, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import type { ToolCallView } from "@plural/client";
import { App } from "../src/App";
import { DEFAULT_SETTINGS, type Settings } from "../src/settings";
import { ALIA, CALL, FakeSession, GUEST, HOST } from "./support/fake-session";

type Setup = Awaited<ReturnType<typeof testRender>>;

const tick = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function session(role: "host" | "participant" | "viewer" = "host"): FakeSession {
  const fake = new FakeSession();
  const me = role === "host" ? HOST : { ...ALIA, role };
  fake.emit({ type: "session.welcome", room: "r_1", token: "t", participant: me, base_policy: [], agent: "demo agent (scripted)" });
  fake.emit({ type: "participant.joined", participant: HOST });
  if (role !== "host") {
    fake.emit({ type: "participant.joined", participant: me });
  }
  return fake;
}

const open: Setup[] = [];
afterEach(() => {
  while (open.length > 0) {
    open.pop()?.renderer.destroy();
  }
});

async function mount(fake: FakeSession, width = 120, height = 36): Promise<Setup> {
  const setup = await testRender(
    <App client={fake} room="r_1" version="0.2.0" guestLink="ws://h/r_1?invite=x" onQuit={() => undefined} />,
    { width, height },
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
    await tick(25);
  }
}

describe("App", () => {
  test("shows the banner, the participants panel and the composer", async () => {
    const setup = await mount(session());
    const text = await frame(setup, "Message the agent");
    expect(text).toContain("plural join");
    expect(text).toContain("PARTICIPANTS");
    expect(text).toContain("vlad");
    expect(text).toContain("vlad (host)");
  });

  test("typing a prompt and pressing enter sends it", async () => {
    const fake = session();
    const setup = await mount(fake);
    await setup.mockInput.typeText("hello");
    await setup.mockInput.pressEnter();
    await tick(100);
    expect(fake.commands).toEqual([{ type: "prompt.submit", text: "hello", delivery: "now" }]);
  });

  test("slash commands become protocol commands and unknown ones are explained", async () => {
    const fake = session();
    const setup = await mount(fake);
    await setup.mockInput.typeText("/mode review");
    await setup.mockInput.pressEnter();
    await tick(100);
    expect(fake.commands).toEqual([{ type: "session.set_prompt_mode", mode: "review" }]);
    await setup.mockInput.typeText("/nope");
    await setup.mockInput.pressEnter();
    await frame(setup, "unknown command /nope");
  });

  test("the host answers an approval from the keyboard", async () => {
    const fake = session();
    const setup = await mount(fake);
    fake.emit({ type: "participant.joined", participant: ALIA });
    fake.emit({
      type: "approval.requested",
      approval: { id: "ap1", call: CALL, provenance: GUEST, timeout_at: new Date(Date.now() + 60_000).toISOString(), suggested_patterns: ["rm *"] },
    });
    const text = await frame(setup, "approval needed");
    expect(text).toContain("$ rm a.txt");
    expect(text).toContain("Alia");
    expect(text).toContain("NEEDS YOU");
    await tick(500);
    await setup.mockInput.pressKey("n");
    await tick(100);
    expect(fake.commands).toEqual([{ type: "approval.respond", approval_id: "ap1", decision: "reject" }]);
  });

  test("keys pressed right after an approval appears are ignored", async () => {
    const fake = session();
    const setup = await mount(fake);
    fake.emit({
      type: "approval.requested",
      approval: { id: "ap1", call: CALL, provenance: GUEST, timeout_at: new Date(Date.now() + 60_000).toISOString(), suggested_patterns: [] },
    });
    await frame(setup, "approval needed");
    await setup.mockInput.pressKey("y");
    await tick(100);
    expect(fake.commands).toEqual([]);
  });

  test("an approval never steals the keys of a half-typed prompt", async () => {
    const fake = session();
    const setup = await mount(fake);
    await setup.mockInput.typeText("ye");
    fake.emit({
      type: "approval.requested",
      approval: { id: "ap1", call: CALL, provenance: GUEST, timeout_at: new Date(Date.now() + 60_000).toISOString(), suggested_patterns: [] },
    });
    await frame(setup, "tab: 1 waiting for you");
    await setup.mockInput.typeText("s");
    await tick(100);
    expect(fake.commands).toEqual([]);
    expect(await frame(setup, "yes")).toContain("❯ yes");
  });

  test("the host approves a proposal after editing it", async () => {
    const fake = session();
    const setup = await mount(fake);
    fake.emit({ type: "participant.joined", participant: ALIA });
    fake.emit({ type: "proposal.created", proposal: { id: "pr1", author_id: "p_alia", text: "delete everything", delivery: "now", attachments: [] } });
    await frame(setup, "proposal");
    await setup.mockInput.pressTab();
    await tick(100);
    await frame(setup, "edit first");
    await setup.mockInput.pressKey("e");
    await frame(setup, "editing the proposal");
    await setup.mockInput.pressEnter();
    await tick(100);
    expect(fake.commands).toEqual([
      { type: "proposal.decide", proposal_id: "pr1", decision: "approve", edited_text: "delete everything" },
    ]);
  });

  test("a participant is told the host reviews prompts, a viewer cannot type", async () => {
    const review = session("participant");
    review.emit({ type: "session.snapshot", state: { ...review.projection.state, prompt_mode: "review" }, streaming: {}, typing: [] });
    const participant = await mount(review);
    expect(await frame(participant, "the host approves it")).toContain("review");

    const viewer = await mount(session("viewer"));
    expect(await frame(viewer, "viewers can only watch")).toContain("viewers can only watch");
  });

  test("the side panel hides with ctrl+b and on narrow terminals", async () => {
    const setup = await mount(session());
    await frame(setup, "PARTICIPANTS");
    await setup.mockInput.pressKey("b", { ctrl: true });
    await tick(100);
    await setup.renderOnce();
    expect(setup.captureCharFrame()).not.toContain("PARTICIPANTS");
    await setup.mockInput.pressKey("b", { ctrl: true });
    await frame(setup, "PARTICIPANTS");
    setup.resize(70, 30);
    await tick(100);
    await setup.renderOnce();
    expect(setup.captureCharFrame()).not.toContain("PARTICIPANTS");
  });

  test("a streamed markdown reply grows in place", async () => {
    const fake = session();
    const setup = await mount(fake);
    fake.emit({ type: "message.started", run_id: "r", message_id: "m1" });
    fake.emit({ type: "message.delta", message_id: "m1", text: "# Title\n\nFirst **bold** paragraph.\n\n", thinking: false });
    fake.emit({ type: "message.delta", message_id: "m1", text: "- one\n- two", thinking: false });
    const text = await frame(setup, "two");
    expect(text).toContain("Title");
    expect(text).toContain("First bold paragraph.");
    expect(text.match(/● plural/g)?.length).toBe(1);
  });

  test("a fenced code block is drawn in a box with its language", async () => {
    const fake = session();
    const setup = await mount(fake);
    const reply = "Fixed:\n\n```python\ndef add(a, b):\n    return a + b\n```\n";
    fake.emit({ type: "message.started", run_id: "r", message_id: "m1" });
    fake.emit({ type: "message.delta", message_id: "m1", text: reply, thinking: false });
    fake.emit({ type: "message.ended", run_id: "r", message_id: "m1", text: reply, thinking: "" });
    const text = await frame(setup, "return a + b");
    expect(text).toContain("python");
    expect(text).toContain("def add(a, b):");
    expect(text).toContain("╭");
  });

  test("the panel lists who is typing and the line above the composer names them", async () => {
    const fake = session();
    const setup = await mount(fake);
    fake.emit({ type: "participant.joined", participant: ALIA });
    fake.emit({ type: "participant.typing", participant_id: "p_alia", typing: true });
    const text = await frame(setup, "Alia is typing…");
    expect(text).toContain("typing…");
    fake.emit({ type: "participant.typing", participant_id: "p_alia", typing: false });
    await tick(100);
    await setup.renderOnce();
    expect(setup.captureCharFrame()).not.toContain("is typing");
  });

  test("my own typing is announced once, refreshed sparingly and ends with the prompt", async () => {
    const fake = session();
    const setup = await mount(fake);
    await setup.mockInput.typeText("hel");
    await tick(100);
    await setup.mockInput.typeText("lo");
    await tick(100);
    expect(fake.sent).toEqual([{ type: "presence.typing", typing: true }]);
    await setup.mockInput.pressEnter();
    await tick(100);
    expect(fake.sent).toEqual([
      { type: "presence.typing", typing: true },
      { type: "presence.typing", typing: false },
      { type: "prompt.submit", text: "hello", delivery: "now" },
    ]);
  });

  test("typing a slash command is not announced, and viewers never announce", async () => {
    const fake = session();
    const setup = await mount(fake);
    await setup.mockInput.typeText("/mo");
    await tick(100);
    expect(fake.sent).toEqual([]);

    const viewer = session("viewer");
    const watching = await mount(viewer);
    await watching.mockInput.typeText("hi");
    await tick(100);
    expect(viewer.sent).toEqual([]);
  });

  test("the queue is listed in the panel and /cancel removes an entry", async () => {
    const fake = session();
    const setup = await mount(fake);
    fake.emit({ type: "participant.joined", participant: ALIA });
    fake.emit({ type: "run.started", run_id: "r", prompt_id: "pm0", provenance: GUEST });
    fake.emit({ type: "prompt.accepted", prompt_id: "pm1", author_id: "p_alia", text: "then fix the readme", delivery: "now", provenance: GUEST, attachments: [] });
    fake.emit({ type: "prompt.accepted", prompt_id: "pm2", author_id: "p_alia", text: "and add tests", delivery: "follow_up", provenance: GUEST, attachments: [] });
    const text = await frame(setup, "QUEUE");
    expect(text).toContain("1 Alia");
    expect(text).toContain("then fix the readme");
    expect(text).toContain("2 Alia  after");

    await setup.mockInput.typeText("/cancel 2");
    await setup.mockInput.pressEnter();
    await tick(100);
    expect(fake.sent.at(-1)).toEqual({ type: "queue.cancel", prompt_id: "pm2" });

    fake.emit({ type: "prompt.dequeued", prompt_id: "pm1", reason: "delivered" });
    fake.emit({ type: "prompt.dequeued", prompt_id: "pm2", reason: "cancelled" });
    await tick(100);
    await setup.renderOnce();
    expect(setup.captureCharFrame()).not.toContain("QUEUE");
    expect(setup.captureCharFrame()).toContain("a queued prompt was cancelled");
  });

  test("/cancel explains an empty queue", async () => {
    const fake = session();
    const setup = await mount(fake);
    await setup.mockInput.typeText("/cancel 1");
    await setup.mockInput.pressEnter();
    await frame(setup, "the queue is empty");
    expect(fake.sent).toEqual([]);
  });

  test("F2 opens the settings with three tabs and escape closes them", async () => {
    const setup = await mount(session());
    await setup.mockInput.pressKey("F2");
    const text = await frame(setup, "● Model");
    expect(text).toContain("○ Session");
    expect(text).toContain("○ Appearance");
    await setup.mockInput.pressEscape();
    await tick(100);
    await setup.renderOnce();
    expect(setup.captureCharFrame()).not.toContain("○ Appearance");
  });

  test("the buttons in the panel and the top bar open the settings with the mouse", async () => {
    const setup = await mount(session());
    const text = await frame(setup, "⚙  settings");
    const lines = text.split("\n");
    const row = lines.findIndex((line) => line.includes("⚙  settings"));
    const column = (lines[row] ?? "").indexOf("⚙");
    await setup.mockMouse.click(column + 2, row);
    await frame(setup, "○ Appearance");
    await setup.mockInput.pressEscape();
    await tick(100);
    await setup.renderOnce();
    expect(setup.captureCharFrame()).not.toContain("○ Appearance");

    const top = setup.captureCharFrame().split("\n")[0] ?? "";
    await setup.mockMouse.click(top.lastIndexOf("⚙"), 0);
    await frame(setup, "○ Appearance");
  });

  test("tabs switch with tab and with the mouse", async () => {
    const setup = await mount(session());
    await setup.mockInput.pressKey("F2");
    await frame(setup, "● Model");
    await setup.mockInput.pressTab();
    const session_ = await frame(setup, "Host approves");
    expect(session_).toContain("everyone in the room prompts the agent directly");
    await setup.mockInput.pressTab();
    const look = await frame(setup, "Tokyo Night");
    expect(look).toContain("Daylight");
    expect(look).toContain("High contrast");
    const lines = look.split("\n");
    const row = lines.findIndex((line) => line.includes("● Appearance"));
    const column = (lines[row] ?? "").indexOf("○ Model");
    await setup.mockMouse.click(column + 3, row);
    await frame(setup, "● Model");
  });

  test("choosing a theme and toggling the panel is reported so it can be saved", async () => {
    const saved: Settings[] = [];
    const setup = await testRender(
      <App client={session()} room="r_1" version="0.2.0" guestLink={null} onSettings={(value) => saved.push(value)} onQuit={() => undefined} />,
      { width: 120, height: 40 },
    );
    open.push(setup);
    await setup.renderOnce();
    await setup.mockInput.pressKey("F2");
    await frame(setup, "● Model");
    await setup.mockInput.pressTab();
    await setup.mockInput.pressTab();
    await frame(setup, "Tokyo Night");
    await setup.mockInput.pressArrow("down");
    await setup.mockInput.pressEnter();
    await tick(100);
    for (let step = 0; step < 3; step += 1) {
      await setup.mockInput.pressArrow("down");
    }
    await setup.mockInput.pressEnter();
    await tick(100);
    expect(saved.map((value) => [value.theme, value.panel])).toEqual([
      ["light", true],
      ["light", false],
    ]);
    await setup.mockInput.pressEscape();
    await tick(100);
    await setup.renderOnce();
    expect(setup.captureCharFrame()).not.toContain("PARTICIPANTS");
  });

  test("the host switches the prompt mode from the Session tab, a participant cannot", async () => {
    const fake = session();
    const setup = await mount(fake);
    await setup.mockInput.pressKey("F2");
    await frame(setup, "● Model");
    await setup.mockInput.pressTab();
    await frame(setup, "Host approves");
    await setup.mockInput.pressArrow("down");
    await setup.mockInput.pressEnter();
    await tick(100);
    expect(fake.commands).toEqual([{ type: "session.set_prompt_mode", mode: "review" }]);

    const guest = session("participant");
    const asGuest = await mount(guest);
    await asGuest.mockInput.pressKey("F2");
    await frame(asGuest, "● Model");
    await asGuest.mockInput.pressTab();
    await frame(asGuest, "Host approves");
    await asGuest.mockInput.pressArrow("down");
    await frame(asGuest, "only the host can change this");
    await asGuest.mockInput.pressEnter();
    await tick(100);
    expect(guest.commands).toEqual([]);
  });

  test("keys typed while the settings are open do not reach the prompt", async () => {
    const fake = session();
    const setup = await mount(fake);
    await setup.mockInput.pressKey("F2");
    await frame(setup, "● Model");
    await setup.mockInput.typeText("hello");
    await setup.mockInput.pressEscape();
    await tick(100);
    await setup.mockInput.pressEnter();
    await tick(100);
    expect(fake.commands).toEqual([]);
  });

  test("turning my typing off stops announcing it", async () => {
    const fake = session();
    const setup = await testRender(
      <App
        client={fake}
        room="r_1"
        version="0.2.0"
        guestLink={null}
        settings={{ ...DEFAULT_SETTINGS, announceTyping: false }}
        onQuit={() => undefined}
      />,
      { width: 120, height: 36 },
    );
    open.push(setup);
    await setup.renderOnce();
    await setup.mockInput.typeText("hello");
    await tick(150);
    expect(fake.sent).toEqual([]);
  });

  test("a demo agent is announced and its name shows in the panel", async () => {
    const setup = await mount(session());
    const text = await frame(setup, "demo agent");
    expect(text).toContain("fixed script");
    expect(text).toContain("demo agent (scripted)");
  });

  const DIFF = "--- a/calc.py\n+++ b/calc.py\n@@ -1,3 +1,3 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n";

  function runTool(fake: FakeSession, call: ToolCallView, output: string, ok = true, diff: string | null = null): void {
    fake.emit({ type: "tool.started", run_id: "r", call });
    fake.emit({ type: "tool.ended", run_id: "r", call_id: call.id, ok, output, diff });
  }

  test("a finished tool is one line and ctrl+o opens every tool", async () => {
    const fake = session();
    const setup = await mount(fake);
    runTool(fake, { id: "t1", name: "bash", risk: "exec", subject: "pytest -q", args: {} }, "a\nb\nc\n[exit 0]");
    const collapsed = await frame(setup, "pytest -q");
    expect(collapsed).toContain("▸ ✓ Bash pytest -q · 3 lines");
    expect(collapsed).not.toContain("$ pytest -q");

    await setup.mockInput.pressKey("o", { ctrl: true });
    const open = await frame(setup, "$ pytest -q");
    expect(open).toContain("▾ ✓ Bash");
    expect(open).toContain("c");
    await setup.mockInput.pressKey("o", { ctrl: true });
    await tick(100);
    await setup.renderOnce();
    expect(setup.captureCharFrame()).not.toContain("$ pytest -q");
  });

  test("clicking the line of one tool opens only that tool", async () => {
    const fake = session();
    const setup = await mount(fake);
    runTool(fake, { id: "t1", name: "bash", risk: "exec", subject: "echo first", args: {} }, "first\n[exit 0]");
    runTool(fake, { id: "t2", name: "bash", risk: "exec", subject: "echo second", args: {} }, "second\n[exit 0]");
    const text = await frame(setup, "echo second");
    const lines = text.split("\n");
    const row = lines.findIndex((line) => line.includes("echo second"));
    await setup.mockMouse.click((lines[row] ?? "").indexOf("Bash"), row);
    const open = await frame(setup, "$ echo second");
    expect(open).not.toContain("$ echo first");
    expect(open).toContain("▾ ✓ Bash echo second");
    expect(open).toContain("▸ ✓ Bash echo first");
  });

  test("a failing command shows how it failed on its one line", async () => {
    const fake = session();
    const setup = await mount(fake);
    runTool(fake, { id: "t1", name: "bash", risk: "exec", subject: "pytest", args: {} }, "FAILED test_x\n[exit 1]", false);
    expect(await frame(setup, "exit 1")).toContain("✗ Bash pytest · exit 1");
  });

  test("a running command shows its latest line next to the spinner and the whole tail when open", async () => {
    const fake = session();
    const setup = await mount(fake);
    fake.emit({ type: "tool.started", run_id: "r", call: { id: "t1", name: "bash", risk: "exec", subject: "make all", args: {} } });
    fake.emit({ type: "tool.output", call_id: "t1", chunk: "compiling a\ncompiling b\n" });
    const text = await frame(setup, "compiling b");
    expect(text).toContain("make all");
    expect(text).not.toContain("compiling a");
    await setup.mockInput.pressKey("o", { ctrl: true });
    const open = await frame(setup, "compiling a");
    expect(open).toContain("compiling b");
  });

  test("an edit says what it added and removed and opens into a numbered diff", async () => {
    const fake = session();
    const setup = await mount(fake);
    runTool(fake, { id: "t1", name: "edit", risk: "write", subject: "calc.py", args: {} }, "edited", true, DIFF);
    expect(await frame(setup, "+1 −1")).toContain("✓ Edit calc.py · +1 −1");
    await setup.mockInput.pressKey("o", { ctrl: true });
    const open = await frame(setup, "return a + b");
    expect(open).toMatch(/1\s+def add\(a, b\):/);
    expect(open).toMatch(/2 − {5}return a - b/);
    expect(open).toMatch(/2 \+ {5}return a \+ b/);
  });

  test("a broken diff does not break the card", async () => {
    const fake = session();
    const setup = await mount(fake);
    runTool(fake, { id: "t1", name: "edit", risk: "write", subject: "calc.py", args: {} }, "edited", true, "@@ -1,9 +1,9 @@\n-a\n+b");
    await setup.mockInput.pressKey("o", { ctrl: true });
    expect(await frame(setup, "Edit calc.py")).toContain("+1 −1");
  });
});
