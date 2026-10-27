# Threat model (draft)

| threat | mitigation in code |
|---|---|
| guest runs commands on host | tool calls always need host approval; a run containing a guest prompt is tainted in both prompt modes (`core/roles.py`, `core/provenance.py`, `host/actor.py`) |
| guest floods the agent with prompts or spends the host's budget | `review` mode makes the host approve every prompt; viewers cannot prompt; host aborts with `/abort` |
| prompt injection via guest | provenance taint forces `ask` for write/exec (`core/policy/engine.py`) |
| compound shell bypass (`ls; rm`) | allow rules ignored for compound commands → `ask` |
| session `always` overriding deny | base deny rules are evaluated first and cannot be overridden |
| compromised relay | host signs tokens and checks permissions; relay only routes (`relay/`) |
| token theft | 24h TTL, room binding, token bound to connection, revoked participants removed from state |
| api key typed in the client reaches the wrong party | keys go only through the local stdin pipe between a client and the host it started, never over the protocol or a relay; the host registers them with the redactor (`host/control.py`) |
| Claude OAuth token exposed to a participant | OAuth tokens stay in the host's owner-only local data file and are never sent over the room protocol or relay (`agent/providers/anthropic_oauth.py`) |
| secret leakage | path deny-list (`security/secrets.py`), env scrubbing for `bash`, redaction before append |
| agent badgering the host with variants of a rejected action | rejection ledger per run and class, `Block (session)` deny rule (`host/policy_gate.py`, `core/policy/rejections.py`) |
| agent or guest widening its own permissions | policy rules are events changed only by host commands (`core/roles.py`); an allow rule never overrides a built-in deny or the guest taint; rules are never read from the workspace the agent can write |
| laundering injected text through a conversation summary | the summary is presented to the model as untrusted notes, runs keep their merged provenance, and write/exec by guest-originated turns still ask (`agent/messages.py`, ADR 0003) |
| a third-party skill steering the agent | only the host installs skills: by command, or by approving the agent's `skill_install` like an edit, which plan mode refuses; archives are size-capped, links are skipped and paths may not leave the skill folder; the `skill` tool reads only inside an installed skill and keeps the secret deny-list (`agent/skills.py`, `agent/tools/skills.py`) |
| an MCP server acting with the host's credentials | only the host adds or enables servers; every MCP call is an `exec` that asks the host, keeps the guest taint and is refused in plan mode; server env and headers stay in the host's files and are added to the redactor; tool hints like `readOnlyHint` are not trusted (`agent/mcp.py`) |
| slow/flooding clients | bounded queues, rate limit and size limit on relay |

Out of scope for MVP: E2E encryption (relay sees content), Docker isolation.
