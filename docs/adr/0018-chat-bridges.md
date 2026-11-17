# ADR 0018: sessions in chat apps through a bridge

Status: accepted for Telegram; Slack is next.

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
