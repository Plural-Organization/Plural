<div align="center">

# Plural

**Multiplayer sessions for one AI coding agent.**

One agent. One host. Everyone in the room.

[![Python](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with pyright](https://microsoft.github.io/pyright/img/pyright_badge.svg)](https://microsoft.github.io/pyright/)
[![Status](https://img.shields.io/badge/status-alpha-orange.svg)](#roadmap)

[Quick start](#quick-start) · [How it works](#how-it-works) · [Security](#security-model) · [Architecture](#architecture) · [Contributing](#contributing)

</div>

---

Plural turns a solo AI agent session into a shared one. The agent runs on the **host's machine** with the **host's API key**. Teammates join from a terminal or a browser, watch the run live, and propose prompts. The host stays in control: every proposal and every risky tool call goes through the host's approval.

```text
┌────────────┐        ┌──────────────┐        ┌─────────────┐
│  guest TUI │◀──ws──▶│              │◀──ws──▶│  host       │
├────────────┤        │  relay       │        │  ├ agent    │──▶ LLM API
│  guest web │◀──ws──▶│  (optional,  │        │  ├ policy   │
└────────────┘        │   dumb pipe) │        │  ├ tools    │──▶ workspace
                      └──────────────┘        │  └ event log│
                                              └─────────────┘
```

## Features

- **Shared live session.** Everyone sees the same transcript, tool calls and diffs as they stream.
- **Proposals, not prompts.** Guests suggest prompts. The host approves, edits or rejects them.
- **Host-only approvals.** Write and exec actions need host consent. Guest-originated turns are tainted and always ask. Rejected actions are not re-asked: after repeated rejections of the same kind the agent is told to ask the user instead, and "Block (session)" denies a whole command class.
- **Attribution.** Every turn records who wrote it and who approved it.
- **Policy engine.** Allow, ask and deny rules with last-match-wins. Base deny rules cannot be overridden.
- **Event-sourced.** An append-only SQLite log is the source of truth. Reconnect, replay and audit come for free.
- **Isolation.** Tools are confined to the workspace. Secret paths are denied and output is redacted.
- **Direct or relayed.** Connect over LAN directly, or through a relay that never sees permissions and never stores content.
- **Terminal and browser clients.** A Textual TUI, a plain line mode and a web client.
- **Bring your own key.** API keys only. Plural never touches subscription credentials.

## Requirements

- Python **3.12** or newer
- [uv](https://docs.astral.sh/uv/) 0.5+
- macOS or Linux (Windows through WSL)
- Node.js 22+ (web client only)

## Installation

Clone the repository, then from its root:

```sh
uv sync
```

As a global tool:

```sh
uv tool install .
```

Check your environment:

```sh
plural doctor
```

## Quick start

Start a session in your project:

```sh
uv run plural host --workspace .
```

The host prints a one-time invite link and opens the TUI. Send the link to a teammate:

```sh
uv run plural join "ws://127.0.0.1:7777/r_…?invite=…" --name alia
```

The default provider is `fake`, a scripted demo that needs no API key. Plain text lists the workspace. `$ cmd` asks to run `cmd` through `bash` and waits for host approval.

### Through a relay

```sh
uv run plural relay --bind 0.0.0.0 --port 8787
uv run plural host --relay wss://relay.example.com
```

A ready-made deployment with Caddy and TLS lives in [`deploy/`](deploy/).

## Usage

### Commands

| Command | Purpose |
|---|---|
| `plural host` | Start a host session, direct mode or `--relay URL` |
| `plural join <link>` | Join as a guest, `--plain` for a line-mode stream |
| `plural relay` | Run the relay router |
| `plural doctor` | Check the environment and workspace |
| `plural export <room>` | Dump a session's event log to JSONL |

Run `plural <command> --help` for all options.

### TUI keys

| Key | Action |
|---|---|
| `ctrl+r` | Review pending proposals and approvals |
| `ctrl+o` | Create an invite link |
| `ctrl+p` | View and edit session policy rules (host) |
| `esc` | Abort the current run |
| `ctrl+q` | Quit |

Prompt-line commands work in the TUI and in `plural join --plain`: `/abort`, `/policy` (list rules), `/policy allow|ask|deny <tool> <pattern>`, `/policy rm <rule id>`.

### Configuration

Every setting can be passed as an environment variable with the `PLURAL_` prefix.

| Variable | Default | Description |
|---|---|---|
| `PLURAL_PROVIDER` | `fake` | `fake`, `anthropic` or `openai` |
| `PLURAL_MODEL` | `claude-opus-5-5` for `anthropic` | Model id, required for `openai` |
| `PLURAL_API_KEY` | `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | Provider API key |
| `PLURAL_BASE_URL` | provider default | Custom endpoint, e.g. a local OpenAI-compatible server |
| `PLURAL_EFFORT` | provider default | `low`, `medium`, `high`, `xhigh` or `max` |
| `PLURAL_MAX_OUTPUT_TOKENS` | provider default | Output token cap per model response |
| `PLURAL_WORKSPACE` | current directory | Directory the agent works in |
| `PLURAL_DATA_DIR` | `~/.plural` | Event logs, host key, attachments |
| `PLURAL_BIND_HOST` | `127.0.0.1` | Bind address for direct mode |
| `PLURAL_PORT` | `7777` | Port for direct mode |
| `PLURAL_RELAY_URL` | none | Relay URL |
| `PLURAL_PUBLIC_URL` | none | Public URL used in invite links |
| `PLURAL_FIRST_TOKEN_TIMEOUT_S` | `120` | Seconds to wait for the model's first output before the run fails |
| `PLURAL_IDLE_TIMEOUT_S` | `60` | Seconds of silence mid-response before the run fails |
| `PLURAL_APPROVAL_TIMEOUT_S` | `120` | Seconds before an approval expires |
| `PLURAL_REJECTION_LIMIT` | `2` | Rejections of one kind of action per run before the agent stops asking the host |
| `PLURAL_TOKEN_TTL_S` | `86400` | Capability token lifetime, at most 24h |
| `PLURAL_INVITE_TTL_S` | `3600` | Invite link lifetime |

### Providers

Two adapters cover most models: `anthropic` uses the official Anthropic SDK, and `openai` speaks the OpenAI Chat Completions format, which also covers OpenRouter, Groq, Gemini, DeepSeek and local servers such as Ollama.

```sh
PLURAL_PROVIDER=anthropic ANTHROPIC_API_KEY=sk-ant-... plural host

PLURAL_PROVIDER=openai PLURAL_MODEL=gpt-5 OPENAI_API_KEY=sk-... plural host

PLURAL_PROVIDER=openai PLURAL_MODEL=qwen2.5-coder PLURAL_BASE_URL=http://localhost:11434/v1 plural host
```

> [!IMPORTANT]
> Plural uses API keys only. It never reads subscription logins or other credentials stored by vendor tools.

## How it works

1. The **host** starts a session. A `SessionActor` owns the room and processes every command in order: append to the log, reduce state, publish.
2. A **guest** joins with an invite and receives a signed Ed25519 capability token bound to the room and connection.
3. The guest **proposes** a prompt. The host approves it, and it enters the agent's queue attributed as `[alia, proposal approved by host]`.
4. The **agent loop** streams the model's reply. Each tool call is prepared, evaluated by the `PolicyGate`, and either runs, waits for the host, or is denied.
5. Every event goes to the **event log** first and is then fanned out to clients. A client that reconnects asks for events `since` its last `seq`.

## Security model

- The agent and the API key live only on the host. Guests never see the key.
- Permission decisions are made only by the host. The relay is a dumb pipe.
- No tool runs without passing the `PolicyGate`. There are no bypasses.
- Tools are confined to the workspace with `realpath` checks and a deny-list for secret files such as `.env`, keys and credentials.
- `bash` runs with a clean environment, in its own process group, with a timeout.
- Secrets are redacted before anything is written to the log or sent to clients.

See [`SECURITY.md`](SECURITY.md) to report a vulnerability and [`docs/threat-model.md`](docs/threat-model.md) for the full threat model.

## Architecture

Plural is a hexagonal, event-sourced Python app. Layers are enforced with `import-linter`.

```text
src/plural/
├── protocol/   wire models, envelope, codec          (pure)
├── core/       state reducer, roles, policy engine   (pure)
├── security/   tokens, host keys, redaction
├── agent/      harness: loop, tools, sandbox, providers
├── storage/    SQLite event store, migrations, export
├── host/       session actor, gateway, transports
├── relay/      dumb relay router
├── client/     connection, reconnect, projection
├── cli/        Typer entry point
└── tui/        Textual app
web/            browser client (Vite + React + TypeScript)
```

- `core` and `protocol` do no I/O.
- `agent` knows nothing about transports or storage.
- `relay` knows nothing about sessions, policy or content.
- `client` knows nothing about the host internals.

Design notes: [`docs/adr/`](docs/adr/) · Wire protocol: [`docs/protocol.md`](docs/protocol.md)

## Development

```sh
uv sync
uv run pytest
```

Full check, the same one CI runs:

```sh
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run lint-imports && uv run pytest
```

Regenerate the protocol JSON schema for the web client:

```sh
uv run python scripts/gen_schema.py
```

Web client:

```sh
cd web
npm ci
npm run dev
```

## Roadmap

- [x] Protocol, event log and session actor
- [x] Policy engine and host approvals
- [x] Workspace tools and local sandbox
- [x] Direct and relay transports
- [x] TUI and plain clients
- [x] Anthropic and OpenAI-compatible providers
- [ ] Web client
- [ ] Context compaction
- [ ] Container sandbox
- [ ] End-to-end and load tests

## Contributing

Contributions are welcome. Read [`CONTRIBUTING.md`](CONTRIBUTING.md) first. In short:

- Open an issue before large changes.
- Use [Conventional Commits](https://www.conventionalcommits.org/).
- New dependencies need discussion, and large ones need an ADR.
- Make sure the full check passes.

## Acknowledgements

Plural learns from [Pi](https://github.com/badlogic/pi-mono), [OpenCode](https://github.com/sst/opencode) and [Hermes](https://github.com/NousResearch/hermes-agent).

## License

Plural is licensed under the [Apache License 2.0](LICENSE).
