# Configuration

Every host setting can be passed as an environment variable with the `PLURAL_` prefix. The model and the API key are normally set from the settings screen of the client (`F2`): the choice is kept in `tui.json` and the key in `credentials.json`, readable only by you, both in the data directory. Claude OAuth tokens are kept separately in `anthropic-oauth.json` with owner-only permissions. Environment variables still work and are used when nothing is chosen there.

## Settings

| Variable | Default | Description |
|---|---|---|
| `PLURAL_PROVIDER` | by key | `fake`, `anthropic`, `anthropic_oauth`, `claude_code` or `openai`. When unset it follows `ANTHROPIC_API_KEY`, then `OPENAI_API_KEY` or `PLURAL_BASE_URL` with `PLURAL_MODEL`, and falls back to the demo agent |
| `PLURAL_MODEL` | `claude-opus-5-5` for Anthropic API keys; `claude-haiku-4-5` for Claude OAuth; `claude-sonnet-5-5` for Claude Code | Model id, required for `openai` |
| `PLURAL_API_KEY` | `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | Provider API key |
| `PLURAL_BASE_URL` | provider default | Custom endpoint, for example a local server |
| `PLURAL_EFFORT` | provider default | `low`, `medium`, `high`, `xhigh` or `max` |
| `PLURAL_MAX_OUTPUT_TOKENS` | provider default | Output token cap per model response |
| `PLURAL_PROMPT_MODE` | `open` | `open` or `review`. A resumed room keeps its last mode when unset |
| `PLURAL_WORKSPACE` | current directory | Directory the agent works in |
| `PLURAL_DATA_DIR` | `~/.plural` | Event logs, host key, attachments, client preferences |
| `PLURAL_BIND_HOST` | `127.0.0.1` | Bind address for direct mode |
| `PLURAL_PORT` | `7777` | Port for direct mode |
| `PLURAL_RELAY_URL` | none | Relay URL |
| `PLURAL_PUBLIC_URL` | none | Public URL used in invite links |
| `PLURAL_ADMISSION` | `approve` | `approve`: the host lets in everyone who uses the room link; `open`: anyone with it goes in at once |
| `PLURAL_JOIN_TIMEOUT_S` | `120` | Seconds before an unanswered request to join lapses |
| `PLURAL_MAX_PENDING_JOINS` | `5` | People who may wait to be let in at once |
| `PLURAL_MAX_PARTICIPANTS` | `20` | People in the room at once |
| `PLURAL_FIRST_TOKEN_TIMEOUT_S` | `120` | Seconds to wait for the model's first output before the run fails |
| `PLURAL_IDLE_TIMEOUT_S` | `60` | Seconds of silence mid-response before the run fails |
| `PLURAL_CONTEXT_WINDOW` | `128000` | Model context size in tokens. Set it to the real window for local models |
| `PLURAL_COMPACT_AT` | `0.75` | Fraction of the window at which the conversation is summarized |
| `PLURAL_FAST_MODEL` | picked from your credentials | The cheaper model for work that does not need the main one, today the conversation summary. By default `claude-haiku-5-5` with Anthropic (API key or OAuth), `gpt-5-mini` with OpenAI, `gemini-2.5-flash` with Gemini, and with Claude Code or Codex whichever of `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` is set. None when the main model is already a small one or nothing cheaper is reachable; then the main model does it. A summary the fast model fails at is retried on the main one |
| `PLURAL_FAST_PROVIDER` | the main provider | Provider for `PLURAL_FAST_MODEL`, for example `openai` to run it on `OPENAI_API_KEY` while the main model is Claude. It shares `PLURAL_BASE_URL` with the main model |
| `PLURAL_APPROVAL_TIMEOUT_S` | `120` | Seconds before an approval expires |
| `PLURAL_REJECTION_LIMIT` | `2` | Rejections of one kind of action per run before the agent stops asking the host |
| `PLURAL_GUEST_RUN_TOKENS` | none | Token budget for a run that includes a guest's prompt. Input, cache writes and output count; cache reads do not. The run ends after the turn that reaches it |
| `PLURAL_TOKEN_TTL_S` | `86400` | Capability token lifetime, at most 24 hours |
| `PLURAL_INVITE_TTL_S` | `3600` | Invite link lifetime |
| `PLURAL_MAX_IMAGE_BYTES` | `2500000` | Largest image a participant may attach, at most `2900000` so it fits a 4 MB message. The terminal client scales pasted images to 1568 px first. Claude Code, Codex CLI and models without vision do not see images |
| `PLURAL_TYPING_TTL_S` | `6` | Seconds after which a typing indicator lapses without a refresh |
| `PLURAL_WEB_SEARCH` | `true` | Give the agent `web_search`: Pydantic AI's `WebSearchTool`, run by the session provider's own search engine. Works with an Anthropic or OpenAI API key and with Claude OAuth; there is no search with Claude Code, Codex CLI or a custom `PLURAL_BASE_URL`. Each search waits for approval like other tools |
| `PLURAL_WEB_SEARCH_MODEL` | session model | Model that runs the search, written as `provider:model` like Pydantic AI, for example `anthropic:claude-haiku-4-5` to search cheaply. It applies only while the session uses that provider (`anthropic` covers Claude OAuth too) |
| `PLURAL_WEB_SEARCH_CONTEXT_SIZE` | `medium` | `low`, `medium` or `high`: how much page text the search reads (OpenAI) |
| `PLURAL_WEB_SEARCH_MAX_USES` | `5` | Searches per `web_search` call (Anthropic) |
| `PLURAL_WEB_SEARCH_ALLOWED_DOMAINS` / `PLURAL_WEB_SEARCH_BLOCKED_DOMAINS` | none | JSON lists such as `["docs.python.org"]`; only one of the two at a time on Anthropic |
| `PLURAL_WEB_SEARCH_CITY` / `_REGION` / `_COUNTRY` / `_TIMEZONE` | none | Location the results are localized for, for example `Almaty`, `KZ`, `Asia/Almaty` |
| `PLURAL_BROWSER` | `launch` | The browser the agent drives through Playwright MCP. `launch` opens a Chrome window of its own on first use; its profile lives in `~/.plural/browser`, so a login there is kept. A CDP endpoint attaches instead: `chrome` is the host's running Chrome once remote debugging is on in `chrome://inspect`. `off` turns the browser off |

