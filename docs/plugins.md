# Plugins

A plugin adds slash commands to a room. It is a Python file on the host's machine; everyone in the room
sees its commands in the suggestions and can run the ones the plugin allows.

> [!WARNING]
> A plugin runs inside the host process with the host's permissions. Install only code you trust.
> Plugins load from the data directory (`~/.plural/plugins/`), never from the workspace, so a cloned
> repository cannot add one.

## Create one

In the terminal client, as the host:

```text
/plugins new hello      creates ~/.plural/plugins/hello.py from a template
/plugins                lists plugins, their commands and file paths
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
| `await ctx.prompt(text, follow_up=False)` | sends a prompt to the agent as the person who ran the command |
| `await ctx.run(*argv, timeout_s=120)` | runs a program in the workspace without a shell and returns its output; a non-zero exit raises |

`ctx.prompt` goes through the same path as a typed prompt. In `review` mode a guest's prompt becomes a
proposal, write and exec actions still wait for the host, and `PLURAL_GUEST_RUN_TOKENS` applies.

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

If a handler raises, the room sees `/name failed: …` and the host keeps running. A file that fails to
import, has no `setup`, or registers a taken name is listed as failed by `/plugins` with the reason.

Replies are scrubbed of known secrets like every other event, and both the call (`command.invoked`) and
the reply (`command.replied`) are kept in the session log.
