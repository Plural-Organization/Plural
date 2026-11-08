# Development

The host is Python 3.12+ managed with [uv](https://docs.astral.sh/uv/). The client is TypeScript on Node 22+ and Bun, in npm workspaces.

## Set up

```bash
uv sync
npm install
```

## Check everything

The same checks CI runs:

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run lint-imports
uv run python scripts/gen_schema.py --check && uv run python scripts/gen_fixtures.py --check
uv run python scripts/gen_team_vectors.py --check
uv run pytest

npm run typecheck --workspace client && npm test --workspace client
npm run typecheck --workspace tui && npm test --workspace tui
npm run typecheck --workspace web && npm test --workspace web && npm run build --workspace web
```

## Run from source

```bash
export PLURAL_HOST_CMD="uv run plural-host"
npm run dev --workspace tui -- --workspace ~/some-project
```

`npm run demo --workspace tui` shows a busy session without a host, which is handy when working on the interface. `npm run build --workspace tui` compiles the client into `dist-bin/plural`.

`npm run dev --workspace web` serves the browser client on http://localhost:5173. Join it with the invite or the host link of a running host. `npm run build --workspace web` writes a static site to `web/dist`.

## What a session cost

The host started by the terminal client logs JSON lines to `~/.plural/logs/host.log`, each with the `room`, and with the `run_id` while a run is going. Three kinds of line say where tokens and time went:

- `llm.call`: one per model call, with its `purpose` (`turn`, `compact`, `briefing`, `ask`), the tokens billed (`input`, `cache_read`, `cache_write`, `output`), `hit`, the share of the prompt read from the provider's cache, and `first_ms` and `total_ms`. A sub-agent's lines also carry `agent` and `agent_model`.
- `tool.call`: the tool, whether it was allowed, how long the approval (`wait_ms`) and the call (`run_ms`) took, the size of its result and whether it was truncated.
- `context.compacted`: why the conversation was summarized, and its size before and after.

```bash
jq -c 'select(.event == "llm.call") | {purpose, input, cache_read, cache_write, hit}' ~/.plural/logs/host.log
```

A `hit` that stays low after the first turn means something changes the start of each request. With `PLURAL_DUMP_REQUESTS=1` every request is saved, and `scripts/prefix_diff.py` names where each one stops repeating the one before it:

```bash
uv run python scripts/prefix_diff.py ~/.plural/logs/requests/<room>
```

## Layout

```text
src/plural/
├── protocol/   wire models, envelope, codec          (pure)
├── core/       state reducer, roles, policy engine   (pure)
├── security/   tokens, host keys, redaction
├── agent/      loop, tools, sandbox, providers
│   ├── prompts/    the agent's prompts as Markdown, their parts in XML tags
│   ├── builtin_agents/, builtin_skills/   explore and plural-plugins, in the user format
│   ├── providers/  api/anthropic, api/openai_compat, cli/: each adapter with its presets.py
│   └── tools/  core/ declared on every request, extra/ loaded with tool_search
├── storage/    SQLite event store, migrations, export
├── host/       session actor, gateway, transports
├── relay/      relay router
├── client/     connection and projection, used by tests
└── cli/        plural-host entry point
client/         @plural/client, the TypeScript protocol client
tui/            the terminal client
web/            the browser client: screens, components, hooks and lib in web/src
```

Layers are enforced with `import-linter`: `core` and `protocol` do no I/O, `agent` knows nothing about transports or storage, `relay` knows nothing about sessions, policy or content.

## The protocol

The JSON schemas in `client/src/protocol/` and the TypeScript types are generated from the Python models:

```bash
uv run python scripts/gen_schema.py
npm run gen --workspace client
uv run python scripts/gen_fixtures.py
```

The fixtures are produced by the Python reducer and replayed by the TypeScript tests, so the two implementations cannot drift apart unnoticed. See [`protocol.md`](protocol.md).

The team signatures are checked the same way. `scripts/gen_team_vectors.py` writes `client/test/fixtures/team-vectors.json`: request and join messages, their ed25519 signatures from a fixed key, and the tunnel hosts, all made by the Python code. The Python, terminal and browser tests each reproduce those values exactly, so a change to what is signed fails all three until it is made in all three.

## Provider catalog

The providers the settings screen offers (NVIDIA, Groq, DeepSeek, Ollama and the rest) are defined once, in
`presets.py` next to the adapter that serves them (`providers/api/openai_compat/presets.py` holds NVIDIA,
Groq, DeepSeek and the other OpenAI-compatible ones), and `providers/catalog.py` puts them together. The host expands a preset into its adapter,
endpoint and default model. The terminal client keeps no copy: it asks the host it started for the
catalog over the control channel (`{"type": "catalog"}`) before it restores the saved model choice.

## Releasing

A tag `vX.Y.Z` that matches `__version__` and the version of the client builds the Python package and the binaries for macOS and Linux, and publishes them after the maintainer approves the `pypi` environment.

Design decisions are recorded in [`adr/`](adr/).
