import { afterEach, describe, expect, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { App } from "../src/App";
import type { AgentControl, ControlResult } from "../src/control";
import { setExtras, type ExtraStatus } from "../src/extras";
import { setPresets, type AgentConfig, type Preset } from "../src/presets";
import { DEFAULT_SETTINGS, type Settings } from "../src/settings";
import { setTools, type ToolStatus } from "../src/tools";
import { actionFor, checklist, flat, listing, stepFor } from "../src/setup";
import { TEST_CATALOG } from "./support/catalog";
import { FakeSession, HOST } from "./support/fake-session";

type Setup = Awaited<ReturnType<typeof testRender>>;

const tick = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

const CLAUDE: ToolStatus = { id: "claude", label: "Claude Code CLI", installed: false, command: "npm install -g @anthropic-ai/claude-code", canInstall: true, login: "claude auth login" };
const CODEX: ToolStatus = { id: "codex", label: "Codex CLI", installed: true, command: "npm install -g @openai/codex", canInstall: true, login: "codex login" };
const SDKS: ExtraStatus[] = [
  { id: "anthropic", label: "Anthropic SDK (Claude API and Claude OAuth)", installed: false },
  { id: "openai", label: "OpenAI SDK (OpenAI and OpenAI-compatible servers)", installed: true },
];

class FakeControl implements AgentControl {
  readonly toolsInstalled: string[] = [];
  readonly sdksInstalled: string[] = [];
  readonly tested: AgentConfig[] = [];
  readonly configured: AgentConfig[] = [];
  toolState: ToolStatus[] = [{ ...CLAUDE }, { ...CODEX }];
  sdkState: ExtraStatus[] = SDKS.map((entry) => ({ ...entry }));
  testResult: ControlResult = { ok: true, message: "answered" };
  toolResult: ControlResult = { ok: true };

  async configure(config: AgentConfig): Promise<ControlResult> {
    this.configured.push(config);
    return { ok: true, agent: "Anthropic · claude-opus-5-5" };
  }

  async test(config: AgentConfig): Promise<ControlResult> {
    this.tested.push(config);
    return this.testResult;
  }

  async catalog(): Promise<Preset[]> {
    return TEST_CATALOG;
  }

  async extras(): Promise<ExtraStatus[]> {
    return this.sdkState;
  }

  async install(extra: string): Promise<ControlResult> {
    this.sdksInstalled.push(extra);
    this.sdkState = this.sdkState.map((entry) => (entry.id === extra ? { ...entry, installed: true } : entry));
    return { ok: true };
  }

  async tools(): Promise<ToolStatus[]> {
    return this.toolState;
  }

  async installTool(tool: string): Promise<ControlResult> {
    this.toolsInstalled.push(tool);
    if (this.toolResult.ok) {
      this.toolState = this.toolState.map((entry) => (entry.id === tool ? { ...entry, installed: true } : entry));
    }
    return this.toolResult;
  }
}

const open: Setup[] = [];
afterEach(() => {
  while (open.length > 0) {
    open.pop()?.renderer.destroy();
  }
  setExtras([]);
  setTools([]);
  setPresets(TEST_CATALOG);
});

function session(): FakeSession {
  const fake = new FakeSession();
  const agent = "demo agent (scripted)";
  fake.emit({ type: "session.welcome", room: "r_1", token: "t", participant: HOST, base_policy: [], agent });
  fake.emit({ type: "agent.changed", agent, fast: "" });
  fake.emit({ type: "participant.joined", participant: HOST });
  return fake;
}

interface Hooks {
  settings: Settings[];
  keys: { preset: string; key: string }[];
}

async function mount(control: AgentControl | null, settings: Settings = DEFAULT_SETTINGS): Promise<{ setup: Setup; hooks: Hooks }> {
  const hooks: Hooks = { settings: [], keys: [] };
  setPresets(TEST_CATALOG);
  if (control !== null) {
    setTools((await control.tools?.()) ?? []);
    setExtras(await control.extras());
  }
  const setup = await testRender(
    <App
      client={session()}
      room="r_1"
      version="0.2.0"
      guestLink={null}
      settings={settings}
      onSettings={(value) => hooks.settings.push(value)}
      control={control}
      keys={{}}
      onKeys={(preset, key) => hooks.keys.push({ preset, key })}
      onQuit={() => undefined}
    />,
    { width: 130, height: 40 },
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

const preset = (id: string): Preset => TEST_CATALOG.find((entry) => entry.id === id) as Preset;

describe("what a provider still needs", () => {
  test("the first step is whatever is missing, in the order it can be fixed", () => {
    setTools([CLAUDE, CODEX]);
    setExtras(SDKS);
    expect(stepFor(preset("claude_code"), "", false)).toMatchObject({ kind: "install_tool" });
    expect(stepFor(preset("codex_cli"), "", false)).toEqual({ kind: "use" });
    expect(stepFor(preset("anthropic"), "", false)).toMatchObject({ kind: "install_extra" });
    expect(stepFor(preset("openai"), "", false)).toEqual({ kind: "key" });
    expect(stepFor(preset("openai"), "sk-1", false)).toEqual({ kind: "use" });
    expect(stepFor(preset("ollama"), "", false)).toEqual({ kind: "use" });
    expect(stepFor(preset("custom"), "", false)).toMatchObject({ kind: "settings", problem: "choose a model" });
    expect(stepFor(preset("anthropic_oauth"), "", false)).toEqual({ kind: "install_extra", extra: SDKS[0] as ExtraStatus });
    expect(stepFor(preset("demo"), "", false)).toEqual({ kind: "use" });
  });

  test("the checklist marks what is done and what is not", () => {
    setTools([CLAUDE, CODEX]);
    setExtras(SDKS);
    expect(checklist(preset("claude_code"), "", false).map((item) => [item.label, item.mark])).toEqual([["Claude Code CLI", "todo"]]);
    expect(checklist(preset("codex_cli"), "", false).map((item) => [item.label, item.mark])).toEqual([["Codex CLI", "ok"], ["Sign in", "info"]]);
    expect(checklist(preset("anthropic"), "", false).map((item) => [item.label, item.mark])).toEqual([["Model SDK", "todo"], ["API key", "todo"]]);
    expect(checklist(preset("demo"), "", false)[0]?.mark).toBe("ok");
  });

  test("a missing npm turns the install into a note with the command to run", () => {
    const action = actionFor(preset("claude_code"), { kind: "install_tool", tool: { ...CLAUDE, canInstall: false } });
    expect(action.enabled).toBe(false);
    expect(action.hint).toContain("Install Node.js, then run: npm install -g @anthropic-ai/claude-code");
  });

  test("the first screen is the popular ones and one row for the rest, search and tab widen it", () => {
    const popular = flat(listing(TEST_CATALOG, false, ""), false, "");
    expect(popular.map((entry) => (typeof entry === "string" ? entry : entry.id))).toEqual(["claude_code", "codex_cli", "anthropic", "openai", "gemini", "openrouter", "ollama", "demo", "__more"]);
    const groups = listing(TEST_CATALOG, true, "");
    expect(groups.map((group) => group.title)).toEqual(["Your account", "API key", "Local", "Try it"]);
    expect(listing(TEST_CATALOG, false, "groq")[0]?.items.map((entry) => entry.id)).toEqual(["groq"]);
  });
});

describe("the first launch", () => {
  test("it opens on the popular providers, says what each one needs, and names the next step", async () => {
    const { setup } = await mount(new FakeControl());
    const text = await frame(setup, "Welcome to Plural");
    for (const name of ["Claude Code", "Codex CLI", "Anthropic", "OpenAI", "Google Gemini", "Ollama", "Demo agent", "More providers"]) {
      expect(text).toContain(name);
    }
    expect(text).toContain("Claude Code CLI  not installed");
    expect(text).toContain("Install Claude Code CLI");
    expect(text).toContain("npm install -g @anthropic-ai/claude-code");
  });

  test("a CLI that is missing is installed from the dialog and then it can be used", async () => {
    const control = new FakeControl();
    const { setup, hooks } = await mount(control);
    await frame(setup, "Install Claude Code CLI");
    await setup.mockInput.pressEnter();
    await frame(setup, "✓ Claude Code CLI installed");
    expect(control.toolsInstalled).toEqual(["claude"]);
    const text = await frame(setup, "Use Claude Code");
    expect(text).toContain("Claude Code CLI  installed");

    await setup.mockInput.pressEnter();
    await gone(setup, "Welcome to Plural");
    expect(control.tested).toHaveLength(1);
    expect(control.configured[0]).toMatchObject({ preset: "claude_code", provider: "claude_code" });
    expect(hooks.settings.at(-1)).toMatchObject({ setupSeen: true, agent: { preset: "claude_code" } });
    await frame(setup, "Now using Anthropic · claude-opus-5-5");
  });

  test("a provider with an API key installs its SDK, asks for the key, checks it and uses it", async () => {
    const control = new FakeControl();
    const { setup, hooks } = await mount(control);
    await frame(setup, "Welcome to Plural");
    await setup.mockInput.pressArrow("down");
    await setup.mockInput.pressArrow("down");
    await frame(setup, "Install Anthropic SDK");
    await setup.mockInput.pressEnter();
    await frame(setup, "✓ Anthropic SDK installed");
    expect(control.sdksInstalled).toEqual(["anthropic"]);

    await frame(setup, "Enter your API key");
    await setup.mockInput.pressEnter();
    await frame(setup, "API key: ");
    await setup.mockInput.typeText("sk-ant-abcdefghijklmnop1234");
    await setup.mockInput.pressEnter();
    await frame(setup, "Use Anthropic");

    await setup.mockInput.pressEnter();
    await gone(setup, "Welcome to Plural");
    expect(control.tested[0]).toMatchObject({ preset: "anthropic", api_key: "sk-ant-abcdefghijklmnop1234" });
    expect(hooks.keys).toEqual([{ preset: "anthropic", key: "sk-ant-abcdefghijklmnop1234" }]);
    expect(hooks.settings.at(-1)).toMatchObject({ agent: { preset: "anthropic", model: "claude-opus-5-5" } });
  });

  test("a key that does not work stays on screen with the reason and nothing is switched", async () => {
    const control = new FakeControl();
    control.testResult = { ok: false, error: "401 unauthorized" };
    const { setup, hooks } = await mount(control);
    await frame(setup, "Welcome to Plural");
    await setup.mockInput.pressArrow("down");
    await frame(setup, "Use Codex CLI");
    await setup.mockInput.pressEnter();
    await frame(setup, "the key was refused (401)");
    expect(control.configured).toEqual([]);
    expect(hooks.settings).toEqual([]);
    expect((await frame(setup, "Welcome to Plural")).length).toBeGreaterThan(0);
  });

  test("a failed install says why and keeps the button", async () => {
    const control = new FakeControl();
    control.toolResult = { ok: false, error: "the install failed, run it yourself in a terminal: npm install -g @anthropic-ai/claude-code" };
    const { setup } = await mount(control);
    await frame(setup, "Install Claude Code CLI");
    await setup.mockInput.pressEnter();
    const text = await frame(setup, "the install failed, run it yourself");
    expect(text).toContain("Install Claude Code CLI");
  });

  test("without npm nothing is run and the way to install it by hand is shown", async () => {
    const control = new FakeControl();
    control.toolState = [{ ...CLAUDE, canInstall: false }, { ...CODEX }];
    const { setup } = await mount(control);
    await frame(setup, "npm was not found");
    await setup.mockInput.pressEnter();
    await tick(100);
    expect(control.toolsInstalled).toEqual([]);
  });

  test("skipping keeps the demo agent and is remembered", async () => {
    const control = new FakeControl();
    const { setup, hooks } = await mount(control);
    await frame(setup, "Welcome to Plural");
    await setup.mockInput.pressEscape();
    await gone(setup, "Welcome to Plural");
    expect(control.configured).toEqual([]);
    expect(hooks.settings.at(-1)).toMatchObject({ setupSeen: true });
  });

  test("tab shows every provider by kind and typing narrows them", async () => {
    const { setup } = await mount(new FakeControl());
    await frame(setup, "Welcome to Plural");
    await setup.mockInput.pressTab();
    const all = await frame(setup, "YOUR ACCOUNT");
    expect(all).toContain("API KEY");
    expect(all).toContain("Claude OAuth");
    await setup.mockInput.typeText("deep");
    const found = await frame(setup, "search: deep");
    expect(found).toContain("DeepSeek");
    expect(found).not.toContain("Anthropic");
  });

  test("a provider that needs more than a key is finished in the settings", async () => {
    const control = new FakeControl();
    const { setup, hooks } = await mount(control);
    await frame(setup, "Welcome to Plural");
    await setup.mockInput.typeText("custom");
    await frame(setup, "Set it up in the menu");
    await setup.mockInput.pressEnter();
    await frame(setup, "Custom endpoint");
    await gone(setup, "Welcome to Plural");
    expect(control.configured).toEqual([]);
    expect(hooks.settings.at(-1)).toMatchObject({ setupSeen: true, agent: { preset: "custom" } });
  });

  test("it is not shown for a repeat launch, for a real agent, or to someone who is not the host", async () => {
    const seen = await mount(new FakeControl(), { ...DEFAULT_SETTINGS, setupSeen: true });
    await tick(150);
    await seen.setup.renderOnce();
    expect(seen.setup.captureCharFrame()).not.toContain("Welcome to Plural");
    const guest = await mount(null);
    await tick(150);
    await guest.setup.renderOnce();
    expect(guest.setup.captureCharFrame()).not.toContain("Welcome to Plural");
  });
});

describe("changing the provider later", () => {
  test("the provider row of the menu opens the same screen with every provider and escape comes back", async () => {
    const { setup } = await mount(new FakeControl(), { ...DEFAULT_SETTINGS, setupSeen: true });
    await setup.mockInput.pressKey("F2");
    await frame(setup, "Provider");
    await setup.mockInput.pressEnter();
    const text = await frame(setup, "Choose a provider");
    expect(text).toContain("TRY IT");
    expect(text).toContain("Demo agent");
    await setup.mockInput.pressEscape();
    await gone(setup, "Choose a provider");
    await frame(setup, "Provider");
  });
});
