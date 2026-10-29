import { afterEach, expect, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import type { ApprovalView } from "@plural/client";
import { App } from "../src/App";
import { DEFAULT_SETTINGS } from "../src/settings";
import { FakeSession, HOST } from "./support/fake-session";

type Setup = Awaited<ReturnType<typeof testRender>>;
const open: Setup[] = [];
afterEach(() => {
  while (open.length > 0) {
    open.pop()?.renderer.destroy();
  }
});

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

function approval(warnings: string[]): ApprovalView {
  return {
    id: "a_1",
    call: { id: "t1", name: "edit", risk: "write", subject: "src/auth.py", args: {} },
    provenance: { initiator_id: "p_host", initiator_role: "host", origin: "direct" },
    timeout_at: new Date(Date.now() + 120_000).toISOString(),
    suggested_patterns: [],
    warnings,
  };
}

async function mount(warnings: string[]): Promise<Setup> {
  const fake = new FakeSession();
  fake.emit({ type: "session.welcome", room: "r_1", token: "t", participant: HOST, base_policy: [], agent: "x" });
  fake.emit({ type: "session.snapshot", state: { ...fake.projection.state, participants: { [HOST.id]: HOST } }, streaming: {}, typing: [] });
  const setup = await testRender(
    <App client={fake} room="r_1" version="0.2.5" guestLink={null} settings={{ ...DEFAULT_SETTINGS, setupSeen: true }} onQuit={() => undefined} />,
    { width: 120, height: 40 },
  );
  open.push(setup);
  fake.emit({ type: "approval.requested", approval: approval(warnings) });
  return setup;
}

test("an edit of a file a teammate changed shows the warning on the approval card", async () => {
  const setup = await mount(["src/auth.py was also changed by alia 3 min ago on feat/x", "src/auth.py was also changed by bek 9 min ago"]);
  const text = await frame(setup, "approval needed");
  expect(text).toContain("⚠ src/auth.py was also changed by alia 3 min ago on feat/x");
  expect(text).toContain("⚠ src/auth.py was also changed by bek 9 min ago");
});

test("an approval with nothing to warn about shows no warning", async () => {
  const setup = await mount([]);
  const text = await frame(setup, "approval needed");
  expect(text).not.toContain("⚠");
});
