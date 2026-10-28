# Usage

## Start a session

```bash
cd your-project
plural
```

`plural` starts a host in the current directory and opens the client. The first lines of the conversation show the room and an invite link. Options:

| Option | Meaning |
|---|---|
| `--workspace <dir>` | Directory the agent works in, default is the current one |
| `--prompts open\|review` | Who may prompt directly, see below |
| `--name <name>` | Your display name |
| `--port <n>`, `--bind <addr>` | Where the host listens in direct mode |
| `--relay <url>`, `--public-url <url>` | Connect through a relay and set the address in invite links |
| `--tunnel cloudflared\|ngrok` | Start a tunnel and put its address in the invite links, see [sharing a session](self-hosting.md) |
| `--room <id>` | Resume a room, its log and settings are kept |

## Share a session

By default the invite works only on your computer. To let others in, open `F2` → Session and choose *Same network* or *Over the internet*, then start `plural` again. [Sharing a session](self-hosting.md) explains the three ways and how to run a relay.

## Join a session

```bash
plural join "ws://host:7777/r_…?invite=…" --name alia
```

An invite is single-use and expires after an hour. The host creates a new one with `/invite` or from the settings. The link is copied to the clipboard.

A teammate can also join from a browser: open the web client, paste the invite and type a name. The web client shows the same session, approvals and queue as the terminal. A page served over https can only reach a host through a relay with `wss://`; over plain `ws://` serve the web client over http on the same network.

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
| `/who` | Participants |
| `/invite [participant\|viewer]` | Create an invite link (host) |
| `/mode open\|review` | Who may prompt directly (host) |
| `/policy` | Show the permission rules (host) |
| `/policy allow\|ask\|deny <tool> <pattern>` | Add a rule (host) |
| `/policy rm <id>` | Remove a rule (host) |
| `/compact` | Summarize the conversation now, or before the agent's next step when it is busy (host) |
| `/skills [search\|add\|rm …]` | List, find and install skills, see [Skills](#skills) |
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
| `ctrl+o` | Expand or collapse tool details |
| `ctrl+b` | Show or hide the side panel |
| `ctrl+y` | Copy the last reply |
| `F2` | Settings |
| `ctrl+c` | Clear the input, press twice to quit |

Selecting text with the mouse copies it. Hold the terminal's bypass key (`shift`, or `option` in some terminals) for the terminal's own selection.

## Settings

Open them with `F2`, the `⚙ settings` button or `/settings`. On the first launch, when no model is set up, they open by themselves. They work with the keyboard and the mouse: `tab` switches the tab, `↑ ↓` select, `← →` change, `enter` applies, `esc` closes.

**Model** (host only). Choose a provider (Anthropic, Claude OAuth, Claude Code, OpenAI, Google Gemini, OpenRouter, Groq, DeepSeek, Ollama, a custom OpenAI-compatible endpoint, or the demo agent), sign in or enter an API key, then use `← →` on Model to cycle its built-in model list. Press `e` to type another model ID. Claude Code uses the installed `claude` program and its own sign-in; run `claude auth login` in a terminal first. *Test connection* checks whether that model answers with your account. *Save and use* switches the agent at once and remembers the model you picked for each provider; the conversation is kept. A local model also asks for the context window the server really uses.

The key is kept in `~/.plural/credentials.json`, readable only by you, when *Remember the key* is on, and it is sent only to your own host through a local pipe, never over the network. Claude OAuth tokens are kept in `~/.plural/anthropic-oauth.json`; the host uses and refreshes them locally. Keys in the environment (`ANTHROPIC_API_KEY` and so on) keep working. Participants do not see this tab: the agent and its credentials belong to the host.

**Session**. *Open*: everyone prompts the agent directly. *Host approves*: participants propose and you approve, edit or reject every prompt. Also the typing indicator and the bell for requests that need the host.

**Appearance**. Four themes (Tokyo Night, Daylight, Gruvbox, High contrast), the side panel and copy on select, plus shortcuts to copy the last reply and to create an invite link.

Preferences are kept in `tui.json` in the data directory.

## Other commands

| Command | Purpose |
|---|---|
| `plural-host relay` | Run the relay router, see [`deploy/`](../deploy/) |
| `plural-host doctor` | Check the environment, the workspace and the provider |
| `plural-host export <room>` | Dump a session's event log to JSONL |
| `plural-host host` | Serve a session without the client, for a remote machine |

`plural relay`, `plural doctor` and `plural export` run the same commands.
