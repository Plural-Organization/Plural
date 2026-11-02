import { contextLines, missedCache, shortTokens, type ContextView } from "@plural/client";

/** The /context answer: what fills the agent's prompt, and how much of it the cache served. */
export function contextText(context: ContextView | null): string {
  if (context === null || context.parts.length === 0) {
    return "the agent has not been asked anything yet";
  }
  const percent = (share: number): string => `${share > 0 && share < 0.01 ? "<1" : Math.round(share * 100)}%`;
  const lines = contextLines(context).map((line) => `  ${line.label}  ${shortTokens(line.tokens)}  ${percent(line.share)}`);
  const total = `  total ${shortTokens(context.tokens)} of ${shortTokens(context.window)}, summarized at ${Math.round(context.compact_at * 100)}%`;
  const hit =
    context.hit === null
      ? []
      : [`  latest request ${Math.round(context.hit * 100)}% cached${missedCache(context) ? ", most of it sent at full price" : ""}`];
  return ["context", ...lines, total, ...hit].join("\n");
}
