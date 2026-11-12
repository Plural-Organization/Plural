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

## Running a built-in tool your own way

`plural.override(name)` runs one of the agent's built-in tools with a plugin function: `read`, `write`,
`edit`, `multi_edit`, `bash`, `grep`, `glob`, `ls` or `web_fetch`. Use it to run commands in a container
or on another machine, or to change what a tool does without the agent learning a new one:

```python
def setup(plural):
    @plural.override("bash")
    async def in_container(args, ctx):
        if args["command"].startswith(("make", "pytest")):
            return await ctx.run("docker", "exec", "dev", "sh", "-c", args["command"])
        # Nothing back: the built-in bash runs as usual.

    @plural.override("read")
    async def numbered(args, ctx):
        text = await ctx.original()
        return text.replace("\t", "    ")
```

The handler gets the call's arguments and a context with `ctx.workspace`, `ctx.log(text)`, `await
ctx.run(*argv)` and `await ctx.original()`, which runs the built-in tool with the same arguments and
returns its text, raising if it fails. Return the result text, any other value as JSON, or nothing to
let the built-in run.

Only how the call runs changes. The model sees the built-in's description and parameters, the arguments
are checked against them, and the policy, folder access and approvals go by the built-in's risk and
subject, so replacing `bash` cannot make a shell command need less approval. One plugin may replace a
tool; a second that tries fails to load. `/plugins` lists the replaced tools with the plugin's own.

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

## MCP servers

A plugin can bring MCP servers with it. They connect when the plugin loads and disconnect when it is
removed, and are never written to the MCP config files:

```python
import os


def setup(plural):
    plural.mcp("tracker", command="npx", args=["-y", "tracker-mcp"], env={"TOKEN": os.environ["TRACKER_TOKEN"]})
    plural.mcp("docs", url="https://docs.example.com/mcp", headers={"Authorization": "Bearer …"})
```

`plural.mcp(name, command=None, args=(), env=None, url=None, headers=None)` takes a command to launch or
a URL to reach, not both. The server's tools load on demand like those of any MCP server, through
`tool_search` or by name, and the host's policy applies to them. `/mcp` lists it, but it is turned off
or removed by changing the plugin. On a reload, a server whose settings did not change stays
connected, and one that changed is connected again. A name already taken by a configured server, or by
another plugin's, makes the plugin fail to load. Its env and header values are masked in what the room
sees, like any MCP server's.

## Model providers

A plugin can offer a model provider: a company gateway, a local server, any API that speaks the
OpenAI or Anthropic protocol. It shows in the host's model settings (`F2` → Model) next to the built-in
presets:

```python
def setup(plural):
    plural.provider(
        "gateway",
        label="Team gateway",
        base_url="https://llm.example.com/v1",
        models=["fast-1", "smart-1"],
        key_env="GATEWAY_KEY",
    )
```

`plural.provider(id, base_url, models=(), label=None, kind="openai", key_env=None, hint="")`: `id` uses
`a-z`, `0-9`, `-` and `_` and cannot be a built-in preset's or another plugin's; `kind` is `openai` or
`anthropic`, the protocol the API speaks; `models` are offered in settings, the first by default. The
key is read from the environment variable `key_env` when the provider is chosen, and is never stored by
the plugin; without `key_env` no key is sent, as for a local server. A command can switch to it with
`ctx.set_model("smart-1", provider="gateway")`.

## Switching the model

A command the host runs can switch the agent's model, as the host would in settings:

```python
def setup(plural):
    @plural.command("fast", host_only=True, description="Switch to the quick model")
    async def fast(ctx):
        label = await ctx.set_model("claude-haiku-5-5")
        await ctx.notify(f"now on {label}")
