# Usage

## Start a session

```bash
cd your-project
plural
```

`plural` starts a host in the current directory and opens the client. The first lines of the conversation show the room link. Words that are not options become the first prompt: `plural "fix the failing test"`.

| Option | Meaning |
|---|---|
| `-r`, `--resume [id\|title]` | Resume a session, see [Resume a session](#resume-a-session) |
| `-c`, `--continue` | Continue the latest session of this folder |
| `-n`, `--title <title>` | Name the session |
| `-p`, `--print` | Answer once and exit, see [Use it from a script](#use-it-from-a-script) |
| `--workspace <dir>` | Directory the agent works in, default is the current one |
| `--prompts open\|review` | Who may prompt directly, see below |
| `--name <name>` | Your display name |
| `--model <id>`, `--provider <name>`, `--effort <level>` | Model, provider (`anthropic`, `openai`, `gemini`, `ollama`…) and effort for this run only |
| `--permission-mode default\|acceptEdits\|plan\|auto` | Start in that permission mode |
| `--allowedTools <tools>`, `--disallowedTools <tools>` | Allow or deny tools for this run, for example `"Bash(git log *)" Read` |
| `--port <n>`, `--bind <addr>` | Where the host listens in direct mode |
| `--relay <url>`, `--public-url <url>` | Connect through a relay and set the address in invite links |
| `--tunnel cloudflared\|ngrok` | Start a tunnel and put its address in the invite links, see [sharing a session](self-hosting.md) |

An option that does not exist is refused, so a typing mistake does not reach the host by accident. A long dash typed by a chat or a keyboard (`—tunnel`) is read as `--tunnel`.

## Update

```bash
plural update           # install the latest release
plural update --check   # only say whether there is one
```

`plural update` looks up the latest release on GitHub and runs the same installer as the first install, pinned to that version: it upgrades the host (`plural-host`) and replaces the `plural` program next to the one you ran, with the same progress, resume and checksum check. A download that was cut off continues where it stopped when you run it again. It does nothing when you are up to date. A copy that runs from source or from a package manager cannot replace itself and says so.

You do not have to leave plural for it. When plural starts it asks GitHub for the latest release, and if there is a newer one, `● update <version>` appears next to the gear and as the first row of the settings (`F2`). Press `enter` on it to install; the row turns into `✓ installed · restart plural` when it is done. Set `PLURAL_NO_UPDATE_CHECK=1` to skip the look-up. Copies that run from source or from a package manager never see the offer.

## Resume a session

Every session you host is kept in `~/.plural/sessions` with its folder, its title and the whole conversation.

```bash
plural -r                 # choose from the sessions of this folder, tab shows every folder
plural -r refactor        # a title, a piece of a title or the start of an id
plural -c                 # the latest session of this folder
plural sessions           # list them
plural sessions --json    # the same for a script
plural rm <id>            # delete one
```

A resumed session works in the folder it was started in, even when you are somewhere else; `--workspace` chooses another one. The conversation continues where it stopped, the people who were in the room come back with their old links while those are valid, and new invites work as usual. The title is the first prompt unless you named it with `--title`.

The chooser also lists the rooms you joined as a guest. Choosing one takes you back in without a new invite, as long as the link you were given is still valid (a token lasts 24 hours) and the host is running.

## Use it from a script

`plural -p` asks once, prints the answer and exits, without the screen. Text piped in goes before the prompt, or is the prompt.

```bash
plural -p "what does this repo do?"
git diff | plural -p "review this change"
plural -p "list the failing tests" --output-format json
plural -r <id> -p "and fix the first one" --permission-mode acceptEdits
```

`--output-format` is `text` (the default, only the final answer), `json` (one object with `result`, `session_id`, `num_turns`, `duration_ms`, `usage`, `denied` and `error`) or `stream-json` (one event per line, the object last). The exit code is 0 when the run stopped normally and 1 when it failed. The `session_id` is a session like any other: `-r` continues it.

Nobody is there to approve an action, so one that needs approval is **refused**: it is named on stderr and listed in `denied`, and the agent goes on without it. Allow what a script may do with `--allowedTools "Bash(npm test)"`, or with `--permission-mode acceptEdits` (file edits) or `auto`. Deny rules always win, and the built-in protections cannot be switched off. The model is the one you saved in the settings; `--provider` and `--model` choose another for this run, and the key comes from `~/.plural/credentials.json` or the usual environment variable (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`…).

## Share a session

By default the invite works only on your computer. To let others in, open `F2` → Session and choose *Same network* or *Over the internet*, then start `plural` again. [Sharing a session](self-hosting.md) explains the three ways and how to run a relay.

## Join a session

```bash
plural join "ws://host:7777/r_…?invite=…" --name alia
```

## Let people in

The link at the top of the conversation is the **room link**. It is permanent: it never expires, it works for any number of people and it stays the same when you resume the session (while the address of your host stays the same). You can send it at any time.

Anyone who opens it waits on a screen that says the host has to let them in. You get a card in the list of things that wait for you, with their name and the program they use, and a bell if you have it on:

| Key | Answer |
|---|---|
| `y` or `enter` | let them in as a participant |
| `v` | let them in as a viewer |
| `n` | refuse |

Until you answer they see nothing of the room. A request that nobody answers lapses after two minutes, at most five people can wait at once, and a room holds twenty people. After you let someone in they come back on their own for 24 hours without asking again.

| Command | Does |
|---|---|
| `/invite` | copy the room link |
| `/invite once`, `/invite viewer` | one-time invites for one person, who go in without your answer: a participant or a viewer, valid for an hour |
| `/invite revoke` | end the room link: those waiting are refused, the old link stops working and the new one is copied. People who are already in stay |
| `/invite open` | anyone with the link goes in at once, for a team you trust. The link is then as good as a password, keep it private |
| `/invite approve` | back to letting each person in (the default) |

The same choice is in `F2` → Session → *People who use the room link*. A host started by a script can use `--admission open` (or `PLURAL_ADMISSION=open`).

Someone who joined by a one-time invite or who is already in, with a saved token, is never asked.

A teammate can also join from a browser: open the web client, paste the link and type a name. The web client shows the same session, approvals and queue as the terminal. A page served over https can only reach a host through a relay with `wss://`; over plain `ws://` serve the web client over http on the same network.

## Talking to the team

Not everything you type is for the agent. Two forms stay between people, and the agent never receives them:

| You type | Who reads it |
|---|---|
| `/team lunch at one` (also `/to-team`, `/chat`) | everyone in the room |
| `@alia can you review this?` at the start of a line | only Alia, and you see your own copy |

Typing `@` lists the people in the room, `tab` completes the name. A tag inside a team message (`/team @alia look at this`) is read by everyone and also alerts Alia. An `@` that names no one in the room, such as `@src/app.ts`, is still a prompt for the agent.

The person you write to hears the terminal bell and sees a short message at the top right. The browser plays a short sound and marks the tab title when the page is in the background. Turn the bell off in `F2` → Session → *Bell on mentions*.

Participants and the host can write; viewers can read the team chat but cannot write and cannot be written to privately. Messages are kept in the session log, so a person who was away finds them on return, and a late joiner sees the team chat but not what was private.

A private message is private from the other guests, not from the host: it is stored in the host's log, `plural-host export` includes it, and it travels through the relay unencrypted. Do not use it for anything you would not say with the host and the relay operator listening.

## Teams

A team is a group of people who run their own plural, each with their own agent and key, and trust each other enough to see who is around. You see who shares a session; opening each other's sessions comes next.

```bash
plural team create Backend --relay wss://relay.example.com --as vlad
plural team join tm-7f3k9-xq2m4 --relay wss://relay.example.com --as alia
plural team members
plural team invite          # a new code, owner only
plural team kick alia       # owner only
plural team leave
plural team disband         # owner only, deletes the team for everyone
plural team status
```

`create` prints an invite code that works once and for an hour; give it to a teammate, who runs `join` with the same relay. Names are what teammates see and `@name` will use: 1 to 32 letters, digits, dots, dashes or underscores, and unique in the team. The relay must run with a team directory (see [running on a server](self-hosting.md#teams)).

### Showing your session to the team

```bash
plural --team                 # uses the team's relay as the way in
plural --team --tunnel ngrok  # or your own tunnel
plural ls                     # who shares what right now
plural ls --json
```

A session is private unless you start it with `--team`. A team session needs an address others can reach, so it uses the team relay, `--relay`, `--public-url` or a tunnel; plural says so and stops if there is none. The team sees your name, the repository and branch, the title, whether the agent is working or waiting for you, and how many people watch. It does not see prompts, replies or files. The card goes away when you quit, or about a minute after your machine drops off.

The side panel has a SPACES section: your own session first, then the team's, refreshed every few seconds: `●` working, `◆` waiting for its host, `○` idle, with who, repository and branch, and `👁 2` when two people watch.

**Click a teammate to open their session** in the main area. You see all of it, live, as a viewer, and your own session keeps running in the background: a click on `you` takes you back, `alt+←` and `alt+→` move between spaces, `ctrl+w` closes the one you are in. What you type goes to the session you are looking at. If your own agent needs you while you are away, its row turns `◆ waiting`, the bell rings and the terminal title says so.

### Watching a teammate

```bash
plural join @alia            # opens alia's shared session, you can read (or click her in the panel)
plural join @alia:web        # when alia shares more than one, say the repository
```

You come in as a viewer: you see the whole conversation and what the agent does, you cannot prompt or answer approvals. Nobody has to let you in, because the team already vouches for you, and your name is the one in the team. The host sees you in the list of participants and in the team card (`👁 1`), and can remove you with `/kick alia`. A host that removed you keeps you out for the rest of that session even though you are still in the team. A host asks the team again whenever you come back, so someone removed from the team loses their seat within about half a minute.

If the host's relay is not the one the team uses, nothing changes for you: the card carries the address to connect to.

### When two agents work on the same file

A team session also tells the team which files its agent changed in the last half hour and which repository it is in (the remote address without any credentials). When two people in the same repository changed the same file, both of them are told, nothing is blocked:

- your row in the side panel says `⚠ alia also changed src/auth.py` and hers is marked `⚠`, and the conversation gets a note and a short message when it first happens;
- `plural ls` prints the same line under both sessions;
- when your agent asks to edit or write a file a teammate changed in the last half hour, even if you have not touched it yet, the approval card says `⚠ src/auth.py was also changed by alia 3 min ago on feat/x`, so you can wait, ask her, or go on.

Only edits and writes by the agent count, not commands it runs in the shell, and only files inside the workspace. A session that is not a team session shares nothing.

### Asking to write

A viewer who wants to take part types `/access` (with a note if they like: `/access I can fix the login test`). The host gets a card, `y` lets them write, `n` says not now, and the viewer is told either way. After a refusal they can ask again in five minutes. Nobody can ask twice at once, and only a few people wait at a time.

From then on they are a participant: their prompts show their name, the agent still asks the host before it changes anything on their behalf, and in `review` mode the host approves each prompt. A team member keeps the right when they come back to the same session. The host can take it back with `/access revoke alia`; `/access` alone lists who is asking, `/access allow alia` and `/access deny alia` answer by name, and `/kick alia` removes someone.

You are identified by a key that plural creates once in `~/.plural/identity.pem`. Joining gives you a certificate signed for the team, valid for 30 days and renewed by itself. Removing a member stops their access at once. One person is in one team at a time.

## Prompt modes

| Mode | What happens to a participant's prompt |
|---|---|
| `open` (default) | It goes straight to the agent, attributed to the participant |
| `review` | It becomes a proposal and waits for the host, who approves, edits or rejects it |

Change it with `/mode open|review`, from the settings, or at start with `--prompts`. Tool calls need the host's approval in both modes. A run that contains a participant's prompt always asks, whatever the rules say.

## Permission modes

The host decides how much the agent may do without asking. `shift+tab` cycles the modes, and the line under the composer shows the current one to everyone.

| Mode | What the agent may do |
|---|---|
| ask before changes (default) | Reads freely; every edit and command waits for the host, unless a rule allows it |
| accept edits | Edits files without asking; commands still ask |
| plan mode | Only reads and researches, then replies with a plan. Edits and commands are refused |
| auto mode | Edits and runs commands without asking |

Deny rules hold in every mode, and a run that contains a participant's prompt still asks before edits and commands, even in auto mode. When a plan is ready the host picks how to start it: `a` in auto mode, `e` accepting edits, `y` asking before changes, or `n` to keep planning. A restarted host always comes back in the default mode.

## Skills

A skill is a folder with a `SKILL.md`: a name and a description up top, instructions below, and any files it refers to next to it. It is the same format Claude Code, Codex and the [skills.sh](https://skills.sh) catalog use, so skills from Vercel, Anthropic or any public GitHub repository work as they are.

The host reads skills from `.agents/skills`, `.claude/skills` and `.plural/skills` in the project and in the home folder; a project skill wins over a global one with the same name. The agent sees each skill's name and description and loads the full instructions with the `skill` tool when a task matches.

| Command | What it does |
|---|---|
| `/skills` | List the installed skills |
| `/skills search <query>` | Search skills.sh, most installed first |
| `/skills add <owner/repo@skill>` | Install into the project's `.agents/skills` (host) |
| `/skills add <owner/repo@skill> --global` | Install into `~/.agents/skills` for every session (host) |
| `/skills rm <name>` | Remove a skill Plural installed (host) |

The agent can search the catalog on its own and suggest a skill. It can install one too, but every install waits for the host's approval like an edit does, and plan mode refuses it. A skill is someone else's instructions that the agent will follow with the host's permissions, so install skills from sources you trust.

## The screen

The conversation is on the left. The panel on the right shows who is in the room and who is typing, what needs the host, the prompt queue and the state of the agent. `ctrl+b` hides it, and it hides itself on narrow terminals.

The line above the input says who will see what you type: `→ agent` (the whole room sees the prompt), `→ room` after `/team` and `→ @name` for a private message, where the agent does not see it. If a message does not reach the host, the text comes back into the input with the reason, and `↑` recalls it even if you started typing something else.

When you scroll up, a line above the input counts what arrived meanwhile (`↓ 3 new · ✉ 1` with the chat messages), and a click on it or `end` takes you back down. A reply longer than 40 lines is folded; click it or press `ctrl+o` to open. Code blocks and tool output have a `copy` button. The terminal title shows `⚠ waiting for you`, `● working` or `✓ done`, and a run longer than 15 seconds rings the bell when it ends.

`ctrl+f` searches the conversation for text, commands, file paths, tool output and diffs, newest match first, and marks every match in the margin.

Each tool call is one line with what it did and a short result: the lines a command printed, its exit code if it failed, or `+added −removed` for an edit. A running command shows its latest line next to the spinner. Click a line, or press `ctrl+o` for all of them, to see the command with its output or a numbered diff.

### Approvals and proposals (host)

When something waits for you, an approval card appears above the prompt.

| Key | Action |
|---|---|
| `y` | Allow once |
| `a` | Allow and remember the suggested pattern for the session |
| `n` | Reject |
| `b` | Block this kind of action for the session |
| `e` | Edit a proposal before approving it |
| `tab` | Move between the prompt and what waits for you |

Keys are ignored for a moment after a card appears, and a card never takes the keys of a prompt you are typing.

## Sub-agents

The agent can hand a self-contained task to a sub-agent that works in its own context and returns a short report, so the main conversation stays small. `explore` is built in: a read-only researcher that searches the code or the web and cites `path:line`. It runs on the fast model when the host has one and on the main model otherwise. The host picks the fast model in the settings (F2, Model): `auto` takes a cheaper model you can already reach, `off` keeps everything on the main model, or choose one; `PLURAL_FAST_MODEL` does the same from the environment. Several sub-agents can run in parallel.

A sub-agent shows up as one `Agent` line in the conversation with what it is doing right now; `ctrl+o` opens everything it looked at, and the line ends with the model it used, its tool calls and its tokens.

`/agents` lists them and `+ create an agent…` asks for a name, when to use it, its instructions, what it may touch (read only, read and run commands, or read, edit and run), which model and where to save it. Or add your own as Markdown files in `.agents/agents`, `.claude/agents` or `.plural/agents`, in the project or the home folder. The format is the one Claude Code uses:

```markdown
---
name: reviewer
description: Reviews a diff for bugs and missing tests.
tools: Read, Grep, Glob, Bash
model: haiku        # haiku/fast runs on the fast model, anything else on the main one
max_turns: 20
---
You review the diff you are given. Report each problem with path:line.
```

Every tool call a sub-agent makes goes through the same permissions as the main agent: deny rules, the permission mode and the host's approval for edits and commands. A sub-agent cannot start another one.

## MCP servers

The host can connect MCP servers and the agent gets their tools, whatever model it runs on. Servers live in `.mcp.json` in the project or `~/.plural/mcp.json` for every session, in the same `mcpServers` format Claude Code and Cursor use, so a config can be copied over as is.

| Command | What it does |
|---|---|
| `/mcp` | The servers, their status and tool count; `↑↓` chooses, `enter` turns one on or off, `ctrl+r` restarts it. `+ add a server…` opens a wizard with popular servers (Context7, Playwright, GitHub, Notion, Filesystem, Fetch, Git, Memory, Time) or your own command or URL, and asks only for what that server needs |
| `/mcp import` | Takes the servers already set up for Claude Code (`~/.claude.json`) and Cursor (`~/.cursor/mcp.json`) |
| `/mcp add <name> <command…>` | Launches a local server, for example `/mcp add plane npx -y @makeplane/plane-mcp-server` |
| `/mcp add <name> <url>` | Connects a remote server over HTTP |
| `/mcp on\|off\|restart\|rm <name>` | Turns a server on or off, restarts or removes it |

`--global` on `add` saves the server for every project. Environment variables and HTTP headers such as tokens go in the JSON file; they never reach the room and are scrubbed from tool output. Remote servers that sign in with OAuth are not supported yet.

Every MCP tool call waits for the host's approval like a command, and `always` allows that tool for the rest of the session. A run with a participant's prompt still asks in auto mode, and plan mode refuses MCP calls. A server writes its stderr to `~/.plural/state/logs/mcp-<name>.log`.

## Context

Everyone sees how full the agent's context is, in the status bar and the side panel: a bar, the percent and the tokens, green, then yellow, then red as it nears the point where the agent compacts on its own. While the agent summarizes the conversation, a squeezing bar shows it to the whole room, and the bar drops once the summary is in.

## Commands

What a command shows, like `/help`, `/who`, `/skills` or skills.sh search results, opens in a panel under the composer instead of the conversation: it is yours alone and never reaches the agent. `esc` or `✕` closes it. Search results are a picker: `↑↓` chooses, `enter` installs into the project and `g` for every project.

| Command | What it does |
|---|---|
| `/help` | Commands and keys |
| `/team <message>` | Write to the room, the agent does not see it. `@name <message>` writes to one person |
| `/who` | Participants |
| `/invite [link\|once\|viewer\|revoke\|open\|approve]` | Copy the room link, make a one-time invite, or change who may join (host) |
| `/mode open\|review` | Who may prompt directly (host) |
| `/policy` | Show the permission rules (host) |
| `/policy allow\|ask\|deny <tool> <pattern>` | Add a rule (host) |
| `/policy rm <id>` | Remove a rule (host) |
| `/compact` | Summarize the conversation now, or before the agent's next step when it is busy (host) |
| `/skills [search\|add\|rm …]` | List, find and install skills, see [Skills](#skills) |
| `/agents [rm <name>]` | The sub-agents; the host creates one with a short form, see [Sub-agents](#sub-agents) |
| `/usage` | Tokens spent in this session per model, for the conversation, summaries and each sub-agent |
| `/abort` | Stop the current run (host) |
| `/cancel <n>` | Remove a queued prompt, yours or any as the host |
| `/copy` | Copy the last reply |
| `/settings` | Open the settings |
| `/quit` | Leave |

## Keys

| Key | Action |
|---|---|
| `enter` | Send |
| `shift+enter`, `ctrl+j` | New line |
| `shift+tab` | Cycle the permission mode (host) |
| `esc` | Interrupt the run (host) |
| `pgup`, `pgdn`, mouse wheel | Scroll the conversation |
| `ctrl+f` | Search the conversation; `enter` goes to an older match, `shift+enter` to a newer one, `esc` closes. Words must all match; `is:failed`, `is:prompt`, `is:tool`, `is:chat`, `is:reply` and `by:name` narrow it down |
| `end` | Jump to the latest message (when the input is empty) |
| `alt+↑`, `alt+↓` | Previous or next prompt |
| `ctrl+o` | Expand or collapse tool details |
| `ctrl+b` | Show or hide the side panel |
| `ctrl+y` | Copy the last reply |
| `ctrl+v` | Attach the image on the clipboard to the next prompt; backspace in an empty input removes it |
| `F2` | Settings |
| `ctrl+c` | Clear the input, press twice to quit |

Selecting text with the mouse copies it. Hold the terminal's bypass key (`shift`, or `option` in some terminals) for the terminal's own selection.

## Settings

Open them with `F2`, the `⚙ settings` button or `/settings`. On the first launch, when no model is set up, they open by themselves. They work with the keyboard and the mouse: `tab` switches the tab, `↑ ↓` select, `← →` change, `enter` applies, `esc` closes.

**Model** (host only). Choose a provider (Anthropic, Claude OAuth, Claude Code, OpenAI, Google Gemini, OpenRouter, Groq, DeepSeek, Ollama, a custom OpenAI-compatible endpoint, or the demo agent), sign in or enter an API key, then use `← →` on Model to cycle its built-in model list. Press `e` to type another model ID. Claude Code uses the installed `claude` program and its own sign-in; run `claude auth login` in a terminal first. *Test connection* checks whether that model answers with your account. *Save and use* switches the agent at once and remembers the model you picked for each provider; the conversation is kept. A local model also asks for the context window the server really uses.

The key is kept in `~/.plural/credentials.json`, readable only by you, when *Remember the key* is on, and it is sent only to your own host through a local pipe, never over the network. Claude OAuth tokens are kept in `~/.plural/anthropic-oauth.json`; the host uses and refreshes them locally. Keys in the environment (`ANTHROPIC_API_KEY` and so on) keep working. Participants do not see this tab: the agent and its credentials belong to the host.

**Session**. *Open*: everyone prompts the agent directly. *Host approves*: participants propose and you approve, edit or reject every prompt. Also the typing indicator, the bell for requests that need the host and the bell for mentions and private messages.

**Appearance**. Four themes (Tokyo Night, Daylight, Gruvbox, High contrast), the side panel and copy on select, plus shortcuts to copy the last reply and the room link.

Preferences are kept in `tui.json` in the data directory.

## Other commands

| Command | Purpose |
|---|---|
| `plural-host relay` | Run the relay router, see [`deploy/`](../deploy/) |
| `plural-host doctor` | Check the environment, the workspace and the provider |
| `plural-host export <room>` | Dump a session's event log to JSONL |
| `plural-host host` | Serve a session without the client, for a remote machine |

`plural relay`, `plural doctor` and `plural export` run the same commands.
