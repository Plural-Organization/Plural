---
name: plural-plugins
description: Write, fix or explain a Plural plugin, a Python file that adds slash commands to the room or tools for the agent. Use when someone asks for a custom /command, a plugin, a plugin tool, or why a plugin failed to load.
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
| `await ctx.prompt(text, follow_up=False)` | a prompt to the agent **as the person who ran the command** |
| `await ctx.run(*argv, timeout_s=120)` | runs a program in the workspace without a shell, returns stdout; raises on a non-zero exit or a timeout |

Names use `a-z`, `0-9`, `-` and `_` and cannot reuse a built-in command (`abort`, `cancel`,
`compact`, `copy`, `help`, `invite`, `leave`, `mcp`, `mode`, `plugins`, `policy`, `quit`,
`settings`, `skills`, `who`) or another plugin's command. `host_only=True` refuses the command to
everyone but the host; viewers can never run commands. If a handler raises, the room sees
`/name failed: …`.

`ctx.prompt` takes the same path as a typed prompt: in review mode a guest's prompt becomes a proposal,
write and exec actions still wait for the host, and the guest token budget applies. Never use it to get
around those rules.

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

## Good plugins

- Keep handlers `async`. Wrap blocking work in `await asyncio.to_thread(...)` so the room does not
  freeze.
- Module-level variables keep state between calls until the next `/plugins reload`.
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
