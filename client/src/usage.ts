import type { ContextPartKind, ContextView } from "./protocol";

interface PromptTokens {
  input_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
}

/** The share of the prompt the provider served from its cache, or null when nothing was sent. */
export function cacheHit(usage: PromptTokens): number | null {
  const prompt = usage.input_tokens + usage.cache_read_tokens + usage.cache_write_tokens;
  return prompt > 0 ? usage.cache_read_tokens / prompt : null;
}

/** How a cache hit reads in a summary line: "93% cached", or "" when there was no prompt. */
export function cacheHitLabel(usage: PromptTokens): string {
  const hit = cacheHit(usage);
  return hit === null ? "" : `${Math.round(hit * 100)}% cached`;
}

const PART_LABELS: Record<ContextPartKind, string> = {
  system: "system prompt",
  tool_rules: "tool rules",
  environment: "environment",
  project_notes: "AGENTS.md",
  skills: "skills",
  agents: "sub-agents",
  plugins: "plugins",
  tools: "tool definitions",
  messages: "messages",
  tool_results: "tool results",
  summary: "summary",
  notes: "notes",
};

export interface ContextLine {
  label: string;
  tokens: number;
  /** The part's share of the model's window. */
  share: number;
}

/** What the context is spent on, largest first. */
export function contextLines(context: ContextView): ContextLine[] {
  return [...context.parts]
    .sort((a, b) => b.tokens - a.tokens)
    .map((part) => ({
      label: part.kind === "tool_results" && part.name ? `${part.name} results` : PART_LABELS[part.kind],
      tokens: part.tokens,
      share: context.window > 0 ? part.tokens / context.window : 0,
    }));
}

/** The latest request was mostly sent at full price although the context is large. */
export function missedCache(context: ContextView): boolean {
  return context.hit !== null && context.hit < 0.5 && context.tokens > 10_000;
}
