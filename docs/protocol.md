# Protocol v1

JSON over WebSocket. Every frame is an `Envelope` (`src/plural/protocol/envelope.py`):
`v, id, kind (cmd|evt|ack), type, room, ts, actor, seq, to, token, re, ok, error, payload`.

- Commands: `src/plural/protocol/commands.py` (discriminated by `type`).
- Events: `src/plural/protocol/events.py`; durable events carry `seq`, transient ones do not.
- Unknown fields are ignored, unknown `type` is rejected with `invalid`.
- JSON Schema for clients: `uv run python scripts/gen_schema.py` → `web/src/protocol/schema.json`.

Relay framing (`src/plural/protocol/relay.py`): host opens `/host/{room}` with `relay.open` (public key + signature over room id); guests connect to `/{room}`; relay wraps guest frames into `relay.frame{conn,data}` and reports `relay.closed`.

Prompt mode: `session.set_prompt_mode` (host only) appends `session.prompt_mode_changed`; `SessionState.prompt_mode` is `open` (participant prompts go straight to the agent) or `review` (they become proposals). See ADR 0004.

Permission mode: `session.set_permission_mode` (host only) appends `session.permission_mode_changed`; `SessionState.permission_mode` is `default` (edits and commands ask), `accept_edits` (writes are allowed), `plan` (writes and commands that are not allowed by a rule are denied, and each prompt carries a plan-mode note to the agent) or `auto` (writes and commands are allowed). Deny rules and the guest-turn taint apply in every mode. The host resets it to `default` on start.

Context: `SessionState.context` holds the agent's context fill (`tokens`, `window`, `compact_at`) and follows `context.usage`, which the host appends after every model response, after a compaction and when the model changes. `context.compact` (host only) starts a compaction at once when the agent is idle, as a run with an empty `prompt_id`; during a run it is deferred to the next step. A transient `context.compacting` (`run_id`, `tokens_before`) marks the start of every compaction, automatic or requested, and `context.compacted` its end.

MCP: `SessionState.mcp` lists the host's MCP servers (`name`, `transport` of `stdio` or `http`, `scope`, `status` of `connecting`, `ready`, `failed` or `off`, `tools`, `error`) and follows `mcp.changed`. The host-only commands `mcp.add` (`name`, a `command` with `args` or a `url`, `scope`), `mcp.toggle` (`name`, `enabled`), `mcp.restart`, `mcp.remove` and `mcp.import` change them; connecting happens in the background and shows up as later `mcp.changed` events. Server environment and headers never appear in events. MCP tools reach the agent as `mcp__<server>__<tool>` with risk `exec` and subject `<server>/<tool>`.

Skills: `SessionState.skills` lists the installed skills (`name`, `description`, `scope` of `project` or `global`) and changes with `skills.changed`, which also names what was `added` and `removed`. `skills.search` (participants and the host) answers the sender alone with a transient `skills.found` holding `hits` of `package` (`owner/repo@skill`), `name` and `installs` from skills.sh. `skills.install` (host only, `scope` defaults to `project`) downloads the skill from GitHub in the background; a failure comes back to the sender as an `error` event. `skills.remove` (host only) deletes a skill from a folder Plural installs into.

Agent: `SessionState.agent` names the agent that answers (for example `anthropic · claude-opus-5-5`) and follows the durable `agent.changed` event. It changes only while no run is active.

Host control channel (not part of the wire protocol): a client that started its own host with `plural-host host --json` keeps the host's stdin open and writes one JSON object per line, `{"id", "type": "configure" | "test", "config": {"provider", "model", "base_url", "api_key", "context_window"}}`. The host answers on stdout with `{"type": "result", "id", "ok", ...}`: `configure` swaps the provider and returns the new `agent` label, `test` makes a short real request and returns `message` or `error`. Closing stdin stops the host. API keys travel only through this local pipe, never in protocol frames, argv or the log, and a key received here is added to the redactor at once. For `anthropic_oauth`, the host reads its own `anthropic-oauth.json` file; OAuth tokens do not enter control frames.

Live output: while `bash` runs, the host broadcasts the transient `tool.output` with whole lines (batched at most every 100 ms, at most 64 KB per call) after redaction; `tool.ended` still carries the complete output. Clients show the tail and must not rely on receiving every chunk.

Queue: a prompt accepted while a run is active is appended to `SessionState.queue` (`prompt.accepted` with an active run) and leaves it with `prompt.dequeued` and a reason: `delivered` when the agent takes it, `cancelled` when the author or the host removes it with `queue.cancel`, `dropped` when the run is aborted or the host restarts.

Presence: `presence.typing` (host and participants) announces that the sender is composing a prompt. The host broadcasts the transient `participant.typing`, never stores it, repeats nothing while the state is unchanged, ends it when the prompt is accepted, the sender leaves or six seconds pass without a refresh, and lists who is typing in `session.snapshot.typing`.

Policy: `policy.add` / `policy.remove` (host only) append `policy.rule_added` / `policy.rule_removed` events; the live session rules are `SessionState.policy`, the built-in rules arrive in `session.welcome.base_policy`. `Always` and `Block` approval decisions are recorded as rules by the host.
