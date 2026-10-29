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
| a leaked room link lets a stranger into the room | the link only lets a person ask: by default the host answers each request, the person sees nothing of the room until then, at most five wait for two minutes each, and `/invite revoke` replaces the code (`host/gateway.py`, `core/joins.py`); with `admission=open` the link is a bearer secret and the docs say to keep it private |
| a stranger reads who is knocking, or answers for the host | requests, their resolutions and the waiting list go only to the host, and `join.decide` is host only (`core/visibility.py`, `core/roles.py`) |
| a private message read by another guest | the host delivers a `chat.posted` with a recipient only to its author and its addressee: live events, history, replay and the snapshot are filtered per connection (`core/chat.py`, `host/publisher.py`); the host, its log and the relay can still read it, so it is private from guests only |
| chat text steering the agent | chat events are not part of the conversation the agent is built from, so no chat text reaches the model (`host/history.py`, tested in `tests/e2e/test_chat.py`) |
| a stranger lists or opens a team's sessions | the directory answers only a valid member certificate plus a signature over a fresh nonce, and a host checks both against the team key it pinned (ADR 0007) |
| a member shows a card under someone else's name, or takes over their room | the directory writes the owner of a card from the member's certificate, never from the card, and refuses a room that already belongs to another member (`relay/presence.py`) |
| a member floods the directory with cards | a card frame is at most 8 KB, a member can show 5 sessions, and a card not renewed within a minute is dropped (`relay/team_routes.py`, `relay/presence.py`) |
| a removed member keeps showing sessions | removal drops their cards at once and the next frame on their open connection closes it (`relay/directory.py`) |
| a stolen member certificate | the certificate alone is useless without the member's private key, it expires, and removing the member revokes it |
| a compromised directory adds a member | the new member can at most become a viewer of sessions that admit team viewers; writing always needs the host to approve `access.request` |
| a viewer reads what the owner did not share | sessions are private and unpublished by default; the card holds no prompts, replies or file contents, only names, repository, status and changed paths |
| context shared between agents steering the other agent | a shared summary reaches the model as untrusted notes, keeps the guest taint and never changes the system prompt (ADR 0003, ADR 0007) |
| slow/flooding clients | bounded queues, rate limit and size limit on relay |

Out of scope for MVP: E2E encryption (relay sees content), Docker isolation.
