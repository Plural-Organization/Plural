export type PresetId =
  | "demo"
  | "anthropic"
  | "openai"
  | "gemini"
  | "openrouter"
  | "groq"
  | "deepseek"
  | "ollama"
  | "custom";

export interface Preset {
  id: PresetId;
  label: string;
  provider: "fake" | "anthropic" | "openai";
  baseUrl: string;
  needsKey: boolean;
  editableUrl: boolean;
  contextWindow: boolean;
  models: string[];
  hint: string;
}

export const PRESETS: Preset[] = [
  {
    id: "anthropic",
    label: "Anthropic",
    provider: "anthropic",
    baseUrl: "",
    needsKey: true,
    editableUrl: false,
    contextWindow: false,
    models: ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"],
    hint: "Claude models with an Anthropic API key",
  },
  {
    id: "openai",
    label: "OpenAI",
    provider: "openai",
    baseUrl: "",
    needsKey: true,
    editableUrl: false,
    contextWindow: false,
    models: ["gpt-5", "gpt-5-mini"],
    hint: "GPT models with an OpenAI API key",
  },
  {
    id: "gemini",
    label: "Google Gemini",
    provider: "openai",
    baseUrl: "https://generativelanguage.googleapis.com/v1beta/openai/",
    needsKey: true,
    editableUrl: false,
    contextWindow: false,
    models: ["gemini-2.5-pro", "gemini-2.5-flash"],
    hint: "Gemini through its OpenAI-compatible endpoint",
  },
  {
    id: "openrouter",
    label: "OpenRouter",
    provider: "openai",
    baseUrl: "https://openrouter.ai/api/v1",
    needsKey: true,
    editableUrl: false,
    contextWindow: false,
    models: ["anthropic/claude-sonnet-5-5", "openai/gpt-5"],
    hint: "Many models behind one key",
  },
  {
    id: "groq",
    label: "Groq",
    provider: "openai",
    baseUrl: "https://api.groq.com/openai/v1",
    needsKey: true,
    editableUrl: false,
    contextWindow: false,
    models: ["llama-3.3-70b-versatile"],
    hint: "Fast hosted open models",
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    provider: "openai",
    baseUrl: "https://api.deepseek.com",
    needsKey: true,
    editableUrl: false,
    contextWindow: false,
    models: ["deepseek-chat", "deepseek-reasoner"],
    hint: "DeepSeek models",
  },
  {
    id: "ollama",
    label: "Ollama (local)",
    provider: "openai",
    baseUrl: "http://127.0.0.1:11434/v1",
    needsKey: false,
    editableUrl: true,
    contextWindow: true,
    models: ["qwen3:4b", "qwen2.5-coder:3b"],
    hint: "A model on this machine, no key. Set the window the server really uses",
  },
  {
    id: "custom",
    label: "Custom endpoint",
    provider: "openai",
    baseUrl: "",
    needsKey: false,
    editableUrl: true,
    contextWindow: true,
    models: [],
    hint: "Any OpenAI-compatible server",
  },
  {
    id: "demo",
    label: "Demo agent",
    provider: "fake",
    baseUrl: "",
    needsKey: false,
    editableUrl: false,
    contextWindow: false,
    models: [],
    hint: "A scripted agent that needs nothing, to try the interface",
  },
];

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
}

export const DEFAULT_CHOICE: AgentChoice = { preset: "demo", model: "", baseUrl: "", contextWindow: "" };

export interface AgentConfig {
  provider: "fake" | "anthropic" | "openai";
  model: string | null;
  base_url: string | null;
  api_key: string | null;
  context_window: number | null;
}

export function toConfig(choice: AgentChoice, key: string): AgentConfig {
  const preset = presetOf(choice.preset);
  const window = Number(choice.contextWindow);
  return {
    provider: preset.provider,
    model: choice.model.trim() || preset.models[0] || null,
    base_url: preset.editableUrl ? choice.baseUrl.trim() || preset.baseUrl || null : preset.baseUrl || null,
    api_key: preset.needsKey || key.trim() !== "" ? key.trim() || null : null,
    context_window: preset.contextWindow && Number.isInteger(window) && window > 0 ? window : null,
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
  if (preset.provider === "openai" && config.model === null) {
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