```

`await ctx.set_model(model, provider=None)` keeps the provider, key and address the client set and
changes the model; with `provider`, a preset name such as `anthropic` or `openai`, it switches to that
preset with its own sign-in. It returns the new model's label, and everyone in the room sees the
change. It raises `PluginError` when the person who ran the command is not the host, while the agent
works, or when the host was started without a client to configure it, such as `plural-host` on its
own.

## Which tools the agent has

`plural.hide_tools(names)` keeps tools from the agent: they are not declared on its requests,
`tool_search` does not find them, and a call to one by name fails as an unknown tool. It takes effect
from the agent's next model call, also in a run that is going. Calling it again replaces the plugin's
set, and an empty list shows the tools again; a reload or `/plugins rm` shows them too.

A read-only mode, switched by a command:

```python
def setup(plural):
    @plural.command("readonly", host_only=True, usage="/readonly [off]")
    async def readonly(ctx):
        writing = ["write", "edit", "multi_edit", "bash"]
        plural.hide_tools([] if ctx.args == "off" else writing)
        plural.status("" if ctx.args == "off" else "read-only")
```

When several plugins hide tools, every tool any of them hides is hidden.

## Instructions for the agent

`plural.instructions(text)` puts text in the agent's system prompt, so it knows something for as long
as the plugin is loaded: how to use the plugin's tools, a convention of the team, where things live:

```python
def setup(plural):
    plural.instructions("Tickets look like PLR-123. Read one with the ticket tool before you work on it.")
```

The agent reads it as `<plugin name="tickets">…</plugin>` from the start of its next run; a run that is
going keeps the prompt it started with, so the provider's cache holds. Call it again to change the
text, or with `""` to remove it; a reload or `/plugins rm` takes it away too. All plugins together get
4,000 characters, in the order they load, and `/context` shows them as `plugins`. For facts that change
from run to run, such as the branch, a `before_run` hook is cheaper: the system prompt is cached, and
changing it costs the next call the whole prompt.

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

### Changing a call's arguments

A `tool_args` hook runs first on every tool call the agent makes and may replace its arguments, for
example to fix a command or add a flag:

```python
def setup(plural):
    @plural.on("tool_args")
    async def use_uv(call, ctx):
        if call.name == "bash" and "pip install" in call.args.get("command", ""):
            command = call.args["command"].replace("pip install", "uv pip install")
            return {**call.args, "command": command}
```

It gets `call.name`, `call.args`, `call.author_id` and `call.role`, and returns the new arguments as a
dict, or nothing to leave them. Hooks run in turn, each seeing what the one before returned. The changed
call is then validated against the tool's parameters and put to `tool_call` hooks and the policy like
any other, so a hook cannot make a call more permitted than its new arguments are; the room sees the
call as it ran. A hook gets 5 seconds; one that raises, is late or returns something other than a dict
changes nothing.

### Changing what a call gives back

A `tool_result` hook runs after every tool call that ran, before the model sees the result, and may
replace its text: hide a secret, shorten noisy output, or add a hint to an error:

```python
def setup(plural):
    @plural.on("tool_result")
    async def hint(result, ctx):
        if result.is_error and "ModuleNotFoundError" in result.content:
            return result.content + "\nhint: run `uv sync` first"
```

It gets `result.name`, `result.risk`, `result.subject`, `result.args`, `result.content`,
`result.is_error`, `result.author_id` and `result.role`, and returns the new text, or nothing to leave
it. Hooks run in turn, each seeing what the one before returned, and the text is cut at 200,000
characters. Whether the call failed stays as it was. The room and the session log get the result as
the hooks left it; output the tool streamed while it ran was already shown. A call that was denied or
aborted never reaches the hook. A hook gets 5 seconds; one that raises, is late or returns something
other than text changes nothing.

### Changing what the model is sent

A `context` hook runs before every model call of the agent and may change the text of the messages it
is sent: shorten old output, mask a value, or add a reminder to the latest message. The session's
history keeps the original, so the next call starts again from it:

```python
def setup(plural):
    @plural.on("context")
    async def remind(context, ctx):
        last = context.messages[-1]
        if last.role == "user":
            last.content += "\n\nRun the tests before you say it is done."
