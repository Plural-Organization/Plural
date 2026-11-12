import { describe, expect, test } from "vitest";
import { DAEMON_PORT, daemonPrompt, manualSteps } from "./agentPrompt";

describe("daemonPrompt", () => {
  test("lists install, sign in and the daemon in that order", () => {
    const prompt = daemonPrompt();
    const order = ["install.sh", "plural login", "nohup plural daemon", `127.0.0.1:${DAEMON_PORT}/v1/status`].map((part) => prompt.indexOf(part));
    expect(order.every((at) => at >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
  });
  test("tells the agent not to ask, and names what only the person can do", () => {
    const prompt = daemonPrompt();
    expect(prompt).toContain("without asking me questions");
    expect(prompt).toContain("needs me");
    expect(prompt).toContain("do not use sudo");
    expect(prompt).toContain("PLURAL_OK");
  });
  test("does not carry a link code, so it can be shown before anyone is linked", () => {
    expect(daemonPrompt()).not.toMatch(/--code/);
  });
});

describe("manualSteps", () => {
  test("is the three commands, one each", () => {
    expect(manualSteps().map((step) => step.command)).toEqual([expect.stringContaining("install.sh"), "plural login", "plural daemon"]);
  });
});
