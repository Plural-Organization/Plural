# Configuration

Every host setting can be passed as an environment variable with the `PLURAL_` prefix. The model and the API key are normally set from the settings screen of the client (`F2`): the choice is kept in `tui.json` and the key in `credentials.json`, readable only by you, both in the data directory. Environment variables still work and are used when nothing is chosen there.

## Settings

| Variable | Default | Description |
|---|---|---|
| `PLURAL_PROVIDER` | by key | `fake`, `anthropic` or `openai`. When unset it follows `ANTHROPIC_API_KEY`, then `OPENAI_API_KEY` or `PLURAL_BASE_URL` with `PLURAL_MODEL`, and falls back to the demo agent |
| `PLURAL_MODEL` | `claude-opus-5-5` for `anthropic` | Model id, required for `openai` |
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
| `PLURAL_FIRST_TOKEN_TIMEOUT_S` | `120` | Seconds to wait for the model's first output before the run fails |
| `PLURAL_IDLE_TIMEOUT_S` | `60` | Seconds of silence mid-response before the run fails |
| `PLURAL_CONTEXT_WINDOW` | `128000` | Model context size in tokens. Set it to the real window for local models |
| `PLURAL_COMPACT_AT` | `0.75` | Fraction of the window at which the conversation is summarized |
| `PLURAL_APPROVAL_TIMEOUT_S` | `120` | Seconds before an approval expires |
| `PLURAL_REJECTION_LIMIT` | `2` | Rejections of one kind of action per run before the agent stops asking the host |
| `PLURAL_TOKEN_TTL_S` | `86400` | Capability token lifetime, at most 24 hours |
| `PLURAL_INVITE_TTL_S` | `3600` | Invite link lifetime |
| `PLURAL_TYPING_TTL_S` | `6` | Seconds after which a typing indicator lapses without a refresh |

## Models

Two adapters cover most models. `anthropic` uses the official Anthropic SDK. `openai` speaks the OpenAI Chat Completions format, which also covers OpenRouter, Groq, Gemini, DeepSeek and local servers such as Ollama.

```bash
ANTHROPIC_API_KEY=sk-ant-… plural

PLURAL_PROVIDER=openai PLURAL_MODEL=gpt-5 OPENAI_API_KEY=sk-… plural

PLURAL_MODEL=qwen3:4b PLURAL_BASE_URL=http://127.0.0.1:11434/v1 PLURAL_CONTEXT_WINDOW=4096 plural
```

Without any of these the host runs a scripted demo agent: any text lists the workspace, and `$ cmd` asks to run `cmd` through `bash`.

> [!NOTE]
> Local servers truncate silently when a prompt is longer than their window, and Ollama defaults to 4096 tokens. Start the server with a larger window (`OLLAMA_CONTEXT_LENGTH`) and set `PLURAL_CONTEXT_WINDOW` to the same value so compaction starts in time.

> [!IMPORTANT]
> Plural uses API keys only. It never reads subscription logins or other credentials stored by vendor tools.

## Relay

A relay lets people connect over the internet without opening a port on the host. It only routes frames: it never decides permissions and never stores content.

```bash
plural relay --bind 0.0.0.0 --port 8787
plural --relay wss://relay.example.com
```

A ready-made deployment with Caddy and TLS is in [`deploy/`](../deploy/).
