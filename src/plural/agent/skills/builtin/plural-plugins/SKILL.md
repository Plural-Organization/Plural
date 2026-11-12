---
name: plural-plugins
description: Only for Plural plugins, Python files that add /commands or agent tools to Plural itself; write, fix or explain one, or why it failed to load.
---

# Plural plugins

A plugin is one Python file in the host's plugin folder, `~/.plural/plugins/<name>.py` (under
`PLURAL_DATA_DIR` when the host set it; `/plugins` shows each plugin's path). The host imports every
file there at start and on `/plugins reload`, and calls its `setup(plural)` function. A plugin can add:

- **commands**: `/name` typed by a person in the room, handled by an async function;
- **tools**: functions the agent calls like any other tool, through the host's approvals.

Plugins run inside the host process with the host's permissions. Only the host installs them, and they
are never loaded from the workspace.

## Where you write it

You work inside the workspace, so you cannot write to the plugin folder yourself. Write the plugin to
`plugins/<name>.py` in the workspace, unless the user named another place, then either:

- ask to copy it with bash, which the host approves:
  `mkdir -p ~/.plural/plugins && cp plugins/<name>.py ~/.plural/plugins/`
- or tell the host to run `/plugins new <name>` and paste the file's content into the path it shows.

Then the host runs `/plugins reload`. `/plugins` lists every plugin with ✓ and its commands and tools,
or ✕ and the error, for example `SyntaxError line 3` or `/deploy is already taken`.
`/plugins rm <name>` deletes a plugin's file and unloads it.

## Commands

```python
def setup(plural):
    @plural.command("review", description="Review the uncommitted changes", host_only=False)
    async def review(ctx):
        diff = await ctx.run("git", "diff")
        if not diff.strip():
            await ctx.reply("nothing to review")
            return
        await ctx.prompt(f"Review this diff and point out bugs:\n{diff[:20000]}")
```

`plural.command(name, description="", usage="", host_only=False)` registers an **async** handler that
takes `ctx`:

| | |
|---|---|
| `ctx.args` | the text after the command, a string, may be empty |
| `ctx.author`, `ctx.author_id`, `ctx.role` | who ran it (`role` is `host` or `participant`) |
| `ctx.workspace` | the workspace path on the host |
| `await ctx.reply(text)` | a reply the whole room sees |
| `await ctx.prompt(text, follow_up=False, display=None)` | a prompt to the agent **as the person who ran the command**; the room sees `display` and the full text folded |
| `await ctx.show(title, text)` | a window only the person who ran the command sees, not logged |
| `await ctx.confirm(title)` / `await ctx.select(title, options)` / `await ctx.input(title, default="")` | ask the person who ran the command and wait: `bool`, the option or `None`, the text or `None`; closed or five minutes unanswered is `False`/`None` |
| `await ctx.notify(text)` | a toast only they see |
| `await ctx.ask(question, history=True, model="fast")` | one answer from the session's model, outside the conversation: no tools, nothing added to the history; raises `PluginError` if no model answers |
| `await ctx.run(*argv, timeout_s=120)` | runs a program in the workspace without a shell, returns stdout; raises on a non-zero exit or a timeout |

For a side question (`/btw`) use `ctx.ask` + `ctx.show`, not `ctx.prompt`: the main task and the room are
left alone.

Names use `a-z`, `0-9`, `-` and `_` and cannot reuse a built-in command (`abort`, `cancel`,
`compact`, `copy`, `help`, `invite`, `leave`, `mcp`, `mode`, `plugins`, `policy`, `quit`,
`settings`, `skills`, `who`) or another plugin's command. `host_only=True` refuses the command to
everyone but the host; viewers can never run commands. If a handler raises, the room sees
`/name failed: …`.

`ctx.prompt` takes the same path as a typed prompt: in review mode a guest's prompt becomes a proposal,
write and exec actions still wait for the host, and the guest token budget applies. Never use it to get
around those rules. When the prompt wraps the user's words in instructions, pass their words as
`display` so the room does not read the instructions as theirs.

## Tools for the agent

```python
def setup(plural):
    @plural.tool(
        "ticket",
        description="Look up a ticket by key: title, status and assignee",
        parameters={"key": "Ticket key, for example PLR-123"},
        risk="read",
    )
    async def ticket(args, ctx):
        ctx.log("asking the tracker")
        return await ctx.run("tracker", "show", args["key"])
```

`plural.tool(name, description, parameters=None, risk="read", exposure="deferred")` registers an
**async** handler that takes `(args, ctx)`:

