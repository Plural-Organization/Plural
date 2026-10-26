# ADR 0004: open and review prompt modes

Status: accepted

## Context

A guest's prompt used to become a proposal that the host had to approve before the agent saw it. That is
the safest default, but it makes a session feel like a queue for everyone except the host: a team that
trusts each other wants to talk to the agent directly and keep the host's attention for tool calls.

The security boundary was never the proposal. Tool execution is gated by `PolicyGate`, and any run that
contains a prompt from a non-host is tainted, so write and exec actions always ask the host. Prompt
approval only protected the agent's context from unwanted text and the host's budget from unwanted runs.

## Decision

A session has a prompt mode, `SessionState.prompt_mode`:

- `open` (default): a prompt from a participant is accepted at once with direct provenance and the
  participant's own role. No proposal is created.
- `review`: a prompt from a participant becomes a proposal and waits for `proposal.decide`, as before.

The host changes the mode with `session.set_prompt_mode` (host only), recorded as
`session.prompt_mode_changed`, so the mode is part of the event log, survives restarts and reaches every
client through the snapshot and replay. `plural host --prompts open|review` (`PLURAL_PROMPT_MODE`) sets it
at start; when the flag is absent the persisted mode of a resumed room is kept.

## Consequences

- Provenance is unchanged: `is_guest_originated` treats every role other than host as guest, so the taint
  holds in both modes. An `allow` rule still never lifts the taint, and approvals stay host-only.
- Viewers still cannot prompt. Only the `participant` and `host` roles can submit.
- Prompts of several participants share the existing queue (steer or follow-up delivery); the host can
  abort a run with `/abort`.
- Proposals created in review mode stay pending after a switch to open and can still be decided.
- The cost of a run is decided by whoever may prompt. A host who wants to control spend uses `review`.
