import type { AgentChoice, LocalServer, Provider, ReadinessState } from "./agent";

// What the picker shows first, in this order; every other provider is under "More".
export const POPULAR: readonly string[] = ["claude_code", "codex_cli", "anthropic", "openai", "gemini", "openrouter", "ollama", "demo"];

export interface Group {
  title: string;
  providers: Provider[];
}

// The providers to list: matches of a search, or Popular and then the rest.
export function groups(providers: readonly Provider[], query: string): Group[] {
  const needle = query.trim().toLowerCase();
  if (needle !== "") {
    const found = providers.filter((provider) => `${provider.label} ${provider.id} ${provider.hint}`.toLowerCase().includes(needle));
    return found.length === 0 ? [] : [{ title: "Results", providers: found }];
  }
  const popular = POPULAR.flatMap((id) => providers.filter((provider) => provider.id === id));
  const more = providers.filter((provider) => !POPULAR.includes(provider.id));
  return [
    ...(popular.length === 0 ? [] : [{ title: "Popular", providers: popular }]),
    ...(more.length === 0 ? [] : [{ title: "More", providers: more }]),
  ];
}

export type Tone = "success" | "warning" | "default";

const STATUS: Record<ReadinessState, { label: string; tone: Tone }> = {
  ready: { label: "Ready", tone: "success" },
  needs_key: { label: "Needs a key", tone: "warning" },
  needs_install: { label: "Not installed", tone: "warning" },
  needs_sdk: { label: "Needs setup", tone: "warning" },
  needs_sign_in: { label: "Sign in", tone: "warning" },
  needs_server: { label: "Not running", tone: "warning" },
};

export function statusOf(provider: Provider): { label: string; tone: Tone } {
  return STATUS[provider.readiness.state];
}

// The choice to start from: what is set now if it is this provider, else what it was last set to.
export function choiceFor(provider: Provider, current: AgentChoice): AgentChoice {
  if (current.preset === provider.id) {
    return { ...current, model: current.model === "" ? (provider.models[0] ?? "") : current.model };
  }
  return provider.saved ?? { preset: provider.id, model: provider.models[0] ?? "", baseUrl: provider.baseUrl, contextWindow: "", fastModel: "" };
}

// The models to offer: what a local server on this computer reports first, then the catalog's.
export function modelOptions(provider: Provider, local: readonly LocalServer[]): string[] {
  const found = local.filter((server) => server.preset === provider.id).flatMap((server) => server.models);
  return [...new Set([...found, ...provider.models])];
}

// Why a choice cannot be used yet, or null. `typedKey` is a key typed but not saved.
export function problemWith(provider: Provider, choice: AgentChoice, typedKey: string): string | null {
  if (provider.needsKey && typedKey.trim() === "" && !provider.key.set) {
    return `${provider.label} needs an API key`;
  }
  const model = choice.model.trim() === "" ? (provider.models[0] ?? "") : choice.model.trim();
  if ((provider.provider === "openai" || provider.provider === "codex_cli") && model === "") {
    return "Choose a model";
  }
  if (provider.provider === "openai" && provider.editableUrl && choice.baseUrl.trim() === "" && provider.baseUrl === "") {
    return "Enter the endpoint address";
  }
  const window = choice.contextWindow.trim();
  if (provider.contextWindow && window !== "" && !/^[1-9]\d*$/.test(window)) {
    return "The context window is a whole number of tokens";
  }
  return null;
}

// What has to happen before the provider answers, as a button; null when nothing is left to do here.
export type Step = { kind: "install"; tool: "claude" | "codex" } | { kind: "sdk"; extra: string } | { kind: "sign-in"; tool: "claude" | "codex" } | { kind: "command"; command: string };

export function stepFor(provider: Provider): Step | null {
  const { state, command } = provider.readiness;
  if (state === "needs_install" && provider.tool !== null) return { kind: "install", tool: provider.tool };
  if (state === "needs_sdk" && provider.extra !== null) return { kind: "sdk", extra: provider.extra };
  if (state === "needs_sign_in" && provider.tool !== null) return { kind: "sign-in", tool: provider.tool };
  return command === null ? null : { kind: "command", command };
}

// Why this choice cannot run yet, or null: a missing field, or a provider that is not ready here.
// A key typed on this page does not block, it is saved when the choice is used.
export function blockerFor(provider: Provider, choice: AgentChoice, typedKey: string): string | null {
  const field = problemWith(provider, choice, typedKey);
  if (field !== null) return field;
  const { state, detail } = provider.readiness;
  if (state === "ready" || (state === "needs_key" && typedKey.trim() !== "")) return null;
  return detail === "" ? "Finish setting this agent up" : detail;
}
