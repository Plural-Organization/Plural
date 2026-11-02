# Plugins

A plugin adds slash commands to a room. It is a Python file on the host's machine; everyone in the room
sees its commands in the suggestions and can run the ones the plugin allows.

> [!WARNING]
> A plugin runs inside the host process with the host's permissions. Install only code you trust.
> Plugins load from the data directory (`~/.plural/plugins/`), never from the workspace, so a cloned
> repository cannot add one.

## Create one

The easiest way is to ask the agent: it has a built-in `plural-plugins` skill with this whole guide,
loads it when you ask for a plugin, and writes the file for you to install.

In the terminal client, as the host:

```text
/plugins new hello      creates ~/.plural/plugins/hello.py from a template
/plugins                lists plugins, their commands and file paths
/plugins rm hello       deletes ~/.plural/plugins/hello.py and unloads it
/plugins reload         applies your edits without restarting the host
```

Open the file, edit it, run `/plugins reload`, then `/hello` in the room.

## Write one

A plugin file defines `setup(plural)` and registers commands with `plural.command`:

```python
def setup(plural):
    @plural.command("hello", description="Say hello")
    async def hello(ctx):
        await ctx.reply(f"Hello {ctx.author}! You wrote: {ctx.args or 'nothing'}")

    @plural.command("review", description="Review the current diff", host_only=True)
    async def review(ctx):
        diff = await ctx.run("git", "diff")
        await ctx.prompt(f"Review these changes:\n{diff}")
```

`plural.command(name, description="", usage="", host_only=False)` registers an `async` handler for
`/name`. Names use `a-z`, `0-9`, `-` and `_`, and cannot reuse a built-in command or another plugin's
command. `host_only=True` refuses the command to everyone but the host. Viewers cannot run commands.

The handler gets a context:

| | |
|---|---|
| `ctx.args` | the text after the command |
| `ctx.author`, `ctx.author_id`, `ctx.role` | who ran it |
| `ctx.workspace` | the workspace directory |
| `await ctx.reply(text)` | posts a reply the whole room sees |
| `await ctx.prompt(text, follow_up=False, display=None)` | sends a prompt to the agent as the person who ran the command |
| `await ctx.show(title, text)` | opens a window only the person who ran the command sees; nothing is logged |
| `await ctx.confirm(title)` | asks the person who ran it yes or no; closing or five minutes without an answer is `False` |
| `await ctx.select(title, options)` | lets them pick one of up to 20 options; `None` if they close it |
| `await ctx.input(title, default="")` | lets them type a line; `None` if they close it |
| `await ctx.notify(text)` | a short toast only they see |
| `await ctx.ask(question, history=True, model="fast")` | asks the session's model one question outside the conversation and returns the answer |
| `await ctx.run(*argv, timeout_s=120)` | runs a program in the workspace without a shell and returns its output; a non-zero exit raises |

A side question that should not touch the conversation, answered only to the person who asked:

```python
@plural.command("btw", description="Ask something on the side", usage="/btw <question>")
async def btw(ctx):
    answer = await ctx.ask(ctx.args)
    await ctx.show("btw", answer)
```

Asking before acting:

```python
@plural.command("deploy", host_only=True)
async def deploy(ctx):
    target = await ctx.select("where to?", ["staging", "prod"])
    if target is None or not await ctx.confirm(f"deploy to {target}?"):
        return
    await ctx.notify("deploying")
    await ctx.reply(await ctx.run("./deploy.sh", target))
```

A question goes only to the person who ran the command: the terminal opens it under the composer (esc
closes it), the web client puts it first in the inbox. One question is open per person at a time.

`ctx.ask` sees the conversation so far, cannot call tools, and adds nothing to the history; its tokens
count as session usage.

`ctx.prompt` goes through the same path as a typed prompt. In `review` mode a guest's prompt becomes a
proposal, write and exec actions still wait for the host, and `PLURAL_GUEST_RUN_TOKENS` applies.

When a plugin wraps a short request in longer instructions, pass the short one as `display`: the room
sees `what is overfitting?` marked `via /btw`, and the full text the agent got stays folded under it, one
click or `ctrl+o` away. A proposal shows the host the full text.

## Tools for the agent

A plugin can also give the agent a tool. The agent calls it like any other tool, and its return value
is the tool's result:

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

`plural.tool(name, description, parameters=None, risk="read", exposure="deferred")`:

| | |
|---|---|
| `name` | `a-z`, `0-9` and `_`; it cannot reuse a built-in tool or another plugin's tool |
| `parameters` | a mapping of name to description (required strings), or a full JSON schema object |
| `risk` | `read`, `write` or `exec`. Like every tool the call goes through the host's policy: a tool without a rule asks the host, and write and exec in a guest's run always do. Allow one for good with `/policy allow ticket *` |
| `exposure` | `deferred` (default): the agent finds it with `tool_search`. `core`: declared on every request |

The handler receives the arguments as a dict and a context with `ctx.workspace`, `ctx.log(text)`, which
streams progress to the room, and `await ctx.run(*argv)`. A string result goes to the model as is, any
other value as JSON. If the handler raises, the model gets the error as the tool's result.

