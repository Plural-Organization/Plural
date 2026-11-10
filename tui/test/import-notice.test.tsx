import { afterEach, expect, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
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

test("a session started from another agent's says so when the client comes in", async () => {
  const fake = new FakeSession();
  fake.emit({ type: "session.welcome", room: "r_1", token: "t", participant: HOST, base_policy: [], agent: "x" });
  const item = { id: "bi_1", source: "Claude Code 39b10222", as_of_seq: 120, chars: 4703, at: "2026-11-08T12:00:00Z" };
  fake.emit({ type: "session.snapshot", state: { ...fake.projection.state, participants: { [HOST.id]: HOST }, briefings_imported: [item] }, streaming: {}, typing: [] } as never);
  const setup = await testRender(
    <App client={fake} room="r_1" version="test" guestLink={null} settings={{ ...DEFAULT_SETTINGS, setupSeen: true }} onQuit={() => undefined} />,
    { width: 120, height: 40 },
  );
  open.push(setup);
  let text = "";
  for (let tries = 0; tries < 60 && !text.includes("is in the agent's notes"); tries++) {
    await setup.renderOnce();
    text = setup.captureCharFrame();
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  expect(text).toContain("Claude Code 39b10222 is in the agent's notes (4,703 characters)");
});
