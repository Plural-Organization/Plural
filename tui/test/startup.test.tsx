import { afterEach, expect, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import type { Command } from "@plural/client";
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

async function mount(fake: FakeSession, startup: Command[], initialPrompt: string | null): Promise<void> {
  const setup = await testRender(
    <App client={fake} room="r_1" version="0.2.1" guestLink={null} settings={{ ...DEFAULT_SETTINGS, setupSeen: true }} startup={startup} initialPrompt={initialPrompt} onQuit={() => undefined} />,
    { width: 120, height: 36 },
  );
  open.push(setup);
  await setup.renderOnce();
}

function online(fake: FakeSession): void {
  fake.emit({ type: "session.welcome", room: "r_1", token: "t", participant: HOST, base_policy: [], agent: "demo agent (scripted)" });
  fake.emit({ type: "participant.joined", participant: HOST });
}

const wait = (ms = 150) => new Promise((resolve) => setTimeout(resolve, ms));

test("the startup commands are sent once the session is up, then the first prompt", async () => {
  const fake = new FakeSession();
  await mount(fake, [{ type: "session.set_permission_mode", mode: "plan" }, { type: "policy.add", tool: "bash", pattern: "git *", action: "allow" }], "fix the failing test");
  await wait();
  expect(fake.commands).toEqual([]);
  online(fake);
  await wait();
  expect(fake.commands).toEqual([
    { type: "session.set_permission_mode", mode: "plan" },
    { type: "policy.add", tool: "bash", pattern: "git *", action: "allow" },
    { type: "prompt.submit", text: "fix the failing test", delivery: "now" },
  ]);
});

test("they are not sent again when the connection comes back", async () => {
  const fake = new FakeSession();
  await mount(fake, [], "do it once");
  online(fake);
  await wait();
  online(fake);
  fake.emit({ type: "participant.joined", participant: { ...HOST, name: "vlad2" } });
  await wait();
  expect(fake.commands.filter((command) => command.type === "prompt.submit")).toHaveLength(1);
});

test("a first prompt can be a team message or a command like any typed line", async () => {
  const fake = new FakeSession();
  await mount(fake, [], "/team standup in five");
  online(fake);
  await wait();
  expect(fake.commands).toEqual([{ type: "chat.send", text: "standup in five", to: null, mentions: [] }]);
});

test("nothing is sent without a first prompt or commands", async () => {
  const fake = new FakeSession();
  await mount(fake, [], null);
  online(fake);
  await wait();
  expect(fake.commands).toEqual([]);
});
