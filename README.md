<div align="center">

<img src="docs/assets/logo.png" alt="plural" width="96" height="96">

# plural

**the shared room for your coding agent.**

[web app](https://plrl.host/app) · [install](#install) · [quick start](#quick-start) · [docs](#docs) · [security](SECURITY.md) · [contributing](CONTRIBUTING.md)

[![License](https://img.shields.io/badge/license-GPL--3.0--or--later-666666?labelColor=333333)](LICENSE)
[![Release](https://img.shields.io/github/v/release/Plural-Organization/Plural?label=release&labelColor=333333&color=666666)](https://github.com/Plural-Organization/Plural/releases/latest)
[![PyPI](https://img.shields.io/pypi/v/plural-agent?label=pypi&labelColor=333333&color=666666)](https://pypi.org/project/plural-agent/)
[![Python](https://img.shields.io/badge/python-3.12%2B-666666?labelColor=333333)](https://www.python.org/downloads/)

</div>

---

**one agent. one host. everyone in the room.**

- **a shared live session** — the host runs the agent on their machine with their own credentials. teammates join from a terminal or the [web app](https://plrl.host/app) and watch every reply, tool call and diff as it happens.
- **teams on your account** — create a team in the web app or the terminal, invite people, and see its live sessions on every device you sign in on.
- **two ways to prompt** — in `open` mode everyone talks to the agent directly. in `review` mode the host approves each prompt first. switch any time.
- **you approve what matters** — write and exec actions always wait for the host, and a run started by a guest can never be waved through by a rule.
- **see who is doing what** — participants, who is typing, a prompt queue, and an attribution on every turn.
- **tools you can follow** — each call is one line. open it to see the live output of a command or a numbered diff.
- **full screen, in your terminal** — a side panel, themes, mouse and keyboard, copy on select. one binary, no runtime to install.
- **your model, your login** — Claude Code, Codex, an API key, any openai-compatible endpoint, or a local model (ollama, LM Studio). change it mid-session from the room settings when tokens run out.
- **event-sourced** — an append-only log is the source of truth. reconnect, replay and audit come for free.
- **direct or relayed** — connect over your network, or through a relay that never decides permissions and never stores content. run your own relay and nothing depends on ours.

---

## install

```bash
curl -fsSL https://raw.githubusercontent.com/Plural-Organization/Plural/main/install.sh | sh
```

macos and linux, arm64 and x64. windows through wsl. the script downloads two checksummed programs side by side, the `plural` client and the `plural-host` host (a frozen build with Python and the Anthropic and OpenAI sdks inside, so there is no uv, Python or dependency resolve at install time). Claude Code and Codex CLI need no key. to install the host from a package index instead, set `PLURAL_HOST_PACKAGE`.

## quick start

**from the web.** open [plrl.host/app](https://plrl.host/app), sign in, then on your computer:

```bash
plural login    # approves this computer, and starts the background daemon
```

the page finds the daemon, and you start a room in a folder you pick, with the agent you choose, for a team or for people you invite.

**from the terminal.** start in the project you want the agent to work on:

```bash
cd your-project
plural
```

the first line in the conversation is the room link. send it to a teammate, now or later: it does not expire, and you let each person in:

```bash
plural join "ws://…"
```

come back to a session with `plural -r` (or `plural -c` for the latest of this folder), and ask once from a script with `plural -p "…"`. teams: `plural team list`, `plural team use <name>`. see [usage](docs/usage.md).

without a key the host runs a scripted demo agent. pick a real one in `F2` → Model, or in the web app: Claude Code (`claude auth login`), Codex (`codex login`), `ANTHROPIC_API_KEY=… plural`, or a local model. details and the Claude OAuth caveats are in [configuration](docs/configuration.md).

`/help` lists the commands, `F2` opens the settings, `ctrl+o` opens the tool details.

## docs

[usage](docs/usage.md) · [configuration](docs/configuration.md) · [plugins](docs/plugins.md) · [running on a server](docs/self-hosting.md) · [wire protocol](docs/protocol.md) · [threat model](docs/threat-model.md) · [design decisions](docs/adr/) · [development](docs/development.md)

## acknowledgements

plural learns from [pi](https://github.com/badlogic/pi-mono), [opencode](https://github.com/sst/opencode), [hermes](https://github.com/NousResearch/hermes-agent) and [herdr](https://github.com/herdrdev/herdr).

## license

plural is free software, licensed under the [GNU General Public License, version 3 or (at your option) any later version](LICENSE). Versions up to and including 0.2.16 were released under the Apache License 2.0 and stay available under it.
