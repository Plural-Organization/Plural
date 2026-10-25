# Threat model (draft)

| threat | mitigation in code |
|---|---|
| guest runs commands on host | guests only create proposals; host approves (`core/roles.py`, `host/actor.py`) |
| prompt injection via guest | provenance taint forces `ask` for write/exec (`core/policy/engine.py`) |
| compound shell bypass (`ls; rm`) | allow rules ignored for compound commands → `ask` |
| session `always` overriding deny | base deny rules are evaluated first and cannot be overridden |
| compromised relay | host signs tokens and checks permissions; relay only routes (`relay/`) |
| token theft | 24h TTL, room binding, token bound to connection, revoked participants removed from state |
| secret leakage | path deny-list (`security/secrets.py`), env scrubbing for `bash`, redaction before append |
| agent badgering the host with variants of a rejected action | rejection ledger per run and class, `Block (session)` deny rule (`host/policy_gate.py`, `core/policy/rejections.py`) |
| agent or guest widening its own permissions | policy rules are events changed only by host commands (`core/roles.py`); an allow rule never overrides a built-in deny or the guest taint; rules are never read from the workspace the agent can write |
| laundering injected text through a conversation summary | the summary is presented to the model as untrusted notes, runs keep their merged provenance, and write/exec by guest-originated turns still ask (`agent/messages.py`, ADR 0003) |
| slow/flooding clients | bounded queues, rate limit and size limit on relay |

Out of scope for MVP: E2E encryption (relay sees content), Docker isolation.
