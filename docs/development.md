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

## Layout

```text
src/plural/
├── protocol/   wire models, envelope, codec          (pure)
├── core/       state reducer, roles, policy engine   (pure)
├── security/   tokens, host keys, redaction
├── agent/      loop, tools, sandbox, providers
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

## Provider catalog

The providers the settings screen offers (NVIDIA, Groq, DeepSeek, Ollama and the rest) are defined once, in
`presets.py` next to the adapter that serves them (`providers/api/openai_compat/presets.py` holds NVIDIA,
Groq, DeepSeek and the other OpenAI-compatible ones), and `providers/catalog.py` puts them together. The host expands a preset into its adapter,
endpoint and default model. The terminal client keeps no copy: it asks the host it started for the
catalog over the control channel (`{"type": "catalog"}`) before it restores the saved model choice.

## Releasing

A tag `vX.Y.Z` that matches `__version__` and the version of the client builds the Python package and the binaries for macOS and Linux, and publishes them after the maintainer approves the `pypi` environment.

Design decisions are recorded in [`adr/`](adr/).
