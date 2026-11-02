# ADR 0010: plugin asides and private windows

Status: accepted

## Context

A plugin such as `/btw` wants to answer a side question about the session. With only `ctx.prompt` it has
to put the question into the conversation: the agent spends a turn of the main task on it, the answer
stays in the history for every later request, and the whole room reads both. Agents such as pi and Claude
Code answer side questions with a separate model call and show the answer to the person who asked.

## Decision

- `ctx.ask(question, history=True, model="fast")` asks the session's model one question and returns the
  answer to the plugin.
  - It runs outside any run, like a briefing (`AgentLoop.ask` beside `AgentLoop.brief`): the request
    carries the system prompt, the settled conversation when `history` is true, and the question. The
    tool list is sent so a history with tool calls stays valid, and the question says not to call tools;
    any tool call is ignored.
  - Nothing is added to the conversation and no event is recorded. A run in progress is not touched.
  - `model="fast"` uses the fast model and falls back to the main one; `"main"` uses only the main one.
    The tokens are recorded as session usage under `plugin`. The answer is redacted like any other output.
  - It times out after 120 seconds and raises `PluginError` when no model answers.
- `ctx.show(title, text)` opens a window for the person who ran the command, and nobody else.
  - The host sends the transient event `plugin.shown` to that participant's connections only. It is not
    logged, so a reconnect, a late joiner and `plural-host export` do not see it.
  - The terminal opens it in the tray and keeps a card in that person's conversation view; the web
    client shows the card. Text is capped at 20,000 characters.

## Consequences

- `/btw` answers from the session's context without changing it, and only the asker sees the answer.
- A guest who can run a plugin command can spend the host's tokens through `ask` without a run, so the
  guest run budget does not apply. The host installs plugins and decides what they expose.
- An aside sees the conversation up to the last settled turn; what the agent is doing right now is not in
  it.
