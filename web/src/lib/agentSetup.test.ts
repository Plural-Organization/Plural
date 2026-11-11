import { describe, expect, test } from "vitest";
import type { AgentChoice, Provider } from "./agent";
import { blockerFor, choiceFor, groups, modelOptions, problemWith, statusOf, stepFor } from "./agentSetup";

function provider(over: Partial<Provider> & { id: string }): Provider {
  return {
    label: over.id,
    provider: "openai",
    baseUrl: "",
    needsKey: false,
    editableUrl: false,
    contextWindow: false,
    models: [],
    hint: "",
    connection: "api_key",
    keyEnv: [],
    extra: null,
    tool: null,
    readiness: { state: "ready", detail: "", command: null },
    key: { set: false, source: null, last4: null },
    saved: null,
    ...over,
  };
}

const none: AgentChoice = { preset: "demo", model: "", baseUrl: "", contextWindow: "", fastModel: "" };

describe("groups", () => {
  const all = [provider({ id: "zeta" }), provider({ id: "ollama", label: "Ollama (local)" }), provider({ id: "claude_code", label: "Claude Code" }), provider({ id: "alpha" })];
  test("Popular comes first in its own order and the rest follow in the catalog's", () => {
    const [popular, more] = groups(all, "");
    expect(popular?.title).toBe("Popular");
    expect(popular?.providers.map((p) => p.id)).toEqual(["claude_code", "ollama"]);
    expect(more?.providers.map((p) => p.id)).toEqual(["zeta", "alpha"]);
  });
  test("a search lists only matches, by name or id, in one group", () => {
    expect(groups(all, "  CLAUDE").flatMap((g) => g.providers.map((p) => p.id))).toEqual(["claude_code"]);
    expect(groups(all, "local")[0]?.title).toBe("Results");
    expect(groups(all, "nothing like it")).toEqual([]);
  });
});

test("every state has words and a tone", () => {
  expect(statusOf(provider({ id: "a" }))).toEqual({ label: "Ready", tone: "success" });
  expect(statusOf(provider({ id: "a", readiness: { state: "needs_key", detail: "", command: null } })).tone).toBe("warning");
});

describe("choiceFor", () => {
  test("keeps what is set when it is this provider and fills the first model", () => {
    const p = provider({ id: "anthropic", models: ["m1", "m2"] });
    expect(choiceFor(p, { ...none, preset: "anthropic" }).model).toBe("m1");
    expect(choiceFor(p, { ...none, preset: "anthropic", model: "m2" }).model).toBe("m2");
  });
  test("starts from what the provider was last set to, else its defaults", () => {
    const saved: AgentChoice = { preset: "ollama", model: "qwen3:4b", baseUrl: "http://x/v1", contextWindow: "8192", fastModel: "off" };
    expect(choiceFor(provider({ id: "ollama", saved }), none)).toEqual(saved);
    const fresh = choiceFor(provider({ id: "ollama", models: ["a"], baseUrl: "http://127.0.0.1:11434/v1" }), none);
    expect(fresh).toEqual({ preset: "ollama", model: "a", baseUrl: "http://127.0.0.1:11434/v1", contextWindow: "", fastModel: "" });
  });
});

test("models a local server reports come before the catalog's, without repeats", () => {
  const p = provider({ id: "ollama", models: ["qwen3:4b", "other"] });
  const local = [{ name: "Ollama", preset: "ollama", baseUrl: "", models: ["llama3", "qwen3:4b"] }];
  expect(modelOptions(p, local)).toEqual(["llama3", "qwen3:4b", "other"]);
  expect(modelOptions(p, [])).toEqual(["qwen3:4b", "other"]);
});

describe("problemWith", () => {
  test("a provider with a key needs one typed or saved", () => {
    const p = provider({ id: "anthropic", label: "Anthropic", needsKey: true, models: ["m"] });
    expect(problemWith(p, none, "")).toBe("Anthropic needs an API key");
    expect(problemWith(p, none, "sk-x")).toBeNull();
    expect(problemWith({ ...p, key: { set: true, source: "environment", last4: null } }, none, "")).toBeNull();
  });
  test("an OpenAI-compatible provider needs a model and an address", () => {
    const custom = provider({ id: "custom", editableUrl: true, contextWindow: true });
    expect(problemWith(custom, none, "")).toBe("Choose a model");
    expect(problemWith(custom, { ...none, model: "m" }, "")).toBe("Enter the endpoint address");
    expect(problemWith(custom, { ...none, model: "m", baseUrl: "http://x/v1" }, "")).toBeNull();
    expect(problemWith(custom, { ...none, model: "m", baseUrl: "http://x/v1", contextWindow: "lots" }, "")).toBe("The context window is a whole number of tokens");
  });
});

describe("stepFor", () => {
  const ready = { state: "ready" as const, detail: "", command: null };
  test("a CLI that is missing is installed, then signed in", () => {
    const claude = provider({ id: "claude_code", tool: "claude" });
    expect(stepFor({ ...claude, readiness: { ...ready, state: "needs_install", command: "npm i" } })).toEqual({ kind: "install", tool: "claude" });
    expect(stepFor({ ...claude, readiness: { ...ready, state: "needs_sign_in", command: "claude auth login" } })).toEqual({ kind: "sign-in", tool: "claude" });
  });
  test("an SDK is installed from the page, anything else is a command to copy", () => {
    expect(stepFor(provider({ id: "anthropic", extra: "anthropic", readiness: { ...ready, state: "needs_sdk", command: "uv tool install" } }))).toEqual({ kind: "sdk", extra: "anthropic" });
    expect(stepFor(provider({ id: "ollama", readiness: { ...ready, state: "needs_server", command: "ollama serve" } }))).toEqual({ kind: "command", command: "ollama serve" });
    expect(stepFor(provider({ id: "demo" }))).toBeNull();
  });
});

describe("blockerFor", () => {
  const need = (state: Provider["readiness"]["state"], detail = "") => ({ state, detail, command: null });
  test("a provider that is ready has nothing in the way", () => {
    expect(blockerFor(provider({ id: "a", models: ["m"] }), none, "")).toBeNull();
  });
  test("one that is not ready says why", () => {
    expect(blockerFor(provider({ id: "a", models: ["m"], readiness: need("needs_sign_in", "Claude Code is not signed in") }), none, "")).toBe("Claude Code is not signed in");
    expect(blockerFor(provider({ id: "a", models: ["m"], readiness: need("needs_server") }), none, "")).toBe("Finish setting this agent up");
  });
  test("a key typed here is enough, it is saved when the agent is used", () => {
    const keyed = provider({ id: "a", label: "A", needsKey: true, models: ["m"], readiness: need("needs_key", "A needs an API key") });
    expect(blockerFor(keyed, none, "")).toBe("A needs an API key");
    expect(blockerFor(keyed, none, "sk-x")).toBeNull();
  });
});
