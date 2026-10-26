import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { THEME_NAMES, type ThemeName } from "./theme";

export interface Settings {
  theme: ThemeName;
  panel: boolean;
  copyOnSelect: boolean;
  bell: boolean;
  announceTyping: boolean;
}

export const DEFAULT_SETTINGS: Settings = {
  theme: "tokyo",
  panel: true,
  copyOnSelect: true,
  bell: false,
  announceTyping: true,
};

export function settingsPath(environment: Record<string, string | undefined> = process.env): string {
  const base = environment["PLURAL_DATA_DIR"] ?? join(homedir(), ".plural");
  return join(base, "tui.json");
}

export function parseSettings(raw: unknown): Settings {
  const value = typeof raw === "object" && raw !== null ? (raw as Record<string, unknown>) : {};
  const flag = (key: keyof Settings): boolean =>
    typeof value[key] === "boolean" ? (value[key] as boolean) : (DEFAULT_SETTINGS[key] as boolean);
  return {
    theme: THEME_NAMES.includes(value["theme"] as ThemeName) ? (value["theme"] as ThemeName) : DEFAULT_SETTINGS.theme,
    panel: flag("panel"),
    copyOnSelect: flag("copyOnSelect"),
    bell: flag("bell"),
    announceTyping: flag("announceTyping"),
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
