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
