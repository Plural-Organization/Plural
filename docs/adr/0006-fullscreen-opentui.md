# ADR 0006: full-screen terminal UI on OpenTUI

Status: accepted. Supersedes the rendering part of ADR 0005; the rest of ADR 0005 (TypeScript client,
Python host, shared `@plural/client`, one binary built with Bun) stands.

## Context

ADR 0005 chose Ink in inline mode so the transcript would live in the terminal's own scrollback. The
Ink client works, but it cannot show anything beside the transcript. A shared session needs presence and
coordination on screen all the time: who is in the room, who is typing, what waits for the host, what is
queued. The reference tools for this product (OpenCode, Herdr) are full-screen applications with a side
panel, their own scrolling and their own text selection that copies on release.

Ink in full-screen mode (`alternateScreen`) would leave us to write scrolling, virtualisation, selection and
mouse handling ourselves. OpenTUI provides them: a native renderer in Zig with TypeScript and React
bindings, a scroll box that sticks to the bottom and culls off-screen content, a streaming Markdown
renderable, tables, diffs, a multi-line text area, text selection and OSC 52 clipboard access. OpenCode runs
on it in production.

## Decision

- The terminal UI is full-screen and built on OpenTUI (`@opentui/core` and `@opentui/react`), pinned to an
  exact version.
- Layout: the transcript with a composer and status line on the left, a side panel on the right with the
  participants, what waits for the host, the prompt queue and the session summary. The panel can be hidden.
- The transcript scrolls inside the application (mouse wheel, page keys). Selecting text copies it to the
  clipboard on release. The terminal's own selection remains available through its mouse-bypass modifier.
- Everything that is not drawing stays: the feed model, the composer editor, commands, the host process
  launcher and `@plural/client`.
- Code blocks are highlighted with our own highlighter through a custom code-block renderer, so the result
  does not depend on tree-sitter grammars being present at run time.
- The binary is still built with `bun build --compile`. All platform packages of the native core must be
  installed at build time for cross-compilation.

## Consequences

- A persistent side panel and room for more panels (team chat, live command output, attributed changes).
- No terminal scrollback, terminal search or on-screen history after exit. The session log keeps the
  history, `plural-host export` dumps it, and `/copy` copies the last reply.
- The renderer is pre-1.0 (0.7.0) and Bun only. The version is pinned and upgrades are deliberate.
- Binary size grows to about 97 MB (about 40 MB gzipped).
- The inline Ink client is removed once the OpenTUI client reaches parity.
