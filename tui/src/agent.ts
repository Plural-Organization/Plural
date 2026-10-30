import type { Keys } from "./credentials";
import { isPresetId, presetOf, presets, problemWith, type AgentChoice, type PresetId } from "./presets";
import type { Settings } from "./settings";
import { UsageError, type SessionOptions } from "./options";

export interface AgentPlan {
  choice: AgentChoice | null;
  key: string;
  env: Record<string, string>;
  problem: string | null;
}

/** The key in the preset's own variables, which the host's catalog names (NVIDIA_API_KEY, ...). */
export function envKey(preset: PresetId, environment: Record<string, string | undefined>): string {
  for (const name of presetOf(preset).keyEnv) {
    const value = environment[name];
    if (value) {
      return value;
    }
  }
  return "";
}

/** Environment the host needs at start, before it can answer with its catalog. */
export function agentEnv(
  settings: Settings,
  options: Pick<SessionOptions, "provider" | "model" | "effort">,
): Record<string, string> {
  const env: Record<string, string> = {};
  if (options.effort !== null) {
    env["PLURAL_EFFORT"] = options.effort;
  }
  if ((options.provider ?? settings.agent.preset) === "demo" && options.model !== null) {
    env["PLURAL_MODEL"] = options.model;
  }
  return env;
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
      throw new UsageError(`--provider takes one of ${presets().map((entry) => entry.id).join(", ")}`);
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
