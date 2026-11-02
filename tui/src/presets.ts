/**
 * A provider preset. The catalog lives on the host, in plural.agent.providers.catalog; the client asks the
 * host it started for it (`AgentControl.catalog`) and keeps no copy of its own.
 */
export type PresetId = string;

export interface Preset {
  id: PresetId;
  label: string;
  provider: "fake" | "anthropic" | "anthropic_oauth" | "claude_code" | "codex_cli" | "openai";
  baseUrl: string;
  needsKey: boolean;
  editableUrl: boolean;
  contextWindow: boolean;
  models: string[];
  hint: string;
  connection: "oauth" | "api_key" | "local";
  keyEnv: string[];
  /** The optional SDK this provider needs on the host (see extras.ts), when it needs one. */
  extra?: string | null;
  tool?: string | null;
}

/** What the client shows before the host answers, or when it joins a room it does not host. */
export const DEMO: Preset = {
  id: "demo",
  label: "Demo agent",
  provider: "fake",
  baseUrl: "",
  needsKey: false,
  editableUrl: false,
  contextWindow: false,
  models: [],
  hint: "A scripted agent that needs nothing, to try the interface",
  connection: "local",
  keyEnv: [],
};

let catalog: Preset[] = [DEMO];

export function setPresets(list: readonly Preset[]): void {
  catalog = list.some((preset) => preset.id === DEMO.id) ? [...list] : [...list, DEMO];
}

export function presets(): readonly Preset[] {
  return catalog;
}

export function presetOf(id: PresetId): Preset {
  return catalog.find((preset) => preset.id === id) ?? DEMO;
}

export function isPresetId(value: unknown): value is PresetId {
  return catalog.some((preset) => preset.id === value);
}

export interface AgentChoice {
  preset: PresetId;
  model: string;
  baseUrl: string;
  contextWindow: string;
  fastModel?: string;
}

export const DEFAULT_CHOICE: AgentChoice = { preset: "demo", model: "", baseUrl: "", contextWindow: "" };

export interface AgentConfig {
  preset?: PresetId;
  provider: "fake" | "anthropic" | "anthropic_oauth" | "claude_code" | "codex_cli" | "openai";
  provider_name?: string;
  model: string | null;
  base_url: string | null;
  api_key: string | null;
  context_window: number | null;
  fast_model?: string;
}

export function toConfig(choice: AgentChoice, key: string): AgentConfig {
  const preset = presetOf(choice.preset);
  const window = Number(choice.contextWindow);
  return {
    preset: preset.id,
    provider: preset.provider,
    provider_name: preset.label,
    model: choice.model.trim() || preset.models[0] || null,
    base_url: preset.editableUrl ? choice.baseUrl.trim() || preset.baseUrl || null : preset.baseUrl || null,
    api_key: preset.needsKey || key.trim() !== "" ? key.trim() || null : null,
    context_window: preset.contextWindow && Number.isInteger(window) && window > 0 ? window : null,
    fast_model: choice.fastModel ?? "",
  };
}

export function problemWith(choice: AgentChoice, key: string): string | null {
  const preset = presetOf(choice.preset);
  if (preset.provider === "fake") {
    return null;
  }
  if (preset.needsKey && key.trim() === "") {
    return `${preset.label} needs an API key`;
  }
  const config = toConfig(choice, key);
  if ((preset.provider === "openai" || preset.provider === "codex_cli") && config.model === null) {
    return "choose a model";
  }
  if (preset.provider === "openai" && preset.editableUrl && config.base_url === null) {
    return "enter the endpoint address";
  }
  if (preset.contextWindow && choice.contextWindow.trim() !== "" && config.context_window === null) {
    return "the context window must be a whole number of tokens";
  }
  return null;
}
