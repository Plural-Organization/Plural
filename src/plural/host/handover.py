"""What the host holds while it hands its seat to a participant (ADR 0019).

The steps, in the order the successor takes them: it accepts and names a key to seal the session
to and the key its host will use; it fetches the session in parts, which makes the host pack it
once the agent is idle; it unpacks and checks it and says it is ready; the host signs its word
that the successor's key holds the room. The relay does the rest, and this host finds it has been
displaced. Until then the host is only frozen: it answers approvals and can abort a run, but takes
no new work, so the log the successor holds is the whole of it."""

import asyncio
import base64
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Final

from plural.core.errors import Conflict, Invalid
from plural.core.ports import Clock, EventStore, IdGenerator
from plural.host.repo import git_dirty, git_head, repo_facts
from plural.protocol.capability import SuccessionClaims
from plural.protocol.events import HostHandoverChunk, HostHandoverGrant
from plural.protocol.models import HOST_PARTICIPANT_ID, SessionState
from plural.security.seal import seal
from plural.security.succession import STATEMENT_TTL, sign_succession
from plural.security.tokens import TokenSigner
from plural.storage.handover import HandoverManifest, RepoNote, pack

# Raw bytes in a part: base64 grows it a third, and a message holds at most 4 MB.
CHUNK_BYTES: Final = 1024 * 1024
# How long an offer waits for its answer before the host takes it back.
OFFER_TTL: Final = timedelta(minutes=5)
# After the host signs its word, how long it waits to be displaced before it goes on as the host.
GRANT_PATIENCE: Final = STATEMENT_TTL + timedelta(seconds=5)


class HandedAway(Exception):
    """This host's room is another host's now. It is not an error: the process ends quietly."""


@dataclass(slots=True)
class Transfer:
    participant_id: str
    seal_key: str | None = None
    host_key: str | None = None
    parts: list[bytes] | None = None
    last_seq: int = 0
    granted: bool = False
    # The sealed bytes are kept as parts; this is only to say how many bytes went.
    size: int = field(default=0)


class HandoverDesk:
    def __init__(
        self,
        *,
        room: str,
        signer: TokenSigner,
        data_dir: Path | None,
        workspace: Path,
        ids: IdGenerator,
        clock: Clock,
        allowed: bool,
    ) -> None:
        self._room = room
        self._signer = signer
        self._data_dir = data_dir
        self._workspace = workspace
        self._ids = ids
        self._clock = clock
        self._allowed = allowed
        self._transfer: Transfer | None = None

    def require_allowed(self) -> None:
        if not self._allowed or self._data_dir is None:
            raise Conflict(
                "this session cannot be handed over: it needs a relay, and a team session "
                "stays with the team's host"
            )

    @property
    def frozen(self) -> bool:
        """The successor has accepted: from here no new work starts on this host."""
        return self._transfer is not None and self._transfer.host_key is not None

    @property
    def granted(self) -> bool:
        return self._transfer is not None and self._transfer.granted

    @property
    def packed(self) -> bool:
        return self._transfer is not None and self._transfer.parts is not None

    def begin(self, participant_id: str) -> None:
        self._transfer = Transfer(participant_id)

    def accept(self, *, seal_key: str | None, host_key: str | None) -> None:
        if self._transfer is None:
            raise Conflict("nobody is being handed the host")
        if seal_key is None or host_key is None:
            raise Invalid("accepting needs a key to seal the session to and your host key")
        self._transfer.seal_key, self._transfer.host_key = seal_key, host_key

    def reset(self) -> None:
        self._transfer = None

    async def part(self, state: SessionState, store: EventStore, index: int) -> HostHandoverChunk:
        transfer = self._accepted()
        if transfer.parts is None:
            if state.run is not None:
                raise Conflict("the agent is working; the session is packed when it is idle")
            await self._pack(transfer, state, store)
        parts = transfer.parts or []
        if index >= len(parts):
            raise Invalid(f"there is no part {index}; the session has {len(parts)}")
        return HostHandoverChunk(
            part=index, parts=len(parts), data_b64=base64.b64encode(parts[index]).decode()
        )

    def grant(self) -> HostHandoverGrant:
        transfer = self._accepted()
        if transfer.parts is None or transfer.host_key is None:
            raise Conflict("fetch the session first")
        now = self._clock.now()
        claims = SuccessionClaims(
            room=self._room,
            from_key=self._signer.verifier.public_b64(),
            to_key=transfer.host_key,
            last_seq=transfer.last_seq,
            iat=now,
            exp=now + STATEMENT_TTL,
        )
        transfer.granted = True
        return HostHandoverGrant(statement=sign_succession(self._signer, claims))

    def _accepted(self) -> Transfer:
        if self._transfer is None or not self.frozen:
            raise Conflict("the offer has not been accepted")
        return self._transfer

    async def _pack(self, transfer: Transfer, state: SessionState, store: EventStore) -> None:
        if self._data_dir is None or transfer.seal_key is None:
            raise Conflict("this host cannot pack a session")
        successor = state.participants.get(transfer.participant_id)
        if successor is None:
            raise Conflict("the person taking the host over has left the room")
        former = state.participants.get(HOST_PARTICIPANT_ID)
        facts = await repo_facts(self._workspace)
        transfer.last_seq = await store.last_seq()
        manifest = HandoverManifest(
            room=self._room,
            last_seq=transfer.last_seq,
            host_key=self._signer.verifier.public_b64(),
            host_name=former.name if former else "host",
            former_host_id=self._ids.new("p_"),
            successor_id=successor.id,
            successor_name=successor.name,
            created_at=self._clock.now(),
            database_sha256="",
            repo=RepoNote(
                repo_id=facts.repo_id,
                branch=facts.branch,
                head=await git_head(self._workspace),
                dirty=await git_dirty(self._workspace),
            ),
        )
        blob = await asyncio.to_thread(pack, self._data_dir, manifest)
        sealed = await asyncio.to_thread(seal, transfer.seal_key, blob)
        transfer.size = len(sealed)
        transfer.parts = [
            sealed[at : at + CHUNK_BYTES] for at in range(0, len(sealed), CHUNK_BYTES)
        ] or [b""]
