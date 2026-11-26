# ADR 0019: the host hands its seat to a participant

Status: accepted

## Context

The host is the computer the agent runs on, so a session ends when its host goes: the person closes the
laptop, and the conversation everyone was in is gone. ADR 0018 let a second person answer approvals, which
helps while the host's computer is on. It does not help when the host leaves.

A host who knows it is leaving can hand the seat to someone else in the room, and the others should find
the same room, the same link and the same conversation, now run from another computer.

## Decision

The host offers its seat to a connected participant who can write, and the participant takes it on their
own computer. The old host stops, and is a participant in the room it hosted.

1. `host.handover_offer { participant_id }` (host only) puts an offer in the room: `SessionState.handover`.
   An unanswered offer lapses after five minutes. Only a session on a relay can be offered: a direct
   address cannot move, and a team session stays with the team's host.
2. The person it is offered to starts a host on their computer (`plural-host host --takeover <their link>`,
   which the terminal client does when they press `y`). It answers with `host.handover_answer`, naming a
   key to seal the session to and the key its host will use. The old host is **frozen** from here: it takes
   no prompt, command, compaction or fork, so the log it hands over is the whole of it. It still answers
   approvals and can abort a run.
3. The successor fetches the session in parts (`host.handover_fetch`). The old host packs it when its agent
   is idle: a consistent copy of the event log, the attached files and a manifest, in one tarball
   (`storage/handover.py`), **sealed** to the successor's key (X25519, HKDF, ChaCha20-Poly1305,
   `security/seal.py`) so the relay that carries the parts cannot read them. The parts are not events and
   are never stored in the log.
4. The successor unpacks and checks it (a hash of the log, a manifest for this room and for this person, a
   tarball that holds only what a pack holds), starts a host from it and says `host.handover_ready`. The
   old host answers with **its signed word** (`SuccessionClaims`): the room, its own key, the successor's
   key, the last event, and two minutes to live.
5. The successor opens the room on the relay with that word. The relay believes it only from the room's
   current key, for that successor and that room, and only while it is fresh; it then gives the room to the
   new key, closes the old host with its own code (4411) and sends the guests back (4410). The old host
   stops; the room's link is unchanged because a room is named by its id, not by a host. If the word is not
   taken up in time, the old host takes its seat back and writes `host.handover_ended`.
6. The new host's first act is `host.handed_over`. The seat, `p_host`, is the successor's; the old host
   becomes a participant under a new id; what each wrote stays theirs (the reducer moves authorship, in the
   host and in the client, and both are held to the same golden fixtures).
7. Tokens the old host signed stay good until they expire: the new host trusts the old key for them. A token
   for `p_host` that the old key signed means the old host as a participant, never the new host.

## Consequences

- The relay is the arbiter: only one key holds a room, and it moves only on the holder's word. A host that
  tried to keep working would find the relay refusing it, so the log cannot fork.
- After a handover the session is **asked more**. What the first host wrote is, to the second, what a guest
  wrote, so the agent counts every run as guest-originated, as after a briefing (ADR 0004's taint): writing
  and running anything asks the new host, in auto mode too, also after a restart (`SessionState.handovers`).
- The new host uses its own model key, its own plugins and MCP servers, and works in its own folder. The
  manifest carries where the old host's code was (repository, branch, commit, how many files were dirty) and
  the new host's folder is **not** changed: moving someone's working tree silently is not a thing a handover
  may do.
- It needs the old host to be there. A host that closes its laptop without warning cannot hand anything
  over; that needs a standby that keeps a copy of the log, which is a later decision.
- A browser cannot take a seat, because the agent has to run on a computer; the web client shows the offer
  and sends the person to the terminal.
