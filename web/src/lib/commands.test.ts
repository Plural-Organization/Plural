import { expect, test } from "vitest";
import { helpText } from "./commands";

test("help lists only the commands the role can use", () => {
  expect(helpText("host")).toContain("/abort");
  expect(helpText("participant")).not.toContain("/abort");
});

test("help lists the browser's own commands and keys", () => {
  expect(helpText("participant")).toContain("/draw");
  expect(helpText("participant")).not.toContain("/quit");
  expect(helpText("host")).toContain("answer the approval card");
});
