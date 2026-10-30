import catalog from "./catalog.json";

/** A provider preset. The catalog comes from the host's plural.agent.providers.catalog (gen_catalog.py). */
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
  keyEnv: string | null;
}

export const PRESETS: Preset[] = catalog as Preset[];

export function presetOf(id: PresetId): Preset {
  return PRESETS.find((preset) => preset.id === id) ?? (PRESETS.at(-1) as Preset);
}

export function isPresetId(value: unknown): value is PresetId {
  return PRESETS.some((preset) => preset.id === value);
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
