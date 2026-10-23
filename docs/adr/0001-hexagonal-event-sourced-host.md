# 0001. Hexagonal host with an event log as source of truth

## Context
One agent, many clients (TUI, web, bot), untrusted relay, late joiners and reconnects.

## Decision
- Ports and adapters: `core` and `protocol` are pure; I/O lives in `storage`, `host/transport`, `agent/sandbox`.
- Append-only SQLite log with monotonic `seq`; every state is `reduce(state, event)`.
- One `SessionActor` per session processes its inbox sequentially: append → reduce → publish.
- Permissions are decided only on the host; tokens are Ed25519 capabilities signed by the host key.
- Approval timeouts are owned by the actor, so the log and the gate never disagree.

## Consequences
Deterministic ordering, free replay/audit, trivial late join. The actor is a throughput ceiling per session, which is fine for ≤ 10 participants.
