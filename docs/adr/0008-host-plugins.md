# ADR 0008: host plugins with slash commands

Status: accepted

## Context

Hosts want their own commands in a room: `/review` that sends the current diff to the agent, `/deploy`
that only the host may run, `/hello` for a quick reply. Agents such as pi solve this with extensions:
code the tool loads at startup that registers commands and reacts to events.

Plural differs from a single-user agent in three ways. The agent runs on the host's machine with the
host's credentials, several people can type commands, and every client (terminal, web) must learn about
commands it was not built with. The security model must not move: tool execution is decided by the
`PolicyGate`, and a run that contains a guest's prompt stays tainted.

## Decision

- A plugin is a Python file in `<data dir>/plugins/` (`~/.plural/plugins/` by default). The host imports
  each file at startup and calls its `setup(plural)` function. Plugins are never loaded from the
  workspace, so a cloned repository cannot run code on the host.
- `plural.command(name, description=..., usage=..., host_only=...)` registers an async handler for
  `/name`. A name clash with a built-in command or another plugin fails that plugin, and a plugin whose
  file or `setup` raises is listed as failed with its error. The host keeps running either way.
- The host publishes plugins and commands in `plugins.changed` (durable, part of `SessionState`), so every
  client can suggest and route plugin commands without knowing them in advance.
- `command.run` asks the host to run a plugin command. Viewers cannot send it (contributors only), and a
  `host_only` command is refused to anyone but the host. The call is logged as `command.invoked`.
- A handler runs as a background task with a context that talks to the actor through the inbox:
  - `ctx.reply(text)` records `command.replied`, which the whole room sees.
  - `ctx.prompt(text)` submits a prompt **as the participant who ran the command**, through the same path
    as `prompt.submit`. Prompt modes, proposals, approvals and the guest budget apply unchanged.
  - `ctx.run(*argv)` runs a program in the workspace without a shell. It is host code, like the plugin.
- `plugins.reload` re-imports every plugin and `plugins.create` writes a starter file. Both are host only.

## Consequences

- Plugins are trusted host code: they run in the host process with the host's permissions. The docs say
  so, and only the host can install them.
- A plugin cannot widen permissions. It reaches the agent only through prompts, which the policy treats
  like any other prompt from the invoking participant.
- Late joiners see the command list from the snapshot, but command replies only from the moment they
  joined, like other notices.
- Event hooks (`tool_call`, `turn_end`) are left for a later ADR; this one covers commands only.
