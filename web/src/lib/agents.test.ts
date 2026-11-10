import { expect, test } from "vitest";
import { agentMark } from "./agents";

test("a host's agent label names its maker", () => {
  expect(agentMark("Claude Code · claude-sonnet-5-5")?.name).toBe("Claude");
  expect(agentMark("Codex CLI · gpt-6.1-sol")?.name).toBe("OpenAI");
  expect(agentMark("openai · qwen3:4b · local")?.name).toBe("OpenAI");
  expect(agentMark("ollama · qwen3:4b")?.name).toBe("Ollama");
  expect(agentMark("OpenRouter · anthropic/claude-opus-5-5")?.name).toBe("OpenRouter");
  expect(agentMark("Gemini CLI · gemini-3-pro")?.name).toBe("Gemini");
  expect(agentMark("DeepSeek · deepseek-chat")).toBeNull();
  expect(agentMark("demo agent (scripted)")).toBeNull();
  expect(agentMark(null)).toBeNull();
});
