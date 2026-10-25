# 0002. Own agent loop, providers on official SDKs

## Context
The `PolicyGate` must sit inside the agent loop, and the event log is the only source of truth. Agent frameworks such as LangGraph or PydanticAI agents bring their own loop, state and interrupt model, which would duplicate approvals and history. We still need many models without writing one adapter per vendor.

## Decision
- `AgentLoop` stays ours. Providers implement only the `LLMProvider.stream()` port and emit normalized events.
- Two adapters on official SDKs: `anthropic` (`anthropic` package, Messages API) and `openai` (`openai` package, Chat Completions). The second covers every OpenAI-compatible server through `PLURAL_BASE_URL`.
- Vendor SDKs are imported only under `plural.agent.providers`; an import-linter contract enforces it.
- History is append-only. Provider-specific blocks (Anthropic thinking signatures, fallback blocks) travel back unchanged as `NativeContent`, tagged with the provider that produced them.
- Calls cut off by `max_tokens` or a refusal are answered with an error result and never executed.
- Keys come only from `PLURAL_API_KEY` or the vendor's `*_API_KEY` variable and are always passed explicitly, so SDKs never fall back to stored logins.
- LangGraph stays a fallback behind an `AgentEngine` port if our loop does not hold up.

## Consequences
Two new runtime dependencies with permissive licenses. Adapters are small and tested against recorded streams with a mock transport. Prompt caching works because the system prompt, tool list and history prefix stay byte-stable.
