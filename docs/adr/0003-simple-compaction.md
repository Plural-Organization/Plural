# ADR 0003: simple, host-side context compaction

Status: accepted

## Context

The agent loop keeps the whole conversation in memory and resends it on every model call. Long sessions
exceed the context window and make each turn expensive. ADR 0002 made the history append-only because
rewriting it breaks prompt caching and invalidates Anthropic thinking signatures (a thinking block is
valid only while the system prompt, the tools and every earlier message are unchanged).

Providers differ: Anthropic offers server-side compaction in beta, OpenAI-compatible servers (Ollama,
Groq, OpenRouter) offer nothing. Plural must behave the same on all of them.

## Decision

Compaction is performed by the loop, with the session's own provider, in the "simple" shape:

- The whole conversation is replaced by a single summary message. No earlier turn and no earlier
  thinking block is replayed. Keeping a verbatim tail is rejected: the retained turns carry thinking
  blocks bound to the old prefix and would be refused by Anthropic's history check.
- The run's current prompt is re-attached verbatim after the summary, so the model knows what to do next.
- The summary is requested with the same system prompt and tool list as normal calls (so the request can
  reuse the cached prefix) plus a final instruction that forbids tool calls. A summary that contains
  tool calls or no text is treated as a failed compaction.
- Triggers: proactively before a model call when the previous response reported a prompt of at least
  `PLURAL_COMPACT_AT` (default 0.75) of `PLURAL_CONTEXT_WINDOW`; reactively once when the provider
  reports a context overflow; on demand through `/compact`, which applies before the next prompt.
- Compaction happens only between tool rounds, never while an assistant turn waits for its tool results.
- The summary is a durable event (`context.compacted`) and `SessionState.summary` keeps the latest one.
  After a host restart the loop is seeded with that summary instead of starting empty.
- The summary is presented to the model as untrusted text produced from untrusted inputs. Provenance
  rules are unchanged: a run is as trusted as the prompts merged into it.

## Consequences

- One scheme for every provider; no dependence on a beta API.
- The prompt cache restarts at every compaction, and detail not captured by the summary is lost. The
  summarisation prompt asks explicitly for constraints, decisions, open work and exact identifiers.
- Only the latest summary survives a restart; turns after the last compaction are not restored. Persisting
  the full conversation is a separate piece of work.
- Local servers truncate silently when `num_ctx` is smaller than the real prompt (Ollama defaults to 4096).
  `PLURAL_CONTEXT_WINDOW` must match the server's actual window, otherwise compaction triggers too late.
- Server-side compaction can be adopted later behind the same loop interface where a provider supports it.
