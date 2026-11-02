# ADR 0011: plugins ask the person who ran them

Status: accepted

## Context

A plugin command could reply, prompt the agent and show a window, but not ask anything back: `/deploy`
cannot let someone pick staging or prod, and cannot ask "are you sure?" before it runs a script. In pi the
extension and the interface share a process, so `ctx.ui.confirm()` is a function call. In Plural the
plugin runs on the host and the interface is a client, of which a room has several, so a question has to
travel there and back.

## Decision

- A command context gets `confirm(title) -> bool`, `select(title, options) -> str | None`,
  `input(title, default="") -> str | None` and `notify(text)`.
- A question goes only to the person who ran the command, as the transient event `plugin.asked` with an
  id, its kind, title, options and default. Nothing is logged.
- The client answers with the command `plugin.answer {ask_id, value}`; no value means it was closed. The
  host accepts an answer only from the person asked, and for `select` and `confirm` only one of the
  options.
- A person has at most one open question; a second one raises `PluginError` in the plugin. A question
  that is not answered in five minutes, or whose person goes offline, answers `None` (`False` for
  `confirm`), so a plugin never waits forever.
- `notify(text)` is the transient event `plugin.notified`, a toast for the same person.
- Hooks cannot ask: they run for no one in particular, and a guard must not wait on a person.
- The terminal opens a question in the tray, as a choice or a text step, and esc answers with nothing.
  The web client shows it first in the inbox, with a close button.

## Consequences

- Commands can be interactive without new trust: answers reach only the plugin that asked, and only from
  the person it asked.
- A plugin that asks and then crashes leaves nothing behind; a plugin that never gets an answer gets
  `None` after five minutes.
- Questions are lost if the person reconnects to another device mid-question; they then time out.
