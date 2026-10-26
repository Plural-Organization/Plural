# ADR 0005: TypeScript client, Python host

Status: accepted. The rendering part (Ink, inline mode) is superseded by ADR 0006.

## Context

The terminal client is a Textual app. Textual draws on the alternate screen, so the transcript is not
part of the terminal's scrollback: the user cannot scroll, search or copy it with the terminal's own
tools, and nothing stays on screen after the client exits. The reference tools (Claude Code, Herdr) feel
native because they write finished output into the normal scrollback and redraw only a small live area.

The web client is TypeScript and needs the same protocol client, reducer and presenter as the terminal
client. Keeping a Python terminal client means maintaining that logic in two languages for no benefit.

The host is different: it spawns processes, owns the workspace sandbox, SQLite and the provider SDKs, and
has 199 tests. Rewriting it would cost months and gain nothing the user can see.

## Decision

- The terminal client and the web client are TypeScript. The host stays Python.
- The WebSocket protocol is the only contract between them. TypeScript types are generated from
  `schema.json`. The host announces a protocol version in `session.welcome`, and a client refuses an
  incompatible host with a clear message.
- A shared package, `@plural/client`, holds the connection with reconnect, the reducer, the projection and
  the presenter. The terminal UI and the web UI both build on it.
- The terminal UI uses Ink (React for terminals) in inline mode, with no alternate screen.
  - Finished messages are written once into the terminal's scrollback (`Static`).
  - The live area (the streaming reply, running tools, the composer, the status line) is bounded by the
    terminal height.
  - A streaming reply is committed paragraph by paragraph, and line by line when the live area would
    exceed the viewport.
- The client is shipped as a single binary built with `bun build --compile`, so users need neither Node nor
  Bun. `plural` starts a local host as a child process unless it is given a link.
- The Python reducer stays the reference. Golden fixtures generated from it are replayed by the TypeScript
  tests, so the two implementations cannot drift unnoticed.
- The Python `tui`, `presenter` and `slash` modules and the interactive `join` are removed after the
  TypeScript client reaches parity. A thin Python client stays as test infrastructure.

## Spike results

Ink 8.0.0, React 19.3.1, Bun 1.4.4, 100x40 terminal, a 600-token streaming reply, measured through a PTY
with a terminal emulator.

| measurement | result |
|---|---|
| live reply taller than the viewport (1200 tokens) | 1.45 MB written, 12 126 scrollback lines, 242 copies of one reply |
| same reply committed paragraph by paragraph | 0.30 MB, 61 cards, no duplicates |
| streaming cost with a bounded live area | about 3 KB written per update |
| first paint, Node (tsx) / Bun, empty history | 0.41 s / 0.15 s |
| first paint, Bun-compiled binary | 0.05 s warm (about 1.2 s on the first launch, the OS scans an unsigned binary) |
| printing 5000 history cards on connect | about 1 s and 1 MB, so connect prints only the latest part |
| compiled binary | 87 MB, 39 MB gzipped, per platform |

An Ink app whose live area outgrows the viewport repaints the whole area into the scrollback on every
update. The commit rule above is therefore a requirement, not an optimisation.

## Consequences

- Native selection, copy, search and scrollback in any terminal, and the transcript survives exit.
- Selection belongs to the terminal in inline mode, so the client cannot copy on select by itself. Terminals
  that offer it (iTerm2, Ghostty, kitty, WezTerm) do it with their own copy-on-select setting. The client
  adds explicit copy commands for the last reply and for code blocks.
- One TypeScript client stack for terminal and web; one presenter.
- Two runtimes to install. `install.sh` installs uv with the Python host and downloads the client binary
  for the platform.
- Binaries are large (about 39 MB per download). Accepted for now; revisit if downloads matter.
- Compiling Ink needs the optional `react-devtools-core` package present, otherwise the build fails.
- Releases build binaries for macOS (arm64, x64) and Linux (x64, arm64). Windows is supported through WSL.
- The reducer exists twice by necessity (host and client); golden fixtures guard it.
- New dependencies: the npm toolchain, Ink, React, Bun (build only).

## Rejected

- Staying on Textual: alternate screen, no native scrollback.
- OpenTUI: pre-1.0 (0.7.0), Bun only, fullscreen model.
- Rewriting the host in TypeScript: months of work and the loss of the Python provider SDK ecosystem for no
  visible gain.

## Rollout

0. This ADR and the spike.
1. `@plural/client`: generated types, connection, reducer, presenter, golden fixtures, protocol version.
2. Terminal UI on Ink: message cards, Markdown with code highlighting, diffs, collapsible tool output,
   approval dialogs, composer with slash completion, participants and proposals, status line, theme.
3. Release pipeline for the binaries and a rewritten `install.sh`.
4. README in the Herdr style and updated docs.
5. Remove the Python terminal UI; restore the web and terminal jobs in CI.
