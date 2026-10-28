import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { DEFAULT_CHOICE, isPresetId, type AgentChoice, type PresetId } from "./presets";
import { isShareMode, type ShareMode } from "./share";
import { THEME_NAMES, type ThemeName } from "./theme";

export interface Settings {
  theme: ThemeName;
  panel: boolean;
  copyOnSelect: boolean;
  bell: boolean;
  announceTyping: boolean;
  rememberKey: boolean;
  setupSeen: boolean;
  share: ShareMode;
  relayUrl: string;
  agent: AgentChoice;
  agentChoices: Partial<Record<PresetId, AgentChoice>>;
}

export const DEFAULT_SETTINGS: Settings = {
  theme: "tokyo",
  panel: true,
  copyOnSelect: true,
  bell: false,
  announceTyping: true,
  rememberKey: true,
  setupSeen: false,
  share: "local",
  relayUrl: "",
  agent: DEFAULT_CHOICE,
  agentChoices: {},
};

function parseChoice(raw: unknown): AgentChoice {
  const value = typeof raw === "object" && raw !== null ? (raw as Record<string, unknown>) : {};
  const text = (field: keyof AgentChoice): string => typeof value[field] === "string" ? value[field] as string : "";
  return {
    preset: isPresetId(value["preset"]) ? value["preset"] : DEFAULT_CHOICE.preset,
    model: text("model"),
    baseUrl: text("baseUrl"),
    contextWindow: text("contextWindow"),
  };
}

export function settingsPath(environment: Record<string, string | undefined> = process.env): string {
  const base = environment["PLURAL_DATA_DIR"] ?? join(homedir(), ".plural");
  return join(base, "tui.json");
}

export function parseSettings(raw: unknown): Settings {
  const value = typeof raw === "object" && raw !== null ? (raw as Record<string, unknown>) : {};
  const flag = (key: "panel" | "copyOnSelect" | "bell" | "announceTyping" | "rememberKey" | "setupSeen"): boolean =>
    typeof value[key] === "boolean" ? (value[key] as boolean) : DEFAULT_SETTINGS[key];
  const agent = parseChoice(value["agent"]);
  const rawChoices = typeof value["agentChoices"] === "object" && value["agentChoices"] !== null
    ? value["agentChoices"] as Record<string, unknown> : {};
  const agentChoices: Settings["agentChoices"] = {};
  for (const [preset, rawChoice] of Object.entries(rawChoices)) {
    if (isPresetId(preset) && typeof rawChoice === "object" && rawChoice !== null) {
      agentChoices[preset] = { ...parseChoice(rawChoice), preset };
    }
  }
  return {
    theme: THEME_NAMES.includes(value["theme"] as ThemeName) ? (value["theme"] as ThemeName) : DEFAULT_SETTINGS.theme,
    panel: flag("panel"),
    copyOnSelect: flag("copyOnSelect"),
    bell: flag("bell"),
    announceTyping: flag("announceTyping"),
    rememberKey: flag("rememberKey"),
    setupSeen: flag("setupSeen"),
    share: isShareMode(value["share"]) ? value["share"] : DEFAULT_SETTINGS.share,
    relayUrl: typeof value["relayUrl"] === "string" ? value["relayUrl"] : DEFAULT_SETTINGS.relayUrl,
    agent,
    agentChoices,
  };
}

export function loadSettings(path: string = settingsPath()): Settings {
  try {
    return parseSettings(JSON.parse(readFileSync(path, "utf8")));
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

export function saveSettings(settings: Settings, path: string = settingsPath()): void {
  try {
    mkdirSync(dirname(path), { recursive: true });
    const temporary = `${path}.tmp`;
    writeFileSync(temporary, `${JSON.stringify(settings, null, 2)}\n`, "utf8");
    renameSync(temporary, path);
  } catch {
    return;
  }
}
