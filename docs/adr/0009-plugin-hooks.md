# ADR 0009: plugin hooks

Status: accepted

## Context

ADR 0008 gave plugins commands and tools, both of which run only when someone calls them. Most useful
extensions in agents such as pi react to what the agent does instead: refuse `git push` to `main`, run the
tests after a run that changed files, add the current branch and failing tests to a prompt. ADR 0008 left
these event hooks for later.

A hook runs host code on every run and every tool call, in a room where guests prompt the agent. Three
things must not move: the `PolicyGate` decides every tool call, a run with a guest's prompt stays tainted,
and the system prompt and tool list stay fixed for the length of a run so the provider cache holds
(`AgentLoop._prompt_parts`).

## Decision

- `plural.on(event)` registers an async handler. A plugin may register several, for any of four events.
  Handlers run in plugin file order, then registration order.

| Event | When | Gets | May return |
|---|---|---|---|
| `session_start` | after the plugins load, at start and on `/plugins reload` | the workspace | nothing |
| `before_run` | after a prompt is accepted, before the agent sees it | the prompt, its author and provenance | text for the agent |
| `tool_call` | in `HostPolicyGate.check`, before the policy is evaluated | the call view (name, risk, subject, args) and provenance | `ask(reason)`, `deny(reason)` or nothing |
| `run_end` | after `run.ended` is recorded | reason, usage, prompt author, files the agent changed | nothing |

- **A hook can only tighten.** `tool_call` answers `deny`, `ask` or nothing; there is no `allow`.
  - `deny` refuses the call with the plugin's reason and the usual "do not retry" suffix. Any deny wins.
  - `ask` turns a call the policy would allow into an approval card, which names the plugin and its
    reason. A call the policy already asks about or refuses is unchanged.
  - Plan mode and policy denials are evaluated as today; a hook never sees a call to make it pass.
- **Hooks are bounded.** `tool_call` and `before_run` have 5 seconds, `session_start` and `run_end` 120. A
  `tool_call` hook that raises or times out counts as `ask` with "plugin X failed", so a broken guard
  slows the host down instead of opening the gate. A `before_run` hook that fails adds nothing; a
  `session_start` or `run_end` hook that fails is reported to the room. The run goes on either way.
- **`before_run` runs in the run's task**, between `run.started` and the first request, so a slow hook
  never holds up the room. It fires when a run starts, not for a prompt steered into a running one.
- **`before_run` text is context, not instructions from a person.** It goes to the agent as a notes turn
  with source `plugin:<name>` right before the prompt, never into the system prompt. It is recorded as a
  durable event so a restored or exported session shows what the agent saw, and the room sees a collapsed
  line "context from <plugin>". Unlike a briefing, it does not mark the session shared: it is host code.
  The text is capped at 8,000 characters per run across all plugins.
- **`run_end` and `session_start` act through the command context.** They get `reply`, `run`, and, for
  `run_end`, `prompt`, which submits as the host. A run started by a `run_end` prompt does not fire
  `run_end` hooks again, so two plugins cannot keep the agent running in a loop.
- Hooks are registered and reset with the rest of a plugin on `/plugins reload`.

## Consequences

- A plugin can make the host stricter than its policy but never looser, so installing one cannot widen
  what a guest's prompt can do.
- Every tool call waits for its `tool_call` hooks. They must be cheap; the timeout keeps a slow one from
  stalling a run for long, and turns it into an approval rather than a silent pass.
- Hooks see tool arguments and prompts, including guests'. They already run with the host's permissions,
  so this adds no new reader, but the plugin docs must say it.
- Not covered: changing tool arguments or results, allowing calls, changing the system prompt, and
  interactive UI from a hook. Each needs its own decision.