| | |
|---|---|
| `name` | `a-z`, `0-9` and `_`; not a built-in tool (`read`, `bash`, `edit`, …) or another plugin's tool |
| `description` | what the tool does and returns; the agent picks tools by it, and `tool_search` searches it |
| `parameters` | `{"name": "description"}` for required string arguments, or a full JSON schema object |
| `risk` | `read`, `write` or `exec`. Say what the tool really does: write and exec in a guest's run always ask the host |
| `exposure` | `deferred`: the agent finds it with `tool_search`. `core`: declared on every request; keep it rare |

`args` is a dict of the call's arguments. `ctx.workspace`, `ctx.log(text)` (live progress for the
room) and `await ctx.run(*argv)` work as above. Return a string for the model, or any JSON value. An
exception becomes an error result the model reads, so raise with a clear message instead of returning
an error string. Every call goes through the host's policy: a tool without a rule asks the host, and
the host can allow it for good with `/policy allow <tool> *`.

## Keeping state

`plural.store.get(key, default)`, `.set(key, value)`, `.delete(key)` and `.all()` keep JSON values in
`~/.plural/plugins/.data/<name>.json` across reloads and restarts (1 MB at most). Use it instead of
module variables for anything that must survive `/plugins reload`.

## A status line

`plural.status(text)` (on the `plural` object from `setup`, usable anywhere) sets the plugin's one line in
the side panel that the whole room sees, at most 80 characters and one change a second; `""` removes it.
Use it for state that matters while people work, such as `tests 3/3 ✓` after a `run_end` hook.

## Hooks

`@plural.on("tool_call")` runs before the policy on every tool call the agent makes. The handler gets
`(call, ctx)`: `call.name`, `call.risk`, `call.subject`, `call.args`, `call.author_id`, `call.role`. It
returns `plural.deny(reason)`, `plural.ask(reason)` or nothing. There is no allow, so use it for guards
("never push to main", "ask before touching migrations/"), not to skip approvals. Keep it fast: after 5
seconds, or if it raises, the call needs the host's approval.

`@plural.on("tool_args")` runs first on every tool call and may change its arguments: it gets `(call,
ctx)` (`call.name`, `call.args`, `call.author_id`, `call.role`) and returns the new arguments as a dict,
or nothing to leave them. The changed call is then validated and put to `tool_call` hooks and the policy
like any other. 5 seconds; a hook that fails changes nothing. Use it to fix commands (`pip` → `uv pip`),
add flags, or point paths elsewhere.

`@plural.on("tool_result")` runs after a tool call that ran and may replace what the model gets back:
it gets `(result, ctx)` (`result.name`, `result.risk`, `result.subject`, `result.args`,
`result.content`, `result.is_error`, `result.author_id`, `result.role`) and returns the new text, or
nothing. 5 seconds; a hook that fails changes nothing. Use it to hide secrets, shorten noisy output or
add a hint to an error.

`@plural.on("session_start")` gets `(session, ctx)` (`session.room`, `session.workspace`) after the
plugins load, at start and on every reload.

`@plural.on("before_run")` gets `(prompt, ctx)` (`prompt.text`, `prompt.author_id`, `prompt.role`) when
a run starts and returns text the agent reads as a note right before the prompt, or nothing. 5 seconds,
8,000 characters across plugins. Use it for facts the agent should not have to look up: branch, failing
tests, ticket.

`@plural.on("run_end")` runs after each run with `(run, ctx)`: `run.reason` (`stop`, `aborted`, `error`,
`limit`), `run.error`, `run.author_id`, `run.role`, `run.files` (edited or written this run),
`run.input_tokens`, `run.output_tokens`. `ctx.reply`, `ctx.run` and `ctx.prompt(text)` (as the host) work;
the run a hook prompt starts does not fire `run_end` again. Good for running tests or a linter after the
agent changed files.

## Good plugins

- Keep handlers `async`. Wrap blocking work in `await asyncio.to_thread(...)` so the room does not
  freeze.
- Module-level variables keep state between calls until the next `/plugins reload`; `plural.store` keeps it for good.
- Read settings from the environment, never hard-code tokens, and never put secrets in replies or tool
  results.
- Trim large output (`text[:20000]`) before replying or prompting.
- One file can hold several commands and tools; the file name is the plugin's name.

## Checklist before you hand it over

1. The file defines `setup(plural)` and every handler is `async def`.
2. Names follow the rules above and do not clash with built-ins.
3. Each tool's `risk` matches what it does.
4. You told the host where the file goes and to run `/plugins reload`, then how to try it: the
   command to type, or a request that makes the agent use the tool.
