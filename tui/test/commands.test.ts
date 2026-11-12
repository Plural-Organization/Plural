import { describe, expect, test } from "bun:test";
import { COMMANDS, pluginHints, suggestions, visibleSuggestionWindow, shortcutCommand } from "../src/commands";

describe("command suggestions", () => {
  test("keeps the selected command in the visible window", () => {
    const window = visibleSuggestionWindow(COMMANDS, 6);

    expect(window.items).toHaveLength(6);
    expect(window.items[window.selectedIndex]?.name).toBe(COMMANDS[6]?.name);
  });

  test("clamps the window at the beginning and end", () => {
    expect(visibleSuggestionWindow(COMMANDS, 0).items[0]?.name).toBe(COMMANDS[0]?.name);

    const last = visibleSuggestionWindow(COMMANDS, COMMANDS.length - 1);
    expect(last.items.at(-1)?.name).toBe(COMMANDS.at(-1)?.name);
    expect(last.items[last.selectedIndex]?.name).toBe(COMMANDS.at(-1)?.name);
  });
});

describe("plugin commands", () => {
  const views = [
    { name: "deploy", plugin: "ops", description: "ship it", usage: "/deploy <env>", host_only: true, shortcut: "f5" },
    { name: "hello", plugin: "fun", description: "", usage: "/hello", host_only: false, shortcut: "ctrl+g" },
  ];
  const plugins = pluginHints(views);

  test("are suggested next to the built-in commands", () => {
    expect(suggestions("/he", "participant", [], plugins).map((hint) => hint.name)).toEqual(["help", "hello"]);
    expect(plugins[1]?.description).toBe("from the fun plugin");
  });

  test("run from their shortcut, host-only ones for the host alone", () => {
    expect(shortcutCommand(views, { name: "g", ctrl: true }, "participant")?.name).toBe("hello");
    expect(shortcutCommand(views, { name: "g", ctrl: false }, "participant")).toBeUndefined();
    expect(shortcutCommand(views, { name: "f5", ctrl: false }, "participant")).toBeUndefined();
    expect(shortcutCommand(views, { name: "f5", ctrl: false }, "host")?.name).toBe("deploy");
  });

  test("hide host-only plugin commands from guests", () => {
    expect(suggestions("/dep", "participant", [], plugins)).toEqual([]);
    expect(suggestions("/dep", "host", [], plugins).map((hint) => hint.usage)).toEqual(["/deploy <env>"]);
  });
});
