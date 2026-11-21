# ADR 0018: sessions in chat apps through a bridge

Status: accepted for Telegram and Discord; Slack is next.

## Context

People want to talk to a session from the chat their team already lives in: tag the bot in a group, see the agent work, and answer what it asks to allow without opening a terminal. Telegram first, Slack and others later, and the same bot for many groups and sessions rather than one bot per session.

## Decision

- **A bridge is a client of the room.** `plural.bridge` joins rooms with the protocol, like the terminal and the web client. It runs on the host's computer (`plural bridge telegram`), needs no server and no port, and an import contract keeps it away from the host's internals. The relay stays as it is.
- **One bot, many places.** A *place* is a chat, or a topic in a chat with topics. A place follows one room; a room can be followed from many places. Links live in `<data dir>/bridge/<platform>.json`.
- **Rooms announce themselves locally.** A host writes `<data dir>/running/<room>.json` (owner-only, with its host link) while it serves and removes it when it stops. The bridge offers these rooms in `/link` and reconnects when a room comes back, so nobody copies a link into a chat.
- **Owners and guests.** Owners pair with a code the bridge prints, from a private chat. Only owners link places, answer approvals and stop runs; the bridge holds the host link and acts as the host only after an owner pressed a button. Anyone else writes through a connection of their own, joined with a participant invite, so the room names them and treats their prompts as a guest's: the guest-turn taint and the gate apply unchanged.
- **Platform-neutral core.** `model.py` describes what is said and shown (`Said`, `Pressed`, `Answer`, `Notice`); `room.py` and `bridge.py` hold every rule; a platform module only translates. Telegram uses rich messages (Bot API 10.1): drafts with a thinking placeholder and stop button in private chats, an edited message in groups, inline buttons with styles for approvals.

## Consequences

- A chat sees everything that happens in the room it follows, whoever asked, and what the agent writes passes through the chat service.
- The bridge runs where the hosts run. A hosted bot for everyone would need delegated approvals the protocol does not have yet.
- Adding Slack means a platform module and its rendering; the room logic and the rules stay.

## Addendum: providers and where they are set up

- **A provider is data.** `bridge/registry.py` describes a service (its fields, which are secret, what to do in the service first) and how to build its `ChatPlatform`; `bridge/providers.py` lists them. Clients render forms from that description and keep no list of their own, the way the agent's presets work.
- **One owner of the settings.** `bridge/service.py` holds the configuration (`<data dir>/bridge/config.json`, owner-only; a secret is written and never read back out) and supervises the bridges. The web client reaches it through the daemon (`/v1/bridges`), the terminal and the command line through `plural-host bridge … --json`. They all write the same file.
- **One runner per computer.** The process that takes `bridge/supervisor.lock` (the daemon, or `plural bridge run`) runs the bridges and publishes their state in `bridge/status.json`; any other process only edits settings and reads that state. The runner reloads the file when it changes, so a change from any place applies in seconds and a token is never read by two bridges.
- **Failures are classified.** A platform raises `AuthError` when the credentials are refused (the bridge stops and says why) and `PlatformError` for anything else (it retries with a growing pause).
- **A turn never blocks another.** The bridge handles each update on its own task, in order within one chat, and a button never waits behind a message, so an approval can be answered while a guest is still joining.
