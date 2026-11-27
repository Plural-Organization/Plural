# ADR 0018: a second person can approve tool calls

Status: accepted

## Context

Only the host answered an approval card. That is written into ADR 0004 and the threat model, and it is the
reason a guest's prompt cannot run a command: the run is tainted, so every write and every command asks
the host.

It also made the host the only point of failure for a session that several people use. When the host
stepped away from the keyboard, the run stood still on a card nobody else could answer, however much the
host trusted the person next to them.

## Decision

The host can name an **approver**: a participant who may answer tool-call approvals besides the host.

- `approver.set { participant_id, enabled }` is host only and appends `approver.changed`. The list is
  `SessionState.approvers`, part of the event log, so it survives restarts and reaches every client through
  the snapshot and replay. Only a participant can be named: a viewer or the host cannot.
- `approval.respond` is now sent by the host and participants, and `core/approvals.authorize_response`
  decides who may answer which approval:
  - the host answers everything, as before;
  - an approver answers a tool call with `once` or `reject` only;
  - an approver never answers an approval that their own prompt started, so nobody approves their own run;
  - `always` and `block` make a rule, and rules are changed only by the host;
  - a folder outside the session is answered by the host, who is asked every time.
- The first answer wins, from the host or an approver. The other gets `not_found`, because the approval is
  gone.
- A person stops being an approver when they lose the right to write or leave the session.

Nobody becomes an approver by joining, by a role, or by a flag at start. The clients offer `/approver add
<name>`, `/approver rm <name>` and `/approver` to list them.

## Consequences

- The taint is unchanged: a run with a guest's prompt still asks, an `allow` rule still does not lift it.
  What changes is who may answer. The host is choosing to trust the named person with the host's machine for
  one call at a time, so name someone you would let sit at your keyboard.
- Two people who work together can still approve each other's calls: A prompts and B approves, then B
  prompts and A approves. That is the point of the mode, and it is why it is off until the host turns it on.
- Approvals were already visible to everyone in the room, so no event had to be filtered.
- The host still has to be online, because the agent and its tools run on the host's computer. This removes
  the host's keyboard from the loop, not the host's computer.
