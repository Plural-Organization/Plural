<div align="center">

<img src="docs/assets/logo.png" alt="plural" width="96" height="96">

# plural

**the shared room for your coding agent.**

[install](#install) · [quick start](#quick-start) · [docs](#docs) · [security](SECURITY.md) · [contributing](CONTRIBUTING.md)

[![License](https://img.shields.io/badge/license-Apache--2.0-666666?labelColor=333333)](LICENSE)
[![Release](https://img.shields.io/github/v/release/Plural-Organization/Plural?label=release&labelColor=333333&color=666666)](https://github.com/Plural-Organization/Plural/releases/latest)
[![PyPI](https://img.shields.io/pypi/v/plural-agent?label=pypi&labelColor=333333&color=666666)](https://pypi.org/project/plural-agent/)
[![Python](https://img.shields.io/badge/python-3.12%2B-666666?labelColor=333333)](https://www.python.org/downloads/)

</div>

---

**one agent. one host. everyone in the room.**

- **a shared live session** — the host runs the agent on their machine with their own credentials. teammates join from a terminal and watch every reply, tool call and diff as it happens.
- **two ways to prompt** — in `open` mode everyone talks to the agent directly. in `review` mode the host approves each prompt first. switch any time.
- **you approve what matters** — write and exec actions always wait for the host, and a run started by a guest can never be waved through by a rule.
- **see who is doing what** — participants, who is typing, a prompt queue, and an attribution on every turn.
- **tools you can follow** — each call is one line. open it to see the live output of a command or a numbered diff.
- **full screen, in your terminal** — a side panel, themes, mouse and keyboard, copy on select. one binary, no runtime to install.
- **your model, your login** — anthropic by API key or Claude OAuth, any openai-compatible endpoint, or a local model through ollama.
- **event-sourced** — an append-only log is the source of truth. reconnect, replay and audit come for free.
- **direct or relayed** — connect over your network, or through a relay that never decides permissions and never stores content.

---

## install

```bash
curl -fsSL https://raw.githubusercontent.com/Plural-Organization/Plural/main/install.sh | sh
```

macos and linux, arm64 and x64. windows through wsl. the script installs [uv](https://docs.astral.sh/uv/), the host (`plural-host`) and the `plural` client, and checks the download.

## quick start

start in the project you want the agent to work on:

```bash
cd your-project
plural
```

the first line in the conversation is an invite. send it to a teammate:

```bash
plural join "ws://…"
```

without a key the host runs a scripted demo agent. for a real model:

```bash
ANTHROPIC_API_KEY=sk-ant-… plural
```

or open `F2` → Model → Claude OAuth → Sign in with Claude, then paste the code shown in the browser. Anthropic may bill this third-party usage from usage credits rather than subscription limits. To use your actual Claude Code login, run `claude auth login` in a terminal and select `F2` → Model → Claude Code.

To use your Codex sign-in, run `codex login` in a terminal and select `F2` → Model → Codex CLI. Choose a model available to your Codex account. Plural streams replies from one Codex session for the room while its host is running.

Claude OAuth defaults to Haiku 4.5. Newer Claude models may reject third-party OAuth requests even when login succeeds; use an Anthropic API key for those models.

`/help` lists the commands, `F2` opens the settings, `ctrl+o` opens the tool details.

## docs

[usage](docs/usage.md) · [configuration](docs/configuration.md) · [plugins](docs/plugins.md) · [relay deployment](deploy/) · [wire protocol](docs/protocol.md) · [threat model](docs/threat-model.md) · [design decisions](docs/adr/) · [development](docs/development.md)

## acknowledgements

plural learns from [pi](https://github.com/badlogic/pi-mono), [opencode](https://github.com/sst/opencode), [hermes](https://github.com/NousResearch/hermes-agent) and [herdr](https://github.com/herdrdev/herdr).

## license

plural is licensed under the [apache license 2.0](LICENSE).
