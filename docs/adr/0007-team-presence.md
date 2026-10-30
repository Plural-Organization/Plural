# ADR 0007: team presence

Status: accepted.

## Context

Everyone runs their own host with their own agent and API key. A team wants to see each other's live
sessions, open one to read the whole conversation, and ask for the right to write, without sending links
around. The relay is deliberately dumb: it routes frames, never decides permissions and never stores content
(ADR 0001, threat model). Whatever we add must keep that.

## Decision

- **Identity.** Every person has a long-lived ed25519 key in the local data folder. No accounts.
- **Team.** A team has a signing key held by the directory, a relay URL and a list of members. `plural team
  create` makes it and prints a one-time invite code with a short lifetime. `plural team join <code>` sends
  the code and the person's public key and receives a **member certificate**: team id, public key, name,
  issue and expiry time, signed with the team key. Certificates are renewed before they expire and revoked by
  removing the member.
- **Directory.** A module of the relay application. It stores teams, members and invite codes in SQLite and
  live session cards in memory with a time to live. It answers only requests that carry a valid certificate
  and a signature over a fresh nonce. It never sees prompts, replies or files.
- **Session card.** A host that runs with `--team` publishes a card: room, owner, repository name, branch,
  title, status, number of viewers, the files its agent changed lately, and a list of endpoints (relay,
  tunnel, LAN). The host refreshes it every 20 seconds, the directory drops it after 60. Sessions are
  `private` by default and are not published.
- **Joining.** `plural join @name` and a click on a session in the side panel ask the directory for the
  card, try its endpoints in turn and send `session.hello` with the certificate and a signature. The host
  verifies both against the team key it pinned at `team join`, then admits the person as a **viewer** at
  once. The token is the usual host-signed capability. A host may require a certificate for every join to a
  team session.
- **Writing.** A viewer sends `access.request`. Only the host answers it. Approval turns the viewer into a
  participant, rejection or a later revoke turns them back. Their prompts are shown with their name, as
  today.
- **Conflicts.** The directory compares the changed files of cards that share a repository and tells both
  hosts. The warning shows on the card, in the status line and on the approval card of an edit that touches
  a file someone else's agent changed. Nothing is blocked and nothing is added to a prompt.
- **Context sharing.** A host produces a summary of its session on request and with its owner's consent. It
  travels over the session connection, never through the directory, and the receiving agent gets it as
  untrusted notes under the same rules as a compaction summary (ADR 0003). The system prompt does not change.

## Consequences

- The relay gains state (a SQLite file), so a team relay needs a volume.
- Presence needs a relay URL even when sessions run over a tunnel or LAN. Over a tunnel the viewer talks to
  the host directly and the relay sees only cards.
- The directory holds the team key: a compromised directory can add members. They get viewer access to
  sessions that allow it, never write access, and every grant of writing still goes through the host. A
  later version can have the owner sign certificates.
- Paths of changed files are visible to every team member for `team` sessions.
- A team session is readable by the whole team. `private` stays the default and the interface says which one
  a session is.
