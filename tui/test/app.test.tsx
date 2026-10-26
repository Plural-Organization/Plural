import { render } from "ink-testing-library";
import { afterEach, describe, expect, test } from "vitest";
import { App } from "../src/App";
import { ALIA, CALL, FakeSession, GUEST, HOST } from "./support/fake-session";

const tick = (ms = 60) => new Promise((resolve) => setTimeout(resolve, ms));

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

let current: ReturnType<typeof render> | null = null;
afterEach(() => {
  current?.unmount();
  current = null;
});

function mount(fake: FakeSession) {
  current = render(<App client={fake} room="r_1" version="0.1.0" guestLink="ws://h/r_1?invite=x" />);
  return current;
}

async function type(app: ReturnType<typeof render>, text: string): Promise<void> {
  for (const char of text) {
    app.stdin.write(char);
    await tick(5);
  }
}

describe("App", () => {
  test("shows the banner and the composer", async () => {
    const app = mount(session());
    await tick();
    const frame = app.lastFrame() ?? "";
    expect(frame).toContain("Message the agent");
    expect(frame).toContain("vlad (host)");
    expect(app.frames.join("\n")).toContain("plural join");
  });

  test("typing a prompt and pressing enter sends it", async () => {
    const fake = session();
    const app = mount(fake);
    await tick();
    await type(app, "hello");
    app.stdin.write("\r");
    await tick();
    expect(fake.sent).toEqual([{ type: "prompt.submit", text: "hello", delivery: "now" }]);
  });

  test("slash commands become protocol commands and unknown ones are explained", async () => {
    const fake = session();
    const app = mount(fake);
    await tick();
    await type(app, "/mode review");
    app.stdin.write("\r");
    await tick();
    expect(fake.sent).toEqual([{ type: "session.set_prompt_mode", mode: "review" }]);
    await type(app, "/nope");
    app.stdin.write("\r");
    await tick();
    expect(app.frames.join("\n")).toContain("unknown command /nope");
  });

  test("the host answers an approval from the keyboard", async () => {
    const fake = session();
    const app = mount(fake);
    fake.emit({ type: "participant.joined", participant: ALIA });
    fake.emit({
      type: "approval.requested",
      approval: { id: "ap1", call: CALL, provenance: GUEST, timeout_at: new Date(Date.now() + 60_000).toISOString(), suggested_patterns: ["rm *"] },
    });
    await tick(150);
    const frame = app.lastFrame() ?? "";
    expect(frame).toContain("approval needed");
    expect(frame).toContain("$ rm a.txt");
    expect(frame).toContain("Alia");
    await tick(500);
    app.stdin.write("n");
    await tick();
    expect(fake.sent).toEqual([{ type: "approval.respond", approval_id: "ap1", decision: "reject" }]);
  });

  test("an approval never steals the keys of a half-typed prompt", async () => {
    const fake = session();
    const app = mount(fake);
    await tick();
    await type(app, "ye");
    fake.emit({ type: "participant.joined", participant: ALIA });
    fake.emit({
      type: "approval.requested",
      approval: { id: "ap1", call: CALL, provenance: GUEST, timeout_at: new Date(Date.now() + 60_000).toISOString(), suggested_patterns: [] },
    });
    await tick(150);
    await type(app, "s");
    await tick();
    expect(app.lastFrame()).toContain("tab: 1 waiting for you");
    expect(app.lastFrame()).toContain("❯ yes");
    expect(fake.sent).toEqual([]);
  });

  test("the host approves a proposal after editing it", async () => {
    const fake = session();
    const app = mount(fake);
    fake.emit({ type: "participant.joined", participant: ALIA });
    fake.emit({ type: "proposal.created", proposal: { id: "pr1", author_id: "p_alia", text: "delete everything", delivery: "now", attachments: [] } });
    await tick(100);
    app.stdin.write("\t");
    await tick();
    expect(app.lastFrame()).toContain("delete everything");
    app.stdin.write("e");
    await tick();
    expect(app.lastFrame()).toContain("editing the proposal");
    app.stdin.write("\r");
    await tick();
    expect(fake.sent).toEqual([
      { type: "proposal.decide", proposal_id: "pr1", decision: "approve", edited_text: "delete everything" },
    ]);
  });

  test("a participant is told that the host reviews prompts, a viewer cannot type", async () => {
    const review = session("participant");
    review.emit({ type: "session.snapshot", state: { ...review.projection.state, prompt_mode: "review" }, streaming: {} });
    const app = mount(review);
    await tick();
    expect(app.lastFrame()).toContain("the host approves it");
    app.unmount();

    const viewer = mount(session("viewer"));
    await tick();
    expect(viewer.lastFrame()).toContain("viewers can only watch");
    await type(viewer, "hi");
    expect(viewer.lastFrame()).not.toContain("❯ hi");
  });

  test("a streamed markdown reply is committed in blocks", async () => {
    const fake = session();
    const app = mount(fake);
    fake.emit({ type: "message.started", run_id: "r", message_id: "m1" });
    fake.emit({ type: "message.delta", message_id: "m1", text: "# Title\n\nFirst **bold** paragraph.\n\n", thinking: false });
    fake.emit({ type: "message.delta", message_id: "m1", text: "- one\n- two\n\n```py\nprint(1)\n```\n\nlast", thinking: false });
    fake.emit({ type: "message.ended", run_id: "r", message_id: "m1", text: "# Title\n\nFirst **bold** paragraph.\n\n- one\n- two\n\n```py\nprint(1)\n```\n\nlast", thinking: "" });
    await tick(150);
    const output = app.lastFrame() ?? "";
    expect(output).toContain("Title");
    expect(output).toContain("• one");
    expect(output).toContain("print(1)");
    expect(output.match(/● plural/g)?.length).toBe(1);
  });
});
