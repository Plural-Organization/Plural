import { expect, test } from "vitest";
import { helpText, isHostOnly, pluginHints, suggestions } from "./commands";

test("suggestions match the typed prefix and hide host commands from guests", () => {
  expect(suggestions("/in", "host").map((hint) => hint.name)).toEqual(["invite"]);
  expect(suggestions("/in", "participant")).toEqual([]);
  expect(suggestions("/c", "participant").map((hint) => hint.name)).toEqual(["cancel", "copy"]);
  expect(suggestions("/cancel 1", "host")).toEqual([]);
  expect(suggestions("hello", "host")).toEqual([]);
});

test("host-only commands are recognised with arguments", () => {
  expect(isHostOnly("/mode review")).toBe(true);
  expect(isHostOnly("/who")).toBe(false);
});

test("help lists only the commands the role can use", () => {
  expect(helpText("host")).toContain("/abort");
  expect(helpText("participant")).not.toContain("/abort");
});

test("plugin commands are suggested and their host-only flag is respected", () => {
  const plugins = pluginHints([{ name: "deploy", plugin: "ops", description: "ship it", usage: "/deploy", host_only: true }]);
  expect(suggestions("/dep", "host", plugins).map((hint) => hint.name)).toEqual(["deploy"]);
  expect(suggestions("/dep", "participant", plugins)).toEqual([]);
  expect(isHostOnly("/deploy prod", plugins)).toBe(true);
});
