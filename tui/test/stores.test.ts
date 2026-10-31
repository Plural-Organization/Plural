import { describe, expect, test } from "bun:test";
import { mkdtempSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { ControlLink, type ControlResult } from "../src/control";
import { credentialsPath, loadKeys, parseKeys, saveKeys } from "../src/credentials";
import { DEFAULT_CHOICE, presetOf, presets, problemWith, toConfig } from "../src/presets";
import { DEFAULT_SETTINGS, loadSettings, parseSettings, saveSettings } from "../src/settings";
import { friendlyError, maskKey, nextConnection, nextModel, nextPreset, nextPresetInConnection, switchConnection, switchPreset } from "../src/settingsModel";

describe("credentials", () => {
  test("keys are stored for the owner only and never next to the preferences", () => {
    const directory = mkdtempSync(join(tmpdir(), "plural-keys-"));
    const path = join(directory, "sub", "credentials.json");
    expect(saveKeys({ anthropic: "sk-ant-secret-0123456789" }, path)).toBe(true);
    expect(statSync(path).mode & 0o777).toBe(0o600);
    expect(statSync(join(directory, "sub")).mode & 0o777).toBe(0o700);
    expect(loadKeys(path)).toEqual({ anthropic: "sk-ant-secret-0123456789" });

    const settingsPath = join(directory, "tui.json");
    saveSettings({ ...DEFAULT_SETTINGS, agent: { preset: "anthropic", model: "claude-opus-5-5", baseUrl: "", contextWindow: "" } }, settingsPath);
    expect(readFileSync(settingsPath, "utf8")).not.toContain("secret");
    expect(readFileSync(settingsPath, "utf8")).not.toContain("sk-ant");
  });

  test("a broken or foreign file gives no keys and the path follows the data directory", () => {
    const directory = mkdtempSync(join(tmpdir(), "plural-keys-"));
    writeFileSync(join(directory, "bad.json"), "{nope");
    expect(loadKeys(join(directory, "bad.json"))).toEqual({});
    expect(loadKeys(join(directory, "absent.json"))).toEqual({});
    expect(parseKeys({ keys: { a: "x", b: 5, c: "" } })).toEqual({ a: "x" });
    expect(parseKeys([])).toEqual({});
    expect(credentialsPath({ PLURAL_DATA_DIR: "/data" })).toBe("/data/credentials.json");
  });

  test("overwriting keeps the permissions", () => {
    const directory = mkdtempSync(join(tmpdir(), "plural-keys-"));
    const path = join(directory, "credentials.json");
    saveKeys({ a: "one-0123456789" }, path);
    saveKeys({ a: "two-0123456789" }, path);
    expect(statSync(path).mode & 0o777).toBe(0o600);
    expect(loadKeys(path)).toEqual({ a: "two-0123456789" });
  });
});

describe("agent settings", () => {
  test("the chosen provider survives a round trip and bad values fall back", () => {
    const chosen = { ...DEFAULT_SETTINGS, agent: { preset: "ollama" as const, model: "qwen3:4b", baseUrl: "http://x/v1", contextWindow: "4096" } };
    expect(parseSettings(JSON.parse(JSON.stringify(chosen)))).toEqual(chosen);
    expect(parseSettings({ agent: { preset: "skynet", model: 5 } }).agent).toEqual({ ...DEFAULT_CHOICE, preset: "skynet" });
    expect(parseSettings({ agent: { preset: 7 } }).agent).toEqual(DEFAULT_CHOICE);
    expect(loadSettings("/definitely/missing/tui.json").agent).toEqual(DEFAULT_CHOICE);
  });
});

describe("presets", () => {
  test("every preset is well formed", () => {
    expect(new Set(presets().map((preset) => preset.id)).size).toBe(presets().length);
    for (const preset of presets()) {
      expect(preset.label).not.toBe("");
      if (preset.provider === "openai" && !preset.editableUrl && preset.id !== "openai") {
        expect(preset.baseUrl).toStartWith("https://");
      }
    }
    expect(presetOf("gemini").baseUrl).toContain("generativelanguage.googleapis.com");
  });

  test("a choice becomes the host's config", () => {
    expect(toConfig({ preset: "anthropic", model: "", baseUrl: "", contextWindow: "" }, " sk-ant-x ")).toEqual({
      preset: "anthropic",
      provider: "anthropic",
      provider_name: "Anthropic",
      model: "claude-opus-5-5",
      base_url: null,
      api_key: "sk-ant-x",
      context_window: null,
      fast_model: "",
    });
    expect(toConfig({ preset: "gemini", model: "gemini-2.5-flash", baseUrl: "ignored", contextWindow: "9" }, "k")).toEqual({
      preset: "gemini",
      provider: "openai",
      provider_name: "Google Gemini",
      model: "gemini-2.5-flash",
      base_url: "https://generativelanguage.googleapis.com/v1beta/openai/",
      api_key: "k",
      context_window: null,
      fast_model: "",
    });
    expect(toConfig({ preset: "custom", model: "m", baseUrl: " http://h/v1 ", contextWindow: "2048" }, "")).toEqual({
      preset: "custom",
      provider: "openai",
      provider_name: "Custom endpoint",
      model: "m",
      base_url: "http://h/v1",
      api_key: null,
      context_window: 2048,
      fast_model: "",
    });
    expect(toConfig(DEFAULT_CHOICE, "")).toMatchObject({ provider: "fake", api_key: null });
    expect(toConfig({ preset: "nvidia", model: "", baseUrl: "", contextWindow: "" }, "nvapi-test")).toMatchObject({
      provider: "openai", model: "meta/llama-3.3-70b-instruct", base_url: "https://integrate.api.nvidia.com/v1", api_key: "nvapi-test",
    });
    expect(toConfig({ preset: "azure", model: "my-deployment", baseUrl: "https://my-resource.openai.azure.com/openai/v1/", contextWindow: "" }, "azure-test")).toMatchObject({
      provider: "openai", model: "my-deployment", base_url: "https://my-resource.openai.azure.com/openai/v1/", api_key: "azure-test",
    });
    expect(toConfig({ preset: "amazon_bedrock", model: "openai.gpt-oss-20b-1:0", baseUrl: "https://bedrock-runtime.us-west-2.amazonaws.com/openai/v1", contextWindow: "" }, "bedrock-test")).toMatchObject({
      provider: "openai", model: "openai.gpt-oss-20b-1:0", base_url: "https://bedrock-runtime.us-west-2.amazonaws.com/openai/v1", api_key: "bedrock-test",
    });
    expect(toConfig({ preset: "claude_code", model: "", baseUrl: "", contextWindow: "" }, "")).toMatchObject({
      provider: "claude_code", model: "claude-sonnet-5-5", api_key: null,
    });
  });

  test("what is missing is named", () => {
    expect(problemWith({ preset: "anthropic", model: "", baseUrl: "", contextWindow: "" }, "")).toBe("Anthropic needs an API key");
    expect(problemWith({ preset: "custom", model: "", baseUrl: "http://h", contextWindow: "" }, "")).toBe("choose a model");
    expect(problemWith({ preset: "custom", model: "m", baseUrl: "", contextWindow: "" }, "")).toBe("enter the endpoint address");
    expect(problemWith({ preset: "azure", model: "", baseUrl: "https://resource/openai/v1/", contextWindow: "" }, "key")).toBe("choose a model");
    expect(problemWith({ preset: "azure", model: "deployment", baseUrl: "", contextWindow: "" }, "key")).toBe("enter the endpoint address");
    expect(problemWith({ preset: "ollama", model: "", baseUrl: "", contextWindow: "lots" }, "")).toBe("the context window must be a whole number of tokens");
    expect(problemWith({ preset: "ollama", model: "", baseUrl: "", contextWindow: "4096" }, "")).toBeNull();
    expect(problemWith(DEFAULT_CHOICE, "")).toBeNull();
  });

  test("cycling wraps around and keeps to the suggestions", () => {
    expect(nextPreset("demo", 1)).toBe("anthropic");
    expect(nextPreset("anthropic", -1)).toBe("demo");
    expect(nextModel({ preset: "anthropic", model: "", baseUrl: "", contextWindow: "" }, 1)).toBe("claude-opus-5-5");
    expect(nextModel({ preset: "anthropic", model: "claude-fable-5-1", baseUrl: "", contextWindow: "" }, 1)).toBe("claude-opus-5-5");
    expect(nextModel({ preset: "custom", model: "mine", baseUrl: "", contextWindow: "" }, 1)).toBe("mine");
    expect(presetOf("anthropic_oauth").models).toHaveLength(14);
    expect(presetOf("anthropic_oauth").models[0]).toBe("claude-haiku-4-5-20251001");
  });

  test("switching providers restores the previous model choice", () => {
    const oauth = { preset: "anthropic_oauth" as const, model: "claude-sonnet-5-5", baseUrl: "", contextWindow: "" };
    const saved = { anthropic_oauth: oauth };
    const next = switchPreset(oauth, saved, 1);
    const back = switchPreset(next.choice, next.saved, -1);
    expect(back.choice).toEqual(oauth);
    expect(back.saved.anthropic_oauth).toEqual(oauth);
  });

  test("connections are grouped by authentication and providers cycle within a group", () => {
    expect(presetOf(nextConnection("anthropic_oauth", 1)).connection).toBe("api_key");
    expect(presetOf(nextConnection("openai", 1)).connection).toBe("local");
    expect(nextPresetInConnection("anthropic_oauth", 1)).toBe("claude_code");
    expect(presetOf(nextPresetInConnection("openrouter", 1)).connection).toBe("api_key");

    const current = { preset: "anthropic_oauth" as const, model: "claude-sonnet-5-5", baseUrl: "", contextWindow: "" };
    const moved = switchConnection(current, {}, 1);
    expect(moved.choice.preset).toBe("anthropic");
    expect(moved.saved.anthropic_oauth).toEqual(current);
    expect(switchPreset(moved.choice, moved.saved, 1, true).choice.preset).toBe("openai");
  });

  test("a key is shown only by its tail", () => {
    expect(maskKey("")).toBe("not set");
    expect(maskKey("abc")).toBe("•••");
    expect(maskKey("sk-ant-abcdefghijklmnop1234")).toEndWith("1234");
    expect(maskKey("sk-ant-abcdefghijklmnop1234")).not.toContain("abcdefghij");
  });
});

describe("control link", () => {
  function link() {
    const written: string[] = [];
    return { written, link: new ControlLink((line) => (written.push(line), true)) };
  }

  test("a reply is matched to its request by id", async () => {
    const { written, link: control } = link();
    const first = control.configure({ provider: "fake", model: null, base_url: null, api_key: null, context_window: null });
    const second = control.test({ provider: "fake", model: null, base_url: null, api_key: null, context_window: null });
    const ids = written.map((line) => (JSON.parse(line) as { id: string }).id);
    expect(ids).toEqual(["k1", "k2"]);
    expect(JSON.parse(written[0] as string)).toMatchObject({ type: "configure", config: { provider: "fake" } });

    control.receive('{"type": "result", "id": "k2", "ok": true, "message": "answered in 1s"}\n{"type": "result", "id": "k1", "ok": false, "error": "no"}\n');
    expect(await second).toEqual({ ok: true, message: "answered in 1s" });
    expect(await first).toEqual({ ok: false, error: "no" });
  });

  test("the SDK list comes with the catalog and an install names the SDK to add", async () => {
    const { written, link: control } = link();
    const status = control.extras();
    control.receive('{"type": "result", "id": "k1", "ok": true, "presets": [], "extras": [{"id": "openai", "label": "OpenAI SDK", "installed": false}]}\n');
    expect(await status).toEqual([{ id: "openai", label: "OpenAI SDK", installed: false }]);

    const done = control.install("openai");
    expect(JSON.parse(written[1] as string)).toEqual({ id: "k2", type: "install", extra: "openai" });
    control.receive('{"type": "result", "id": "k2", "ok": true}\n');
    expect(await done).toEqual({ ok: true });
  });

  test("asking for the presets, SDKs and tools together makes one request, and a later ask makes a new one", async () => {
    const { written, link: control } = link();
    const together = Promise.all([control.catalog(), control.extras(), control.tools()]);
    expect(written).toHaveLength(1);
    control.receive(
      '{"type": "result", "id": "k1", "ok": true, "presets": [{"id": "demo"}], "extras": [{"id": "openai", "label": "OpenAI SDK", "installed": true}], "tools": [{"id": "claude"}]}\n',
    );
    const [presets, sdks, installable] = await together;
    expect(presets).toEqual([{ id: "demo" }]);
    expect(sdks).toHaveLength(1);
    expect(installable).toEqual([{ id: "claude" }]);

    const later = control.tools();
    expect(written).toHaveLength(2);
    control.receive('{"type": "result", "id": "k2", "ok": true, "tools": []}\n');
    expect(await later).toEqual([]);
  });

  test("a host that reports no SDKs leaves nothing to offer", async () => {
    const { link: control } = link();
    const status = control.extras();
    control.receive('{"type": "result", "id": "k1", "ok": true, "presets": []}\n');
    expect(await status).toEqual([]);
  });

  test("replies split across chunks and unrelated lines are handled", async () => {
    const { link: control } = link();
    const pending = control.configure({ provider: "fake", model: null, base_url: null, api_key: null, context_window: null });
    control.receive('{"type": "ready"}\nnot json\n{"type": "result", "id": "k1", "ok": tr');
    control.receive('ue, "agent": "demo agent (scripted)"}\n');
    expect(await pending).toEqual({ ok: true, agent: "demo agent (scripted)" });
  });

  test("a host that is gone or silent fails the request instead of hanging", async () => {
    const closed = new ControlLink(() => false);
    expect(await closed.test({ provider: "fake", model: null, base_url: null, api_key: null, context_window: null })).toEqual({
      ok: false,
      error: "the host is not reachable",
    });

    const { link: control } = link();
    const pending: Promise<ControlResult> = control.configure({ provider: "fake", model: null, base_url: null, api_key: null, context_window: null });
    control.close();
    expect(await pending).toEqual({ ok: false, error: "the host stopped" });
  });
});

describe("error messages", () => {
  test("a refused key is said plainly and a provider message is pulled out", () => {
    const refused = "anthropic 401: Error code: 401 - {'type': 'error', 'error': {'type': 'authentication_error', 'message': 'invalid x-api-key'}}";
    expect(friendlyError(refused)).toBe("the key was refused (401): invalid x-api-key");
    expect(friendlyError('openai 429: {"error": {"message": "quota exceeded"}}')).toBe("429: quota exceeded");
    expect(friendlyError("the agent is busy, wait for the current run to end")).toBe("the agent is busy, wait for the current run to end");
    expect(friendlyError("x".repeat(300)).length).toBe(200);
  });
});
