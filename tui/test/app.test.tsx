import { afterEach, describe, expect, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { App } from "../src/App";
import { ALIA, CALL, FakeSession, GUEST, HOST } from "./support/fake-session";

type Setup = Awaited<ReturnType<typeof testRender>>;

const tick = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function session(role: "host" | "participant" | "viewer" = "host"): FakeSession {
  const fake = new FakeSession();
  const me = role === "host" ? HOST : { ...ALIA, role };
  fake.emit({ type: "session.welcome", room: "r_1", token: "t", participant: me, base_policy: [] });
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
});
