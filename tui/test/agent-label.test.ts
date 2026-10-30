import { expect, test } from "bun:test";
import { briefAgent } from "../src/lib/agent";

test("a Claude model is cut down to its family and version", () => {
  expect(briefAgent("anthropic · claude-opus-5-5")).toBe("anthropic · opus 5.5");
  expect(briefAgent("Claude Code · claude-sonnet-5-5")).toBe("Claude Code · sonnet 5.5");
  expect(briefAgent("Claude OAuth · claude-haiku-4-5")).toBe("Claude OAuth · haiku 4.5");
  expect(briefAgent("anthropic · claude-sonnet-4-5-20250929")).toBe("anthropic · sonnet 4.5");
});

test("other labels are left alone", () => {
  expect(briefAgent("Codex CLI · gpt-6.1-sol")).toBe("Codex CLI · gpt-6.1-sol");
  expect(briefAgent("openai · gpt-5 · local")).toBe("openai · gpt-5 · local");
  expect(briefAgent("demo agent (scripted)")).toBe("demo agent (scripted)");
});
