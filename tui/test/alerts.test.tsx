import { afterEach, describe, expect, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { Alerts } from "../src/alerts";
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

async function mount(alerts: Alerts): Promise<Setup> {
  const fake = new FakeSession();
  fake.emit({ type: "session.welcome", room: "r_1", token: "t", participant: HOST, base_policy: [], agent: "anthropic · claude-opus-5-5" });
  fake.emit({ type: "participant.joined", participant: HOST });
  const setup = await testRender(
    <App client={fake} room="r_1" version="0.2.0" guestLink={null} settings={{ ...DEFAULT_SETTINGS, setupSeen: true }} alerts={alerts} onQuit={() => undefined} />,
    { width: 120, height: 40 },
  );
  open.push(setup);
  await setup.renderOnce();
  return setup;
}

async function frame(setup: Setup, includes: string): Promise<string> {
  const deadline = Date.now() + 3000;
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

describe("alerts", () => {
  test("a message sent before anyone listens is kept and delivered once", () => {
    const alerts = new Alerts();
    alerts.emit("danger", "early");
    const seen: string[] = [];
    alerts.subscribe((_tone, text) => seen.push(text));
    alerts.subscribe((_tone, text) => seen.push(`second:${text}`));
    alerts.emit("warn", "later");
    expect(seen).toEqual(["early", "later", "second:later"]);
  });

  test("a listener that left hears nothing", () => {
    const alerts = new Alerts();
    const seen: string[] = [];
    const leave = alerts.subscribe((_tone, text) => seen.push(text));
    leave();
    alerts.emit("warn", "x");
    expect(seen).toEqual([]);
  });

  test("an alert appears in the conversation, also when it came before the screen", async () => {
    const alerts = new Alerts();
    alerts.emit("danger", "the cloudflared tunnel stopped early");
    const setup = await mount(alerts);
    await frame(setup, "the cloudflared tunnel stopped early");
    alerts.emit("danger", "the cloudflared tunnel stopped later");
    await frame(setup, "the cloudflared tunnel stopped later");
  });
});