## Models

Two adapters cover most models. `anthropic` uses the official Anthropic SDK. `openai` speaks the OpenAI Chat Completions format, which also covers OpenRouter, Groq, Gemini, DeepSeek and local servers such as Ollama.

For Claude OAuth, open `F2` → Model → Claude OAuth → Sign in with Claude. The authorization page opens in your browser and its URL is copied to the clipboard. Paste the code it shows into Plural, then choose *Save and use*. The host refreshes the token automatically. `PLURAL_PROVIDER=anthropic_oauth` also selects a previously saved login for a standalone host. Signing out in the Model tab removes Plural's saved OAuth credentials.

For a direct Claude Code session, install the official `claude` CLI, run `claude auth login`, then select `F2` → Model → Claude Code. Plural invokes `claude -p` with the selected model. Claude Code's own tools are disabled so tool requests still run through Plural's host approval flow. This provider uses Claude Code's sign-in, not Plural's OAuth token. `PLURAL_PROVIDER=claude_code` also selects it for a standalone host.

Claude OAuth defaults to Haiku 4.5 because an OAuth account can receive an opaque `429` for other models even when the token works. The Model row lists current Claude model IDs; use `← →` to choose one or `e` to enter another ID. The list is a catalog, not proof of access: use *Test connection* before *Save and use*. The choice for each provider is remembered in `tui.json`. This access behavior is controlled by Anthropic. The same models are available through an Anthropic API key when your API account has access. A generic OAuth `429` without `retry-after` is reported as a possible model-access restriction; usage-credit limits can also cause a `429`.

```bash
ANTHROPIC_API_KEY=sk-ant-… plural

PLURAL_PROVIDER=claude_code PLURAL_MODEL=claude-sonnet-5-5 plural

PLURAL_PROVIDER=openai PLURAL_MODEL=gpt-5 OPENAI_API_KEY=sk-… plural

PLURAL_MODEL=qwen3:4b PLURAL_BASE_URL=http://127.0.0.1:11434/v1 PLURAL_CONTEXT_WINDOW=4096 plural
```

Without any of these the host runs a scripted demo agent: any text lists the workspace, and `$ cmd` asks to run `cmd` through `bash`.

> [!NOTE]
> Local servers truncate silently when a prompt is longer than their window, and Ollama defaults to 4096 tokens. Start the server with a larger window (`OLLAMA_CONTEXT_LENGTH`) and set `PLURAL_CONTEXT_WINDOW` to the same value so compaction starts in time.

> [!IMPORTANT]
> Plural's Claude OAuth mode stores its own login and does not read credentials stored by Claude Code or pi. The separate Claude Code mode launches the installed CLI, which uses its own login. [Anthropic says](https://support.claude.com/en/articles/13189465-log-in-to-your-claude-account) third-party OAuth usage may draw from paid usage credits rather than subscription limits and may be restricted. Plural does not identify its own requests as Claude Code or promise subscription billing.

## Relay

A relay lets people connect over the internet without opening a port on the host. It only routes frames: it never decides permissions and never stores content.

```bash
plural-host relay --bind 0.0.0.0 --port 8787
plural --relay wss://relay.example.com
```

The relay takes its port from `PORT` and its address from `PLURAL_RELAY_BIND` when no option is given. In the client, `F2` → Session → *Over the internet* saves the relay address, see [sharing a session](self-hosting.md).

Running the relay and a host on Railway, Render, any VM or your own machine is described in [running on a server](self-hosting.md).
