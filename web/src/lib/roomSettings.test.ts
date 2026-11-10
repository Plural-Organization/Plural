import { describe, expect, test } from "vitest";
import { ADMISSION, BRIEFINGS, PERMISSIONS, PROMPTS, saysOf } from "./roomSettings";

describe("room settings", () => {
  test("every option the host can pick says what it does", () => {
    for (const options of [PROMPTS, PERMISSIONS, ADMISSION, BRIEFINGS]) {
      expect(new Set(options.map((option) => option.id)).size).toBe(options.length);
      for (const option of options) {
        expect(option.label).not.toBe("");
        expect(option.says.endsWith(".")).toBe(true);
      }
    }
  });
  test("they cover every value the protocol accepts", () => {
    expect(PROMPTS.map((o) => o.id).sort()).toEqual(["open", "review"]);
    expect(PERMISSIONS.map((o) => o.id).sort()).toEqual(["accept_edits", "auto", "default", "plan"]);
    expect(ADMISSION.map((o) => o.id).sort()).toEqual(["approve", "open"]);
    expect(BRIEFINGS.map((o) => o.id).sort()).toEqual(["ask", "off", "team"]);
  });
  test("the line under a choice follows the current one", () => {
    expect(saysOf(PERMISSIONS, "plan")).toContain("only reads");
    expect(saysOf(PROMPTS, "review")).toContain("approve");
  });
});
