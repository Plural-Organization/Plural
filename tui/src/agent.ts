import type { Keys } from "./credentials";
import { isPresetId, presetOf, PRESETS, problemWith, type AgentChoice, type PresetId } from "./presets";
import type { Settings } from "./settings";
import { UsageError, type SessionOptions } from "./options";

const KEY_VARIABLES: Partial<Record<PresetId, string[]>> = {
  anthropic: ["ANTHROPIC_API_KEY"],
  openai: ["OPENAI_API_KEY"],
  gemini: ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
  openrouter: ["OPENROUTER_API_KEY"],
  groq: ["GROQ_API_KEY"],
  deepseek: ["DEEPSEEK_API_KEY"],
};

export interface AgentPlan {
  choice: AgentChoice | null;
  key: string;
  env: Record<string, string>;
  problem: string | null;
}

export function envKey(preset: PresetId, environment: Record<string, string | undefined>): string {
  for (const name of KEY_VARIABLES[preset] ?? []) {
    const value = environment[name];
    if (value) {
      return value;
    }
  }
  return "";
}

export function planAgent(
  settings: Settings,
  keys: Keys,
  options: Pick<SessionOptions, "provider" | "model" | "effort">,
  environment: Record<string, string | undefined> = process.env,
): AgentPlan {
  const env: Record<string, string> = {};
  if (options.effort !== null) {
    env["PLURAL_EFFORT"] = options.effort;
  }
  let preset = settings.agent.preset;
  if (options.provider !== null) {
    if (!isPresetId(options.provider)) {
      throw new UsageError(`--provider takes one of ${PRESETS.map((entry) => entry.id).join(", ")}`);
    }
    preset = options.provider;
  }
  if (preset === "demo") {
    if (options.model !== null) {
      env["PLURAL_MODEL"] = options.model;
    }
    return { choice: null, key: "", env, problem: null };
  }
  const base: AgentChoice =
    preset === settings.agent.preset
      ? settings.agent
      : (settings.agentChoices[preset] ?? { preset, model: presetOf(preset).models[0] ?? "", baseUrl: "", contextWindow: "" });
  const choice = { ...base, preset, model: options.model ?? base.model };
  const key = keys[preset] ?? envKey(preset, environment);
  return { choice, key, env, problem: problemWith(choice, key) };
}
