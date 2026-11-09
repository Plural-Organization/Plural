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

async function frame(setup: Setup, includes: string): Promise<string> {
  let text = "";
  for (let tries = 0; tries < 80 && !text.includes(includes); tries++) {
    await setup.renderOnce();
    text = setup.captureCharFrame();
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  return text;
}

async function run(importUrl: string | null): Promise<string> {
  const fake = new FakeSession();
  fake.emit({ type: "session.welcome", room: "r_1", token: "t", participant: HOST, base_policy: [], agent: "x" });
  fake.emit({ type: "session.snapshot", state: { ...fake.projection.state, participants: { [HOST.id]: HOST } }, streaming: {}, typing: [] } as never);
  const setup = await testRender(
    <App client={fake} room="r_1" version="test" guestLink={null} importUrl={importUrl} settings={{ ...DEFAULT_SETTINGS, setupSeen: true }} onQuit={() => undefined} />,
    { width: 120, height: 40 },
  );
  open.push(setup);
  await setup.renderOnce();
  await setup.mockInput.typeText("/import");
  await setup.mockInput.pressEnter();
  return frame(setup, importUrl ?? "needs a relay");
}

test("/import shows the address a chat service sends to", async () => {
  const text = await run("https://relay.example/mcp/r_1/abc123");
  expect(text).toContain("https://relay.example/mcp/r_1/abc123");
  expect(text).toContain("custom connector");
});

test("/import says why there is no address without a relay", async () => {
  const text = await run(null);
  expect(text).toContain("needs a relay");
});
