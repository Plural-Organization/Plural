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
| slow/flooding clients | bounded queues, rate limit and size limit on relay |

Out of scope for MVP: E2E encryption (relay sees content), Docker isolation.