```

`context.system` is the system prompt, to read. `context.messages` holds each message with `role`
(`user`, `assistant` or `tool`), `content` and, for a tool result, `tool`, the tool that gave it. Set
`content` to change a message; messages cannot be added or removed, so a tool result never loses its
call. Hooks run in turn on the same messages. A hook gets 5 seconds; if it raises or is late, what it
changed is put back, and so is a `content` that is not text.

A model reads the start of its prompt from the provider's cache, so a change to an older message makes
every later call pay for the whole prompt again. With the Claude Code, Codex or Grok CLI it also starts
their session over, since they keep the conversation themselves. Prefer changing the latest messages.

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

### Rewriting a prompt

An `input` hook runs when a run starts and may rewrite the prompt the agent gets, for example to expand
a shorthand:

```python
def setup(plural):
    @plural.on("input")
    async def fix(prompt, ctx):
        if prompt.text.startswith("!fix "):
            return "Fix this bug and run the tests: " + prompt.text.removeprefix("!fix ")
```

It gets the same `prompt` as a `before_run` hook and returns the new text, or nothing to leave it. Hooks
run in turn, then `before_run` hooks see the new text. The room keeps showing what the person typed;
the agent and the session log get the rewritten prompt. Like `before_run`, it runs for the prompt a run
starts with, not one that joins a run already going. A hook gets 5 seconds; one that fails or is late
changes nothing.

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
system prompt, and is kept in the session log, so a restored session gives the agent the same note. A
note that repeats the plugin's latest one is left out, so returning the same branch every run costs
nothing after the first. The room sees a short line saying the plugin added context. Notes from all plugins together are capped at
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

### Writing the compaction summary

When the conversation grows too long for the model, the host summarizes its older part and keeps the
newest part as it is. A `summary` hook can write that summary instead of the model, for example by its
own rules or with another model:

```python
def setup(plural):
    @plural.on("summary")
    async def notes(event, ctx):
        text = await ctx.run("my-summarizer", "--max-words", "400", event.conversation[-100_000:])
        return f"{event.previous or ''}\n{text}".strip()
```

It gets `event.conversation`, the part being summarized written out as text (who said what, which
tools ran and what they gave), `event.previous`, the summary the last compaction left or `None`, and
`event.messages`, how many messages are summarized. It returns the summary text, or nothing to let the
model write it. The first hook that answers wins. The list of files read and changed is added to the
summary either way. A hook gets 120 seconds; one that fails or is late is skipped.

### Watching the agent work

Four events let a plugin follow a run as it goes, to log it, count things, mirror it to another tool or
keep `plural.status` up to date:

```python
def setup(plural):
    calls = {"n": 0}

    @plural.on("tool_start")
    async def count(call, ctx):
        calls["n"] += 1
        plural.status(f"{calls['n']} tool calls, last: {call.name}")
```

| event | gets |
|---|---|
| `tool_start` | `call.run_id`, `call.call_id`, `call.name`, `call.risk`, `call.subject`, `call.args`: a call the agent made, before it is approved and run |
| `tool_end` | `result.run_id`, `result.call_id`, `result.name`, `result.content`, `result.is_error`: what the call gave back, as the model got it |
| `message_end` | `message.run_id`, `message.message_id`, `message.text`, `message.thinking`: a reply of the agent, whole |
| `compaction` | `event.run_id`, `event.summary`, `event.tokens_before`: the conversation was summarized |

These hooks only watch: what they return is ignored, and they cannot change or stop the run. They get
the events in order, in the background, so a slow one never holds up the agent or the room; each call
has 5 seconds, and one that fails is logged and the next event still comes. If more than 1,000 events
wait for the plugins, new ones are dropped.

If a handler raises, the room sees `/name failed: …` and the host keeps running. A file that fails to
import, has no `setup`, or registers a taken name is listed as failed by `/plugins` with the reason.

Replies are scrubbed of known secrets like every other event, and both the call (`command.invoked`) and
the reply (`command.replied`) are kept in the session log.
