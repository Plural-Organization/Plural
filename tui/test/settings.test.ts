import { afterEach, describe, expect, test } from "bun:test";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DEFAULT_SETTINGS, loadSettings, parseSettings, saveSettings, settingsPath } from "../src/settings";
import { THEME_NAMES, THEMES, colorFor, setTheme, theme } from "../src/theme";

afterEach(() => setTheme("tokyo"));

describe("settings", () => {
  test("missing, broken or foreign files fall back to the defaults", () => {
    const directory = mkdtempSync(join(tmpdir(), "plural-settings-"));
    expect(loadSettings(join(directory, "absent.json"))).toEqual(DEFAULT_SETTINGS);
    writeFileSync(join(directory, "broken.json"), "{not json");
    expect(loadSettings(join(directory, "broken.json"))).toEqual(DEFAULT_SETTINGS);
    expect(parseSettings(null)).toEqual(DEFAULT_SETTINGS);
    expect(parseSettings({ theme: "neon", panel: "yes", bell: 1 })).toEqual(DEFAULT_SETTINGS);
  });

  test("request sounds default to on and an explicit mute is preserved", () => {
    expect(parseSettings({}).bell).toBe(true);
    expect(parseSettings({ bell: false }).bell).toBe(false);
  });

  test("valid values are kept and saving round-trips", () => {
    const directory = mkdtempSync(join(tmpdir(), "plural-settings-"));
    const path = join(directory, "nested", "tui.json");
    const chosen = {
      ...DEFAULT_SETTINGS,
      theme: "gruvbox" as const,
      panel: false,
      copyOnSelect: false,
      bell: true,
      joinBell: false,
      announceTyping: false,
      rememberKey: false,
      setupSeen: true,
      share: "relay" as const,
      relayUrl: "wss://relay.example.com",
      agent: { preset: "gemini" as const, model: "gemini-2.5-flash", baseUrl: "", contextWindow: "" },
      agentChoices: {
        gemini: { preset: "gemini" as const, model: "gemini-2.5-flash", baseUrl: "", contextWindow: "" },
        anthropic_oauth: { preset: "anthropic_oauth" as const, model: "claude-haiku-4-5-20251001", baseUrl: "", contextWindow: "" },
      },
    };
    saveSettings(chosen, path);
    expect(JSON.parse(readFileSync(path, "utf8"))).toEqual(chosen);
    expect(loadSettings(path)).toEqual(chosen);
  });

  test("stored provider choices keep any preset name for the host to check, and old settings still load", () => {
    expect(parseSettings({ agent: { preset: "anthropic_oauth", model: "claude-haiku-4-5" } }).agentChoices).toEqual({});
    expect(parseSettings({ agentChoices: {
      anthropic_oauth: { preset: "demo", model: "claude-haiku-4-5-20251001" },
      unknown: { preset: "unknown", model: "x" },
      "Bad Name": { preset: "Bad Name", model: "x" },
    } }).agentChoices).toEqual({
      anthropic_oauth: { preset: "anthropic_oauth", model: "claude-haiku-4-5-20251001", baseUrl: "", contextWindow: "" },
      unknown: { preset: "unknown", model: "x", baseUrl: "", contextWindow: "" },
    });
  });

  test("the sharing choice falls back to this machine when it is not valid", () => {
    expect(parseSettings({}).share).toBe("local");
    expect(parseSettings({ share: "everywhere", relayUrl: 7 })).toMatchObject({ share: "local", relayUrl: "" });
    expect(parseSettings({ share: "network", relayUrl: "wss://r.example.com" })).toMatchObject({
      share: "network",
      relayUrl: "wss://r.example.com",
    });
  });

  test("the file lives in the data directory", () => {
    expect(settingsPath({ PLURAL_DATA_DIR: "/data" })).toBe("/data/tui.json");
    expect(settingsPath({})).toEndWith("/.plural/tui.json");
  });
});

describe("themes", () => {
  test("every theme defines every colour as a hex value", () => {
    const keys = Object.keys(THEMES.tokyo.colors).sort();
    for (const name of THEME_NAMES) {
      const colors = THEMES[name].colors;
      expect(Object.keys(colors).sort()).toEqual(keys);
      for (const [key, value] of Object.entries(colors)) {
        if (key === "people") {
          expect((value as string[]).length).toBe(8);
        } else {
          expect(value).toMatch(/^#[0-9a-f]{6}$/);
        }
      }
    }
  });

  test("switching changes the live palette and the colour of a person", () => {
    const before = colorFor("p_alia");
    setTheme("light");
    expect(theme.bg).toBe(THEMES.light.colors.bg);
    expect(colorFor("p_alia")).not.toBe(before);
    setTheme("tokyo");
    expect(colorFor("p_alia")).toBe(before);
  });
});
