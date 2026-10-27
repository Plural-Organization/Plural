import { describe, expect, test } from "bun:test";
import { COMMANDS, visibleSuggestionWindow } from "../src/commands";

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
