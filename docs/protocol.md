# Protocol v1

JSON over WebSocket. Every frame is an `Envelope` (`src/plural/protocol/envelope.py`):
`v, id, kind (cmd|evt|ack), type, room, ts, actor, seq, to, token, re, ok, error, payload`.

- Commands: `src/plural/protocol/commands.py` (discriminated by `type`).
- Events: `src/plural/protocol/events.py`; durable events carry `seq`, transient ones do not.
- Unknown fields are ignored, unknown `type` is rejected with `invalid`.
- JSON Schema for clients: `uv run python scripts/gen_schema.py` → `web/src/protocol/schema.json`.

Relay framing (`src/plural/protocol/relay.py`): host opens `/host/{room}` with `relay.open` (public key + signature over room id); guests connect to `/{room}`; relay wraps guest frames into `relay.frame{conn,data}` and reports `relay.closed`.

Policy: `policy.add` / `policy.remove` (host only) append `policy.rule_added` / `policy.rule_removed` events; the live session rules are `SessionState.policy`, the built-in rules arrive in `session.welcome.base_policy`. `Always` and `Block` approval decisions are recorded as rules by the host.
