import { afterEach, describe, expect, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { App } from "../src/App";
import type { AgentControl, ControlResult } from "../src/control";
import { setExtras, type ExtraStatus } from "../src/extras";
import type { AgentConfig, Preset } from "../src/presets";
import { DEFAULT_SETTINGS, type Settings } from "../src/settings";
import { TEST_CATALOG } from "./support/catalog";
import { FakeSession, HOST } from "./support/fake-session";

type Setup = Awaited<ReturnType<typeof testRender>>;

const tick = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

const MISSING: ExtraStatus[] = [
  { id: "anthropic", label: "Anthropic SDK (Claude API and Claude OAuth)", installed: false },
  { id: "openai", label: "OpenAI SDK (OpenAI and OpenAI-compatible servers)", installed: false },
];

class FakeControl implements AgentControl {
  readonly installed: string[] = [];
  readonly configured: AgentConfig[] = [];
  state: ExtraStatus[] = MISSING.map((extra) => ({ ...extra }));
  nextInstall: ControlResult = { ok: true };

  async configure(config: AgentConfig): Promise<ControlResult> {
    this.configured.push(config);
    return { ok: true, agent: "Anthropic · claude-opus-5-5" };
  }

  async test(): Promise<ControlResult> {
    return { ok: true, message: "answered" };
  }

  async catalog(): Promise<Preset[]> {
    return TEST_CATALOG;
  }

  async extras(): Promise<ExtraStatus[]> {
    return this.state;
  }

  async install(extra: string): Promise<ControlResult> {
    this.installed.push(extra);
    if (this.nextInstall.ok) {
      this.state = this.state.map((entry) => (entry.id === extra ? { ...entry, installed: true } : entry));
    }
    return this.nextInstall;
  }
}

const open: Setup[] = [];
afterEach(() => {
  while (open.length > 0) {
    open.pop()?.renderer.destroy();
  }
  setExtras([]);
});

function session(): FakeSession {
  const fake = new FakeSession();
  const agent = "demo agent (scripted)";
  fake.emit({ type: "session.welcome", room: "r_1", token: "t", participant: HOST, base_policy: [], agent });
  fake.emit({ type: "agent.changed", agent, fast: "" });
  fake.emit({ type: "participant.joined", participant: HOST });
  return fake;
}

async function mount(control: AgentControl, settings: Settings): Promise<{ setup: Setup; saved: Settings[] }> {
  const saved: Settings[] = [];
  const setup = await testRender(
    <App
      client={session()}
      room="r_1"
      version="0.2.0"
      guestLink={null}
      settings={settings}
      onSettings={(value) => saved.push(value)}
      control={control}
      keys={{}}
      onKeys={() => undefined}
      onQuit={() => undefined}
    />,
    { width: 120, height: 40 },
  );
  open.push(setup);
  await setup.renderOnce();
  return { setup, saved };
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

async function gone(setup: Setup, text: string, timeout = 3000): Promise<void> {
  const deadline = Date.now() + timeout;
  for (;;) {
    await setup.renderOnce();
    if (!setup.captureCharFrame().includes(text)) {
      return;
    }
    if (Date.now() > deadline) {
      throw new Error(`"${text}" never went away`);
    }
    await tick(25);
  }
}

const FIRST_RUN: Settings = { ...DEFAULT_SETTINGS, setupSeen: true };

describe("the offer to install the model SDKs", () => {
  test("a first run without them offers both and names what works without", async () => {
    setExtras(MISSING);
    const { setup } = await mount(new FakeControl(), FIRST_RUN);
    const text = await frame(setup, "model SDKs");
    expect(text).toContain("Anthropic SDK");
    expect(text).toContain("OpenAI SDK");
    expect(text).toContain("Claude Code and Codex CLI work without any");
    expect(text).toContain("Install selected");
    expect(text).toContain("Skip for now");
  });

  test("skipping installs nothing and is remembered so it is not asked again", async () => {
    setExtras(MISSING);
    const control = new FakeControl();
    const { setup, saved } = await mount(control, FIRST_RUN);
    await frame(setup, "model SDKs");
    await setup.mockInput.pressEscape();
    await gone(setup, "model SDKs");
    expect(control.installed).toEqual([]);
    expect(saved.at(-1)).toMatchObject({ extrasSeen: true });
  });

  test("it is not offered again once answered", async () => {
    setExtras(MISSING);
    const { setup } = await mount(new FakeControl(), { ...FIRST_RUN, extrasSeen: true });
    await tick(100);
    await setup.renderOnce();
    expect(setup.captureCharFrame()).not.toContain("model SDKs");
  });

  test("nothing is offered when the SDKs are there or the host does not report them", async () => {
    setExtras(MISSING.map((extra) => ({ ...extra, installed: true })));
    const first = await mount(new FakeControl(), FIRST_RUN);
    await tick(100);
    await first.setup.renderOnce();
    expect(first.setup.captureCharFrame()).not.toContain("model SDKs");
    setExtras([]);
    const second = await mount(new FakeControl(), FIRST_RUN);
    await tick(100);
    await second.setup.renderOnce();
    expect(second.setup.captureCharFrame()).not.toContain("model SDKs");
  });

  test("a participant is never asked: only the host can install", async () => {
    setExtras(MISSING);
    const setup = await testRender(
      <App client={session()} room="r_1" version="0.2.0" guestLink={null} settings={FIRST_RUN} onSettings={() => undefined} control={null} keys={{}} onKeys={() => undefined} onQuit={() => undefined} />,
      { width: 120, height: 40 },
    );
    open.push(setup);
    await tick(100);
    await setup.renderOnce();
    expect(setup.captureCharFrame()).not.toContain("model SDKs");
  });

  test("ticking one and confirming installs only that one", async () => {
    setExtras(MISSING);
    const control = new FakeControl();
    const { setup } = await mount(control, FIRST_RUN);
    await frame(setup, "model SDKs");
    await setup.mockInput.pressKey(" ");
    await frame(setup, "[x] Anthropic SDK");
    await setup.mockInput.pressArrow("down");
    await setup.mockInput.pressArrow("down");
    await setup.mockInput.pressEnter();
    await gone(setup, "model SDKs");
    expect(control.installed).toEqual(["anthropic"]);
  });

  test("confirming with nothing ticked asks to tick something and installs nothing", async () => {
    setExtras(MISSING);
    const control = new FakeControl();
    const { setup } = await mount(control, FIRST_RUN);
    await frame(setup, "model SDKs");
    await setup.mockInput.pressArrow("down");
    await setup.mockInput.pressArrow("down");
    await setup.mockInput.pressEnter();
    await frame(setup, "tick what to install");
    expect(control.installed).toEqual([]);
  });

  test("a failed install stays open and shows why", async () => {
    setExtras(MISSING);
    const control = new FakeControl();
    control.nextInstall = { ok: false, error: "the install failed, run: uv tool install --force 'plural-agent[anthropic]'" };
    const { setup } = await mount(control, FIRST_RUN);
    await frame(setup, "model SDKs");
    await setup.mockInput.pressKey(" ");
    await setup.mockInput.pressArrow("down");
    await setup.mockInput.pressArrow("down");
    await setup.mockInput.pressEnter();
    const text = await frame(setup, "the install failed, run: uv tool install --force");
    expect(text).toContain("model SDKs");
  });

  test("saving a provider whose SDK is missing offers it instead of failing, then comes back", async () => {
    setExtras(MISSING);
    const control = new FakeControl();
    const { setup } = await mount(control, { ...FIRST_RUN, extrasSeen: true });
    await setup.mockInput.pressKey("F2");
    await frame(setup, "Demo agent");
    await setup.mockInput.pressArrow("right");
    await setup.mockInput.pressArrow("right");
    await frame(setup, "Anthropic");
    await setup.mockInput.pressArrow("down");
    await setup.mockInput.pressArrow("down");
    await setup.mockInput.pressEnter();
    await setup.mockInput.typeText("sk-ant-abcdefghijklmnop1234");
    await setup.mockInput.pressEnter();
    for (let step = 0; step < 5; step += 1) {
      await setup.mockInput.pressArrow("down");
    }
    await setup.mockInput.pressEnter();
    const text = await frame(setup, "This provider needs the Anthropic SDK");
    expect(text).toContain("[x] Anthropic SDK");
    expect(text).toContain("[ ] OpenAI SDK");
    expect(control.configured).toEqual([]);

    await setup.mockInput.pressArrow("down");
    await setup.mockInput.pressArrow("down");
    await setup.mockInput.pressEnter();
    await gone(setup, "model SDKs");
    expect(control.installed).toEqual(["anthropic"]);
    await frame(setup, "settings");
  });
});
