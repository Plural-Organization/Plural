import { afterEach, describe, expect, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { App } from "../src/App";
import type { AgentControl, ControlResult } from "../src/control";
import type { PresetId, AgentConfig } from "../src/presets";
import { DEFAULT_SETTINGS, type Settings } from "../src/settings";
import { ALIA, FakeSession, HOST } from "./support/fake-session";

type Setup = Awaited<ReturnType<typeof testRender>>;

const tick = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

class FakeControl implements AgentControl {
  readonly configured: AgentConfig[] = [];
  readonly tested: AgentConfig[] = [];
  nextConfigure: ControlResult = { ok: true, agent: "anthropic · claude-opus-5-5" };
  nextTest: ControlResult = { ok: true, message: "answered in 0.8s" };

  async configure(config: AgentConfig): Promise<ControlResult> {
    this.configured.push(config);
    return this.nextConfigure;
  }

  async test(config: AgentConfig): Promise<ControlResult> {
    this.tested.push(config);
    return this.nextTest;
  }
}

function session(role: "host" | "participant" = "host", agent = "demo agent (scripted)"): FakeSession {
  const fake = new FakeSession();
  const me = role === "host" ? HOST : ALIA;
  fake.emit({ type: "session.welcome", room: "r_1", token: "t", participant: me, base_policy: [], agent });
  fake.emit({ type: "agent.changed", agent });
  fake.emit({ type: "participant.joined", participant: HOST });
  return fake;
}

const open: Setup[] = [];
afterEach(() => {
  while (open.length > 0) {
    open.pop()?.renderer.destroy();
  }
});

interface Hooks {
  settings: Settings[];
  keys: [PresetId, string, boolean][];
}

async function mount(fake: FakeSession, control: AgentControl | null, settings: Settings = { ...DEFAULT_SETTINGS, setupSeen: true }): Promise<{ setup: Setup; hooks: Hooks }> {
  const hooks: Hooks = { settings: [], keys: [] };
  const setup = await testRender(
    <App
      client={fake}
      room="r_1"
      version="0.2.0"
      guestLink={null}
      settings={settings}
      onSettings={(value) => hooks.settings.push(value)}
      control={control}
      keys={{ gemini: "AIzaStoredKeyFromEarlier0000000000000000" }}
      onKeys={(preset, key, remember) => hooks.keys.push([preset, key, remember])}
      onQuit={() => undefined}
    />,
    { width: 120, height: 40 },
  );
  open.push(setup);
  await setup.renderOnce();
  return { setup, hooks };
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

async function down(setup: Setup, times: number): Promise<void> {
  for (let step = 0; step < times; step += 1) {
    await setup.mockInput.pressArrow("down");
  }
}

describe("Model tab", () => {
  test("the host picks Anthropic, types a key and saves, and the host is configured", async () => {
    const control = new FakeControl();
    const { setup, hooks } = await mount(session(), control);
    await setup.mockInput.pressKey("F2");
    const first = await frame(setup, "Demo agent");
    expect(first).toContain("A scripted agent");

    await setup.mockInput.pressArrow("right");
    const anthropic = await frame(setup, "Anthropic");
    expect(anthropic).toContain("API key");
    expect(anthropic).toContain("not set");
    expect(anthropic).toContain("claude-opus-5-5");

    await down(setup, 1);
    await setup.mockInput.pressEnter();
    await setup.mockInput.typeText("sk-ant-abcdefghijklmnop1234");
    const typing = await frame(setup, "1234▏");
    expect(typing).not.toContain("sk-ant-abcdefghijklmnop1234");
    await setup.mockInput.pressEnter();
    const masked = await frame(setup, "•");
    expect(masked).toContain("1234");
    expect(masked).not.toContain("sk-ant-abcdefghijklmnop1234");

    await down(setup, 4);
    await setup.mockInput.pressEnter();
    await frame(setup, "now using anthropic · claude-opus-5-5");
    expect(control.configured).toEqual([
      {
        provider: "anthropic",
        model: "claude-opus-5-5",
        base_url: null,
        api_key: "sk-ant-abcdefghijklmnop1234",
        context_window: null,
      },
    ]);
    expect(hooks.settings.at(-1)).toMatchObject({
      setupSeen: true,
      agent: { preset: "anthropic" },
      agentChoices: { anthropic: { preset: "anthropic", model: "claude-opus-5-5" } },
    });
    expect(hooks.keys).toEqual([["anthropic", "sk-ant-abcdefghijklmnop1234", true]]);
  });

  test("a missing key is explained and nothing is sent", async () => {
    const control = new FakeControl();
    const { setup, hooks } = await mount(session(), control);
    await setup.mockInput.pressKey("F2");
    await frame(setup, "Demo agent");
    await setup.mockInput.pressArrow("right");
    await frame(setup, "Anthropic");
    await down(setup, 4);
    await setup.mockInput.pressEnter();
    await frame(setup, "Anthropic needs an API key");
    expect(control.configured).toEqual([]);
    expect(hooks.keys).toEqual([]);
  });

  test("testing the connection reports success and failure and changes nothing", async () => {
    const control = new FakeControl();
    const { setup, hooks } = await mount(session(), control);
    await setup.mockInput.pressKey("F2");
    await frame(setup, "Demo agent");
    await setup.mockInput.pressArrow("left");
    await frame(setup, "Custom endpoint");
    await setup.mockInput.pressArrow("left");
    await frame(setup, "Ollama (local)");
    await down(setup, 4);
    await setup.mockInput.pressEnter();
    await frame(setup, "connected, answered in 0.8s");
    expect(control.tested).toEqual([
      {
        provider: "openai",
        model: "qwen3:4b",
        base_url: "http://127.0.0.1:11434/v1",
        api_key: null,
        context_window: null,
      },
    ]);

    control.nextTest = { ok: false, error: "401 invalid api key" };
    await setup.mockInput.pressEnter();
    await frame(setup, "the key was refused (401)");
    expect(control.configured).toEqual([]);
    expect(hooks.settings).toEqual([]);
  });

  test("a local model asks for the endpoint and the context window", async () => {
    const control = new FakeControl();
    const { setup } = await mount(session(), control);
    await setup.mockInput.pressKey("F2");
    await frame(setup, "Demo agent");
    await setup.mockInput.pressArrow("left");
    await frame(setup, "Custom endpoint");
    const custom = await frame(setup, "Endpoint");
    expect(custom).toContain("Context window");
    expect(custom).toContain("API key (optional)");
    await down(setup, 3);
    await setup.mockInput.pressEnter();
    await setup.mockInput.typeText("4096");
    await setup.mockInput.pressEnter();
    await frame(setup, "4096");
  });

  test("a pasted key is accepted without newlines", async () => {
    const control = new FakeControl();
    const { setup } = await mount(session(), control);
    await setup.mockInput.pressKey("F2");
    await frame(setup, "Demo agent");
    await setup.mockInput.pressArrow("right");
    await frame(setup, "Anthropic");
    await down(setup, 1);
    await setup.mockInput.pressEnter();
    await setup.mockInput.pasteBracketedText("sk-ant-pasted-key-9876\n");
    await frame(setup, "9876▏");
    await setup.mockInput.pressEnter();
    await frame(setup, "9876");
  });

  test("a saved key for a provider is offered again when it is chosen", async () => {
    const control = new FakeControl();
    const { setup } = await mount(session(), control);
    await setup.mockInput.pressKey("F2");
    await frame(setup, "Demo agent");
    for (let step = 0; step < 6; step += 1) {
      await setup.mockInput.pressArrow("right");
    }
    const gemini = await frame(setup, "Google Gemini");
    expect(gemini).toContain("0000");
    expect(gemini).toContain("gemini-2.5-pro");
    expect(gemini).not.toContain("AIzaStoredKeyFromEarlier");
  });

  test("a failure to switch is shown and not saved", async () => {
    const control = new FakeControl();
    control.nextConfigure = { ok: false, error: "the agent is busy, wait for the current run to end" };
    const { setup, hooks } = await mount(session(), control);
    await setup.mockInput.pressKey("F2");
    await frame(setup, "Demo agent");
    await setup.mockInput.pressArrow("right");
    await frame(setup, "Anthropic");
    await down(setup, 1);
    await setup.mockInput.pressEnter();
    await setup.mockInput.typeText("sk-ant-abcdefghijklmnop1234");
    await setup.mockInput.pressEnter();
    await down(setup, 4);
    await setup.mockInput.pressEnter();
    await frame(setup, "the agent is busy");
    expect(hooks.settings).toEqual([]);
    expect(hooks.keys).toEqual([]);
  });

  test("a participant is told the agent belongs to the host", async () => {
    const { setup } = await mount(session("participant"), new FakeControl());
    await setup.mockInput.pressKey("F2");
    await frame(setup, "The agent belongs to the host");
  });

  test("the first launch opens the settings with a welcome and closing it is remembered", async () => {
    const { setup, hooks } = await mount(session(), new FakeControl(), { ...DEFAULT_SETTINGS });
    const text = await frame(setup, "Welcome");
    expect(text).toContain("Pick a model to start");
    await setup.mockInput.pressEscape();
    await tick(100);
    await setup.renderOnce();
    expect(setup.captureCharFrame()).not.toContain("Welcome");
    expect(hooks.settings.at(-1)).toMatchObject({ setupSeen: true });
  });

  test("there is no welcome for a real agent, for a repeat launch or for a guest", async () => {
    const real = await mount(session("host", "anthropic · claude-opus-5-5"), new FakeControl(), { ...DEFAULT_SETTINGS });
    await tick(150);
    await real.setup.renderOnce();
    expect(real.setup.captureCharFrame()).not.toContain("Welcome");

    const seen = await mount(session(), new FakeControl(), { ...DEFAULT_SETTINGS, setupSeen: true });
    await tick(150);
    await seen.setup.renderOnce();
    expect(seen.setup.captureCharFrame()).not.toContain("Welcome");

    const guest = await mount(session("participant"), null, { ...DEFAULT_SETTINGS });
    await tick(150);
    await guest.setup.renderOnce();
    expect(guest.setup.captureCharFrame()).not.toContain("Welcome");
  });
});
