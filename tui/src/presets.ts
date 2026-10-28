export type PresetId =
  | "demo"
  | "anthropic"
  | "anthropic_oauth"
  | "claude_code"
  | "codex_cli"
  | "openai"
  | "gemini"
  | "openrouter"
  | "groq"
  | "deepseek"
  | "nvidia"
  | "azure"
  | "ant_ling"
  | "amazon_bedrock"
  | "baseten"
  | "cerebras"
  | "cloudflare_workers_ai"
  | "fireworks"
  | "huggingface"
  | "kimi_coding"
  | "mistral"
  | "minimax"
  | "minimax_cn"
  | "moonshotai"
  | "moonshotai_cn"
  | "qwen_token_plan"
  | "qwen_token_plan_cn"
  | "qwen_token_plan_individual"
  | "together"
  | "vercel_ai_gateway"
  | "xai"
  | "xiaomi"
  | "xiaomi_token_plan_cn"
  | "xiaomi_token_plan_ams"
  | "xiaomi_token_plan_sgp"
  | "zai"
  | "zai_coding_cn"
  | "ollama"
  | "custom";

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
    connection: "api_key",
  },
  {
    id: "anthropic_oauth",
    label: "Claude OAuth",
    provider: "anthropic_oauth",
    baseUrl: "",
    needsKey: false,
    editableUrl: false,
    contextWindow: false,
    models: [
      "claude-haiku-4-5-20251001",
      "claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1",
      "claude-opus-5", "claude-sonnet-5", "claude-fable-5",
      "claude-opus-4-8", "claude-opus-4-7", "claude-sonnet-4-6", "claude-opus-4-6",
      "claude-opus-4-5-20251101", "claude-sonnet-4-5-20250929",
    ],
    hint: "Claude model IDs; Test connection checks access for your account",
    connection: "oauth",
  },
  {
    id: "claude_code",
    label: "Claude Code",
    provider: "claude_code",
    baseUrl: "",
    needsKey: false,
    editableUrl: false,
    contextWindow: false,
    models: [
      "claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5", "claude-fable-5-1",
      "claude-sonnet-5", "claude-opus-5", "claude-fable-5",
      "claude-opus-4-8", "claude-opus-4-7", "claude-sonnet-4-6", "claude-opus-4-6",
      "claude-opus-4-5-20251101", "claude-haiku-4-5-20251001", "claude-sonnet-4-5-20250929",
    ],
    hint: "Uses the installed Claude Code CLI; sign in with claude auth login",
    connection: "oauth",
  },
  {
    id: "codex_cli",
    label: "Codex CLI",
    provider: "codex_cli",
    baseUrl: "",
    needsKey: false,
    editableUrl: false,
    contextWindow: false,
    models: [
      "gpt-6.1-sol", "gpt-6-astra", "gpt-6-sol", "gpt-6-luna", "gpt-5.6-sol", "gpt-5.5",
    ],
    hint: "Streams replies from Codex CLI and keeps one session for this room",
    connection: "oauth",
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
    connection: "api_key",
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
    connection: "api_key",
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
    connection: "api_key",
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
    connection: "api_key",
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
    connection: "api_key",
  },
  {
    id: "nvidia",
    label: "NVIDIA NIM",
    provider: "openai",
    baseUrl: "https://integrate.api.nvidia.com/v1",
    needsKey: true,
    editableUrl: false,
    contextWindow: false,
    models: ["meta/llama-3.3-70b-instruct", "deepseek-ai/deepseek-v4-flash", "meta/llama-3.1-70b-instruct"],
    hint: "NVIDIA NIM OpenAI-compatible endpoint; get a key from build.nvidia.com",
    connection: "api_key",
  },
  {
    id: "azure",
    label: "Azure OpenAI",
    provider: "openai",
    baseUrl: "",
    needsKey: true,
    editableUrl: true,
    contextWindow: false,
    models: [],
    hint: "Enter your Azure resource endpoint and deployment name",
    connection: "api_key",
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
    connection: "local",
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
    connection: "api_key",
  },
  ...([
    ["amazon_bedrock", "Amazon Bedrock API key", "", "openai.gpt-oss-20b-1:0", "Use a Bedrock API key; enter the region's bedrock-runtime /openai/v1 URL"],
    ["ant_ling", "Ant Ling", "https://api.ant-ling.com/v1", "Ring-2.6-1T", "OpenAI-compatible endpoint"],
    ["baseten", "Baseten", "https://inference.baseten.co/v1", "", "OpenAI-compatible endpoint; enter a model ID"],
    ["cerebras", "Cerebras", "https://api.cerebras.ai/v1", "gpt-oss-120b", "Cerebras OpenAI-compatible API"],
    ["cloudflare_workers_ai", "Cloudflare Workers AI", "", "", "Enter the account-scoped OpenAI-compatible endpoint URL"],
    ["fireworks", "Fireworks", "https://api.fireworks.ai/inference/v1", "accounts/fireworks/models/kimi-k3", "OpenAI-compatible API; model catalog may vary by account"],
    ["huggingface", "Hugging Face", "https://router.huggingface.co/v1", "moonshotai/Kimi-K2.6", "Hugging Face Inference Providers OpenAI-compatible router"],
    ["kimi_coding", "Kimi For Coding", "https://api.kimi.com/coding/v1", "kimi-for-coding", "Kimi Coding OpenAI-compatible API; subscription OAuth is not configured here"],
    ["mistral", "Mistral", "https://api.mistral.ai/v1", "devstral-medium-latest", "Mistral chat completions API"],
    ["minimax", "MiniMax", "https://api.minimax.io/anthropic", "MiniMax-M2.7", "Anthropic-compatible Messages API"],
    ["minimax_cn", "MiniMax China", "https://api.minimaxi.com/anthropic", "MiniMax-M2.7", "Anthropic-compatible Messages API"],
    ["moonshotai", "Moonshot AI", "https://api.moonshot.ai/v1", "kimi-k2.6", "OpenAI-compatible endpoint"],
    ["moonshotai_cn", "Moonshot AI China", "https://api.moonshot.cn/v1", "kimi-k2.6", "OpenAI-compatible endpoint"],
    ["qwen_token_plan", "Qwen Token Plan", "https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1", "qwen3-coder-plus", "Qwen Token Plan OpenAI-compatible endpoint"],
    ["qwen_token_plan_cn", "Qwen Token Plan China", "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1", "qwen3-coder-plus", "Qwen Token Plan OpenAI-compatible endpoint"],
    ["qwen_token_plan_individual", "Qwen Token Plan Individual", "https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1", "qwen3-coder-plus", "Qwen Token Plan OpenAI-compatible endpoint"],
    ["together", "Together AI", "https://api.together.ai/v1", "moonshotai/Kimi-K3", "OpenAI-compatible endpoint"],
    ["vercel_ai_gateway", "Vercel AI Gateway", "https://ai-gateway.vercel.sh", "", "Anthropic-compatible Messages API; enter a model route"],
    ["xai", "xAI", "https://api.x.ai/v1", "grok-4.7", "OpenAI-compatible chat completions endpoint"],
    ["xiaomi", "Xiaomi MiMo", "https://api.xiaomimimo.com/v1", "mimo-v2-flash", "OpenAI-compatible endpoint"],
    ["xiaomi_token_plan_cn", "Xiaomi Token Plan China", "https://token-plan-cn.xiaomimimo.com/v1", "mimo-v2-flash", "OpenAI-compatible endpoint"],
    ["xiaomi_token_plan_ams", "Xiaomi Token Plan Amsterdam", "https://token-plan-ams.xiaomimimo.com/v1", "mimo-v2-flash", "OpenAI-compatible endpoint"],
    ["xiaomi_token_plan_sgp", "Xiaomi Token Plan Singapore", "https://token-plan-sgp.xiaomimimo.com/v1", "mimo-v2-flash", "OpenAI-compatible endpoint"],
    ["zai", "Z.AI Coding Plan", "https://api.z.ai/api/coding/paas/v4", "glm-5.3", "Z.AI Coding Plan OpenAI-compatible endpoint"],
    ["zai_coding_cn", "Z.AI Coding Plan China", "https://open.bigmodel.cn/api/coding/paas/v4", "glm-5.3", "Z.AI Coding Plan OpenAI-compatible endpoint"],
  ] as const).map(([id, label, baseUrl, model, hint]) => ({
    id,
    label,
    provider: id === "minimax" || id === "minimax_cn" || id === "vercel_ai_gateway" ? "anthropic" as const : "openai" as const,
    baseUrl,
    needsKey: true,
    editableUrl: baseUrl === "",
    contextWindow: false,
    models: model ? [model] : [],
    hint,
    connection: "api_key" as const,
  })),
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
    connection: "local",
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
  provider: "fake" | "anthropic" | "anthropic_oauth" | "claude_code" | "codex_cli" | "openai";
  provider_name?: string;
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
    provider_name: preset.label,
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
