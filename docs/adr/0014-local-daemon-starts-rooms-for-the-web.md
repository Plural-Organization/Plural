# ADR 0014: a local daemon starts rooms for the web client

Status: proposed. Slice 0 (a browser experiment) must confirm the transport before the rest is built.

## Context

The web client can sign a person in and link a computer to the account, but a host is still started
from a terminal: a browser cannot run a process, choose a folder or hold the host's key. We want
"Start a room" in the web client to start a host on the person's own computer, in a folder they choose,
and open the room.

The pieces already exist. `plural-host host --json --workspace <dir>` starts a host without a terminal,
prints one `ready` line with the room, guest link and host link, and stops when its stdin closes. The
TUI starts hosts that way. `plural login` leaves the computer's certificate and key in the data
directory (ADR 0013). What is missing is something on the computer the browser can talk to.

## Decision

A small **daemon**, `plural daemon`, listens on the loopback interface only and starts and stops hosts
on request. It starts nothing by itself and holds no state a host does not already hold.

- **Transport.** HTTP on `127.0.0.1` at a fixed port (default 47831, `PLURAL_DAEMON_PORT`), never on
  another interface. The web client at `https://plrl.host` calls it with `fetch`. Browsers differ in
  how they treat a public page calling loopback (Private Network Access preflights, Chrome's local
  network permission, Safari's mixed-content blocking), so slice 0 tests Chrome, Firefox and Safari
  before anything else is built, and the fallback below exists if one cannot be supported.
- **Who may call it** is decided by three checks on every request, each refusing on its own:
  1. `Host` must be `127.0.0.1:<port>` or `localhost:<port>`, so a name that resolves to loopback
     later (DNS rebinding) is refused.
  2. `Origin` must be one of the configured web origins (default `https://plrl.host` and
     `https://www.plrl.host`). The answer carries CORS headers for that origin only, and answers a
     Private Network Access preflight. A request with no `Origin` (curl, another program) gets only
     `GET /v1/status`, which says nothing about the person.
  3. A **ticket** proves the account. The browser asks the accounts service for one
     (`POST /tickets`, with its session cookie) and sends it as `Authorization: Bearer`. A ticket is
     `base64url(claims).base64url(signature)` signed with the same key as certificates, with
     `aud: "daemon"`, the account, a nonce and a 60 second life. The daemon checks it offline with the
     accounts public key and requires `account` to equal the account in its own certificate. A page
     that is not signed in as this computer's account cannot start anything, even from an allowed
     origin.
- **Folders.** The browser never sends a path. `POST /v1/folders/pick` opens the operating system's own
  folder dialog on the computer and returns an opaque `folder` id for the one the person chose. A room
  can only be started in a folder picked this way. macOS uses `osascript`, Linux `zenity` or
  `kdialog`, Windows PowerShell; with none of them the daemon says so and the web client shows a field
  to start from the terminal instead.
- **Rooms.** `POST /v1/rooms {folder, title?}` starts `plural-host host --json --workspace <folder>`
  as a child, waits for its `ready` line and returns `{room, guest_link, host_link}`. `GET /v1/rooms`
  lists the rooms the daemon started; `DELETE /v1/rooms/{room}` closes the child's stdin. When the
  daemon stops, its hosts stop. At most 5 rooms at once.
- **No account, no daemon.** `plural daemon` refuses to start without a certificate from
  `plural login`; it renews the certificate the way a host does.
- **Starting it.** `plural daemon` runs in the foreground. A launch agent (macOS) and a user service
  (Linux) that keep it running are a later slice and are never installed without the person asking.

## Fallback

If a browser cannot call loopback, the web client keeps its current flow: it shows the command and
the person starts the host in a terminal. Nothing else in this ADR depends on that flow changing.

## Consequences

- Anything on the computer can reach the port, so the checks above protect against web pages, not
  against another program run by the same person. Such a program can already start hosts itself.
- The daemon widens the surface of one open port per computer. It accepts no file contents, no paths
  and no commands from the browser: it starts the Plural host in a folder the person clicked.
- Tickets bind a web session to this computer's account for a minute; they do not make the page
  trustworthy, which is why the origin and the folder dialog stay.
- The accounts service gains one endpoint (`POST /tickets`), and the web client one client for the
  daemon. The relay is untouched.

## Plan

| slice | what | where |
|---|---|---|
| 0 | browser experiment: a page on a public origin calling a loopback server in Chrome, Firefox and Safari, with the preflight headers; result recorded here | scratch, then this ADR |
| 1 | accounts: `POST /tickets` and its tests | accounts repo |
| 2 | daemon core: loopback server, host/origin/ticket checks, `GET /v1/status`, `plural daemon` | `src/plural/daemon/`, `cli/` |
| 3 | folder dialog on macOS, Linux and Windows, behind one interface | `src/plural/daemon/folders.py` |
| 4 | rooms: start, list, stop, limits, shutdown with the daemon | `src/plural/daemon/rooms.py` |
| 5 | web client: find the daemon, "Start a room", folder choice, open the room; fallback when it is absent | `web/` |
| 6 | docs, threat model, `plural daemon` in the TUI passthrough, install notes | `docs/`, `tui/` |
| 7 | later: keep it running at login, relay refusing hosts without a certificate | separate decisions |
