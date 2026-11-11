# ADR 0015: the agent is set up on the computer, and every client asks it

Status: proposed.

## Context

The terminal client lets a person choose the agent a room runs: Claude Code, Codex, a model on their
own machine, or any provider with an API key. The web client cannot, and starting a room from the
web (ADR 0014) needs it to. The choice has to reach the same host the terminal client configures.

Today the terminal client owns more than the screen. In TypeScript it keeps the chosen provider and
model (`tui.json`), the API keys (`credentials.json`, mode 0600), the Claude OAuth exchange, and the
logic that decides what a provider still needs (`setup.ts`, `agent.ts`, `settingsModel.ts`). The host
only receives a finished `configure` request and owns the catalog of providers. A second client that
copies this logic would drift from the first.

## Decision

The state and the rules move to one layer on the computer, `plural.agent_setup` (Python, next to the
host and the daemon). The terminal client and the web client are clients of it.

- **What it owns.** The saved choice per provider (provider, model, endpoint, context window, fast
  model), the API keys, whether each provider is ready, whether a Claude Code or Codex sign-in exists,
  the models a local server offers, and a connection test. It reuses the host's catalog
  (`PRESETS`), `extras`, `tools` and `control.probe`; none of that is copied.
- **Files stay as they are.** `credentials.json` (`{"keys": {preset: key}}`, 0600) and the `agent` and
  `agentChoices` fields of `tui.json` keep their format, so a key a person already saved is found.
  Writes are atomic and keep every field the layer does not own.
- **Readiness** is one answer per provider: `ready`, `needs_key`, `needs_install` (a CLI),
  `needs_sdk` (an optional Python extra), `needs_sign_in`. Each carries the command that fixes it.
  Claude Code and Codex are asked for their own status (`claude auth status`, `codex login status`):
  the CLI keeps its sign-in and Plural never reads, copies or stores its token.
- **Local models** are found by probing fixed loopback addresses (Ollama `127.0.0.1:11434`, LM Studio
  `127.0.0.1:1234`) and listing the models they report. The layer probes no address a client names.
- **Secrets only go in.** No call returns a key or token. A client learns that a key is set and, for
  a long key, its last four characters. Keys never appear in logs or errors.
- **Surfaces.** `plural agent` is the command line over the layer (`list`, `status`, `key`, `use`,
  `test`). The daemon exposes the same operations over its loopback API with the checks of ADR 0014
  (a later change). The web client draws its screen from the catalog and keeps no provider list.
- **Claude OAuth with the public client id stays in the terminal client.** A Claude subscription is
  used through Claude Code. The web client does not run its own OAuth exchange.

## Consequences

- One place decides what a provider needs, so the terminal and the web client cannot disagree.
- A key typed into a web page reaches the daemon over loopback only, is written to a 0600 file and is
  never read back. A script injected into the web page could still capture what the person types, so
  the web client also offers `plural agent key`, which takes the key on the computer.
- The terminal client keeps its own copy of this logic until a later change moves it onto the layer.
  Until then both write the same files, so a choice made in either shows in the other after a restart.
- The web client can configure only the computer its daemon runs on.

## Plan

| slice | what |
|---|---|
| 1 | this ADR; `plural.agent_setup` and `plural agent`, with tests |
| 2 | daemon: `/v1/agent/*` (catalog, status, key, install, test, use) and the agent of a room |
| 3 | web client: provider picker and agent settings (HeroUI), in Start a room and Room settings |
| 4 | terminal client moves onto the layer and drops its copy |

## The daemon's agent API

All of it sits behind the three checks of ADR 0014 (host, origin, ticket); the preflight now also
allows `PUT`.

| call | what |
|---|---|
| `GET /v1/agent` | the catalog: every provider with what it needs, key facts, the saved choice, the local servers found |
| `PUT /v1/agent` `{agent}` | make a complete choice this computer's agent |
| `PUT /v1/agent/key` `{preset, key}` · `DELETE /v1/agent/key/{preset}` | save or forget a key. Nothing returns it |
| `POST /v1/agent/test` `{choice, key?}` | one short request to the provider |
| `POST /v1/agent/install` `{tool}` or `{extra}` | install a CLI or an SDK, from the same fixed lists as the host |
| `POST /v1/agent/sign-in` `{tool}` | open a terminal window that runs `claude auth login` or `codex login` |
| `POST /v1/rooms` `{folder, title?, agent?, relay?}` | the room runs `agent`, or this computer's agent when it is left out. `relay` names the relay (empty: the Plural relay) and becomes this computer's relay; left out, the saved one is used |
| `GET /v1/settings` | the relay this computer's rooms go through, as the terminal client saved it |
| `PUT /v1/rooms/{room}/agent` `{agent}` | switch a running room's agent, the conversation is kept |

A page names a provider and a model; the daemon adds the key it holds and sends the host a
`configure` request on its control channel (stdin), the same request the terminal client sends. A
host that refuses the agent is stopped and the room is not listed, so a room never runs an agent
the person did not choose. The command a sign-in opens is picked by the daemon from a list of two;
no text from the page reaches a shell.
