import claude from "../assets/providers/claude.svg";
import gemini from "../assets/providers/gemini.svg";
import ollama from "../assets/providers/ollama.svg";
import openai from "../assets/providers/openai.svg";
import openrouter from "../assets/providers/openrouter.svg";

export interface AgentMark {
  name: string;
  icon: string;
  // The maker's own colour; marks drawn in black and white take the text colour.
  color: string;
}

const MARKS: [RegExp, AgentMark][] = [
  [/openrouter/i, { name: "OpenRouter", icon: openrouter, color: "#8b8ef7" }],
  [/claude|anthropic|opus|sonnet|haiku/i, { name: "Claude", icon: claude, color: "#d97757" }],
  [/codex|openai|gpt|\bo\d\b/i, { name: "OpenAI", icon: openai, color: "currentColor" }],
  [/gemini|google/i, { name: "Gemini", icon: gemini, color: "#5b8def" }],
  [/ollama|\blocal\b/i, { name: "Ollama", icon: ollama, color: "currentColor" }],
];

// Which agent a host's label ("Claude Code · claude-sonnet-5-5", "Codex CLI · gpt-6.1-sol") is, if it says.
export function agentMark(label: string | null | undefined): AgentMark | null {
  if (!label) return null;
  return MARKS.find(([pattern]) => pattern.test(label))?.[1] ?? null;
}
