# ADR 0016: teams belong to accounts, and the web client manages them

Status: accepted.

## Context

Teams (ADR 0007) live in a directory on the relay. A member is an ed25519 key: `plural team create`
or `join` sends a key and gets back a member certificate for it. That worked while every person had
one terminal client. Since then:

- **A person has several keys.** The web client makes its own key in each browser (IndexedDB) and
  the computer has `identity.pem`. The same person who joined from the terminal is a stranger in the
  browser and has to join again, and shows up twice in the member list.
- **One team per place.** The browser keeps one team profile, the computer one `team.json`.
  `plural team join` and the web client refuse a second team.
- **The web client can only join.** Creating a team, inviting, seeing members, removing someone or
  disbanding happens in the terminal.
- **Rooms started from the web are never team rooms.** The daemon (ADR 0014) starts hosts without
  `--team`, and the computer's membership is separate from the browser's.
- **People now have accounts.** A computer is bound to an account by a certificate (ADR 0013), and a
  browser session can prove its account with a ticket (ADR 0014). Nothing about teams uses that yet.

We want, in the web client: create a team, invite people, see and manage members, belong to more
than one team and switch between them, leave or disband, and show a room to a team. And one person
should be one member whatever device they use.

## Decision

**A member is an account when the relay knows the accounts service, and a key otherwise.**

- **Directory stays on the relay.** Teams, members and invites stay in the relay's SQLite, as today.
  A self-hosted relay keeps working without any accounts service, so teams never depend on ours.
- **Account members.** A relay started with `--accounts-url` (it already reads the accounts key for
  the entitlement gate) also accepts account proofs for teams:
  - a browser sends a **ticket** with a new audience, `aud: "teams"` (the accounts service signs it
    on `POST /tickets {aud}`; a `daemon` ticket is refused here and a `teams` ticket by the daemon);
  - a computer sends its **entitlement certificate** with a signature by its host key, the way it
    already opens rooms.
  The directory checks either offline with the accounts key, then treats `account` as the member.
- **Several keys per member.** A member row gains `account` (nullable) and its keys move to a
  `member_keys` table. Each device asks for a member certificate for its own key; the certificate
  format (team, member, key, name, role, iat, exp) does not change, so hosts and the room protocol
  keep verifying it as before. A key-only member is a member with one key and no account.
- **My teams.** `POST /teams/mine` with an account proof and the device's public key returns every
  team the account is in, each with a fresh member certificate for that key. A new browser or
  computer gets all its teams by signing in, with no invite.
- **Create, join, manage.** `POST /teams` and `POST /teams/join` accept an account proof instead of a
  bare key. Members, invite, remove, renew and disband keep their signed-request API (ADR 0007).
  Limits count per account when there is one: at most 3 owned teams, 50 members.
- **Claiming.** A key-only member who later joins the same team with an account proof is linked to
  it instead of added twice, when the proof is signed by a key the member already has.
- **Owners.** An owner can hand ownership to another member (`POST /teams/{id}/owner`), and then
  leave. Disbanding stays owner-only.

**The web client holds several teams and switches between them.**

- **Storage.** IndexedDB keeps one profile per team (`team:<id>`), plus the browser key. The single
  `team` profile of today is migrated on first load.
- **Switcher.** The rail shows the current space: "Rooms you joined" or one of the teams. A HeroUI
  `Dropdown` lists every team with its live session count, "Create a team" and "Join with an invite".
- **Team window.** One HeroUI `Modal` with tabs: Members (role, remove, make owner), Invite (link to
  copy, new code), Settings (rename, leave, disband with an `AlertDialog`).
- **Signed in or not.** Signed in on a relay with accounts, the client uses account proofs and
  `/teams/mine`. Without an account, or on a relay without accounts, it keeps today's key flow, so
  invites to self-hosted relays still work.

**Rooms the web starts can be team rooms.**

- **Computer teams.** The computer keeps one profile per team (`teams/<id>.json` beside the old
  `team.json`, which is migrated), and `plural-host host --team <id>` picks one. Linked to an
  account, the computer gets them from `/teams/mine`, so it never joins separately.
- **Daemon.** `GET /v1/teams` lists the computer's teams, and `POST /v1/rooms` takes `team`. Start a
  room gets a "Show to" choice: only people I invite, or a team.
- **Showing a running room** to a team is a later step (a `team.show` control request), not part of
  this decision.

## Consequences

- One person is one member on every device signed in to the same account, and a new device gets
  its teams by signing in.
- The relay learns which account each member is, as the entitlement gate already does. It still
  never sees prompts, replies or files.
- Teams on our relay start to depend on the accounts service being reachable for create, join and
  `/teams/mine`; certificates already issued keep working while it is down, as ADR 0013 does for
  rooms.
- Key-only teams on self-hosted relays are unchanged, and a team can mix both kinds of members.
- The directory still holds each team's signing key (ADR 0007): a compromised relay can still add
  members. Owner-signed certificates remain a later step.

## Rejected

- **Teams in the accounts service.** One central list would be simpler for us, but every team would
  depend on our service and a self-hosted relay would lose teams.
- **Keep keys only, add a device-linking code.** It fixes duplicate members with a manual step per
  device, while accounts already prove who a device belongs to.

## Plan

| slice | what | where |
|---|---|---|
| 1 | tickets with an audience: `POST /tickets {aud: "daemon" \| "teams"}` | accounts, `protocol/ticket.py` |
| 2 | directory: account proofs, `member_keys`, `/teams/mine`, claiming, owner hand-over, migration | `relay/directory.py`, `protocol/team.py` |
| 3 | client library: account-proof create, join and mine | `client/src/team` |
| 4 | web: several teams in IndexedDB, switcher, create, team window | `web/` |
| 5 | computer: per-team profiles, `--team <id>`, `/teams/mine` from the certificate; daemon `/v1/teams` and `team` on rooms; "Show to" in Start a room | `host/team.py`, `daemon/`, `web/` |
| 6 | terminal client: switch teams, create with an account | `tui/` |
| 7 | later: show a running room to a team, owner-signed certificates | separate decisions |

Slices 1 to 4 give the web client full team management; slice 5 connects rooms to it.

## Built

Slice 2: `relay/directory.py` (account members, `member_keys` with a migration of existing members,
`mine`, claiming a key-only member with a signature by its key, `hand_over`, owner checks read the
role from the directory), `relay/account_proofs.py`, routes `POST /teams/mine` and
`POST /teams/{id}/owner`. A ticket's audience is checked by `EntitlementVerifier.ticket`.

A claim needs more than the ADR first said: a signature by the member's key over the invite code
(`key_proof`), since a public key alone proves nothing.
