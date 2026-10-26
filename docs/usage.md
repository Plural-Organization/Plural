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
| `--room <id>` | Resume a room, its log and settings are kept |

## Join a session

```bash
plural join "ws://host:7777/r_…?invite=…" --name alia
```

An invite is single-use and expires after an hour. The host creates a new one with `/invite` or from the settings. The link is copied to the clipboard.

## Prompt modes

| Mode | What happens to a participant's prompt |
|---|---|
| `open` (default) | It goes straight to the agent, attributed to the participant |
| `review` | It becomes a proposal and waits for the host, who approves, edits or rejects it |

Change it with `/mode open|review`, from the settings, or at start with `--prompts`. Tool calls need the host's approval in both modes. A run that contains a participant's prompt always asks, whatever the rules say.

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

## Commands

| Command | What it does |
|---|---|
| `/help` | Commands and keys |
| `/who` | Participants |
| `/invite [participant\|viewer]` | Create an invite link (host) |
| `/mode open\|review` | Who may prompt directly (host) |
| `/policy` | Show the permission rules (host) |
| `/policy allow\|ask\|deny <tool> <pattern>` | Add a rule (host) |
| `/policy rm <id>` | Remove a rule (host) |
| `/compact` | Summarize the conversation before the next prompt (host) |
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

**Model** (host only). Choose a provider (Anthropic, OpenAI, Google Gemini, OpenRouter, Groq, DeepSeek, Ollama, a custom OpenAI-compatible endpoint, or the demo agent), type or paste the API key, pick or type the model, and press *Test connection* to see whether it answers. *Save and use* switches the agent at once, the conversation is kept. A local model also asks for the context window the server really uses.

The key is kept in `~/.plural/credentials.json`, readable only by you, when *Remember the key* is on, and it is sent only to your own host through a local pipe, never over the network. Keys in the environment (`ANTHROPIC_API_KEY` and so on) keep working. Participants do not see this tab: the agent and its key belong to the host.

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
