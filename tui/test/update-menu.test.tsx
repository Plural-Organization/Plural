import { afterEach, expect, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { App } from "../src/App";
import { DEFAULT_SETTINGS } from "../src/settings";
import { Updater, type Installer } from "../src/update";
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

test("a new release is offered at the top of the settings and installs from there", async () => {
  const installs: Record<string, string>[] = [];
  const install: Installer = async (environment) => {
    installs.push(environment);
    return 0;
  };
  const fetcher = (async () => new Response(JSON.stringify({ tag_name: "v9.9.9" }))) as unknown as typeof fetch;
  const updater = new Updater({ current: "0.2.4", execPath: "/home/me/.local/bin/plural", fetcher, install });
  await updater.check();

  const fake = new FakeSession();
  fake.emit({ type: "session.welcome", room: "r_1", token: "t", participant: HOST, base_policy: [], agent: "anthropic · claude-opus-5-5" });
  fake.emit({ type: "session.snapshot", state: { ...fake.projection.state, participants: { [HOST.id]: HOST } }, streaming: {}, typing: [] });
  const setup = await testRender(
    <App client={fake} room="r_1" version="0.2.4" guestLink={null} updater={updater} settings={{ ...DEFAULT_SETTINGS, setupSeen: true }} onQuit={() => undefined} />,
    { width: 120, height: 40 },
  );
  open.push(setup);
  const bar = await frame(setup, "update 9.9.9");
  expect(bar).toContain("⚙●");
  expect(bar).toContain("update 9.9.9 ready · f2");

  await setup.mockInput.pressKey("F2");
  await frame(setup, "New version available: 0.2.4 → 9.9.9 · install now");
  await setup.mockInput.pressEnter();
  await frame(setup, "9.9.9 installed · restart plural");
  expect(installs).toEqual([{ PLURAL_VERSION: "9.9.9", PLURAL_INSTALL_DIR: "/home/me/.local/bin" }]);
});

test("without a new release the settings carry no marker", async () => {
  const updater = new Updater({ current: "0.2.4", execPath: "/home/me/.local/bin/plural", fetcher: (async () => new Response(JSON.stringify({ tag_name: "v0.2.4" }))) as unknown as typeof fetch });
  await updater.check();
  const fake = new FakeSession();
  fake.emit({ type: "session.welcome", room: "r_1", token: "t", participant: HOST, base_policy: [], agent: "anthropic · claude-opus-5-5" });
  fake.emit({ type: "session.snapshot", state: { ...fake.projection.state, participants: { [HOST.id]: HOST } }, streaming: {}, typing: [] });
  const setup = await testRender(
    <App client={fake} room="r_1" version="0.2.4" guestLink={null} updater={updater} settings={{ ...DEFAULT_SETTINGS, setupSeen: true }} onQuit={() => undefined} />,
    { width: 120, height: 40 },
  );
  open.push(setup);
  const text = await frame(setup, "f2 settings");
  expect(text).not.toContain("⚙●");
  expect(text).not.toContain("ready · f2");
});