## Keeping state

Module variables reset on `/plugins reload`. What must last goes in `plural.store`, a JSON file of the
plugin's own at `~/.plural/plugins/.data/<name>.json`:

```python
runs = plural.store.get("runs", 0)
plural.store.set("runs", runs + 1)
plural.store.delete("old")
plural.store.all()
```

Values are anything JSON can hold. Every `set` and `delete` writes the file at once, through a temporary
file, and a store holds at most 1 MB. `/plugins rm` leaves the file, so a plugin added back finds its data.

## A line in the side panel

`plural.status(text)` keeps a short line for the plugin in the side panel, under the session, for
everyone in the room: `ci  tests 3/3 ✓`. Call it from a command, a tool or a hook; an empty text removes
the line. It is one line of at most 80 characters, the host shows at most one change a second (the
latest wins), and the line goes away when the plugin is removed or fails to load.

## Hooks

`plural.on(event)` runs a function when something happens instead of when someone calls it.

### Guarding tool calls

A `tool_call` hook sees every tool call the agent makes before the host's policy is applied, and can make
the host stricter, never looser:

```python
def setup(plural):
    @plural.on("tool_call")
    async def guard(call, ctx):
        if (
            call.name == "bash"
            and "git push" in call.args.get("command", "")
            and "main" in call.subject
        ):
            return plural.deny("pushes to main go through review")
        if call.name == "edit" and call.subject.startswith("migrations/"):
            return plural.ask("migrations need a second look")
```

| | |
|---|---|
| `call.name`, `call.risk`, `call.subject`, `call.args` | the tool, `read`/`write`/`exec`, what it acts on, and its arguments |
| `call.author_id`, `call.role` | who started the run the call belongs to |
| `return plural.deny(reason)` | refuses the call; the agent is told the reason and not to retry |
| `return plural.ask(reason)` | the host approves it even in auto mode; the card shows `<plugin> plugin: <reason>` |
| return nothing | the policy decides as usual |

Any deny wins. There is no allow: a call the policy refuses, or one plan mode forbids, never reaches the
hook. A hook gets 5 seconds; one that raises or takes longer counts as `ask`, so a broken guard makes the
host ask rather than let a call through. `ctx.reply(text)` and `ctx.run(*argv)` work as in commands.

### When the plugins load

A `session_start` hook runs after the plugins load: when the host starts and after every
`/plugins reload`, `new` or `rm`. It gets `session.room` and `session.workspace`, and `ctx.reply` and
`ctx.run` work. Use it to check the environment or set the first status line:

```python
@plural.on("session_start")
async def ready(session, ctx):
    plural.status("watching tests")
```

It has 120 seconds; if it fails the room sees why.

### Before a run

A `before_run` hook can hand the agent context just before a run starts, such as the branch or the tests
that fail:

```python
def setup(plural):
    @plural.on("before_run")
    async def branch(prompt, ctx):
        name = (await ctx.run("git", "branch", "--show-current")).strip()
        return f"current branch: {name}"
```

It gets `prompt.prompt_id`, `prompt.text`, `prompt.author_id` and `prompt.role`, and returns text or
nothing. The text goes to the agent as a note from the plugin right before the prompt, never into the
system prompt, and is kept in the session log, so a restored session gives the agent the same note. The
room sees a short line saying the plugin added context. Notes from all plugins together are capped at
8,000 characters; a hook gets 5 seconds and one that fails or is late adds nothing. It runs when a run
starts, not for a prompt that joins a run already going. Unlike a briefing, a plugin's note does not
make the agent ask before every change: it is the host's own code.

### After a run

A `run_end` hook runs after every run of the agent, in the background:

```python
def setup(plural):
    @plural.on("run_end")
    async def tests(run, ctx):
        if run.reason == "stop" and any(path.endswith(".py") for path in run.files):
            output = await ctx.run("pytest", "-q")
            await ctx.reply(output.strip().splitlines()[-1])
```

| | |
|---|---|
| `run.reason`, `run.error` | `stop`, `aborted`, `error` or `limit`, and the error if any |
| `run.author_id`, `run.role` | who started the run |
| `run.files` | files the agent edited or wrote in this run, relative to the workspace |
| `run.input_tokens`, `run.output_tokens` | what the run used |
| `await ctx.reply(text)`, `await ctx.run(*argv)` | as in commands |
| `await ctx.prompt(text, follow_up=True, display=None)` | prompts the agent **as the host** |

A run started by a `run_end` prompt does not fire `run_end` again, so hooks cannot keep the agent going
on their own. Such a prompt is the host's, so it is not reviewed and does not taint the run; do not paste
a guest's text into it. A hook has 120 seconds; if it fails the room sees why and the other hooks still
run.

If a handler raises, the room sees `/name failed: …` and the host keeps running. A file that fails to
import, has no `setup`, or registers a taken name is listed as failed by `/plugins` with the reason.

Replies are scrubbed of known secrets like every other event, and both the call (`command.invoked`) and
the reply (`command.replied`) are kept in the session log.
