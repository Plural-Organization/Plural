"""The new host's side of a handover (ADR 0019): join the room as the person who was offered the
host, take the session, and come up as the host of the same room.

`plural-host host --takeover <link>` runs it. `receive` answers the offer and brings the session
here, `finish` waits for the old host's word that this host's key holds the room, and then the
host serves as usual: its first act with the relay is to show that word."""

import asyncio
import base64
import json
import sqlite3
from collections.abc import Callable
from contextlib import suppress
from time import monotonic

from plural import __version__
from plural.client.connection import CommandRejected
from plural.client.reconnect import JoinLink, SessionClient
from plural.host.bootstrap import Host
from plural.host.config import HostSettings
from plural.host.repo import git_head, repo_facts
from plural.host.transport.relay_link import RelayLink
from plural.protocol.commands import (
    ClientInfo,
    HostHandoverAnswer,
    HostHandoverFetch,
    HostHandoverReady,
)
from plural.protocol.envelope import ErrorCode
from plural.protocol.events import (
    HostHandedOver,
    HostHandoverChunk,
    HostHandoverEnded,
    HostHandoverGrant,
    SessionSnapshot,
)
from plural.security.keys import load_or_create_host_key
from plural.security.seal import SealError, SealKey
from plural.security.tokens import TokenSigner
from plural.storage.handover import HandoverError, HandoverManifest, unpack
from plural.storage.sessions import delete_session, session_path

CLIENT = ClientInfo(kind="takeover", version=__version__)
# The old host packs the session when its agent is idle: wait that long for it.
BUSY_PATIENCE_S = 600.0
POLL_S = 1.0
STEP_TIMEOUT_S = 30.0


class TakeoverError(Exception):
    pass


class Takeover:
    def __init__(
        self,
        link: str,
        settings: HostSettings,
        *,
        notice: Callable[[str], None] = lambda _: None,
    ) -> None:
        try:
            self._link = JoinLink.parse(link)
        except ValueError as error:
            raise TakeoverError(f"not a room link: {error}") from error
        if self._link.token is None:
            raise TakeoverError("the link must carry your own token, as the one the client shows")
        self._settings = settings
        self._notice = notice
        self._client = SessionClient(self._link, name=settings.host_name, client=CLIENT)
        self._reader: asyncio.Task[None] | None = None
        self._changed = asyncio.Condition()
        self._chunks: dict[int, HostHandoverChunk] = {}
        self._grant: HostHandoverGrant | None = None
        self._ended: HostHandoverEnded | None = None
        self._snapshot = False
        self._failure: BaseException | None = None
        self.manifest: HandoverManifest | None = None
        # What this person should know before the agent works here: the folder is not the old one.
        self.notes: list[str] = []

    async def receive(self) -> HostSettings:
        """Answers the offer, brings the session here and returns the settings to host it with."""
        self._reader = asyncio.create_task(self._read())
        await self._until(lambda: self._snapshot)
        projection = self._client.projection
        me, offer = projection.me, projection.state.handover
        if me is None or offer is None or offer.participant_id != me.id:
            raise TakeoverError("nobody has offered you the host of this room")
        self._notice(f"taking over the host of room {self._link.room} as {me.name}")
        seal = SealKey()
        signer = TokenSigner(
            await asyncio.to_thread(load_or_create_host_key, self._settings.state_dir / "host_key")
        )
        await self._send(
            HostHandoverAnswer(
                accept=True,
                seal_key=seal.public_b64,
                host_key=signer.verifier.public_b64(),
            )
        )
        first = await self._fetch(0)
        parts = [first]
        for index in range(1, first.parts):
            parts.append(await self._fetch(index))
        blob = b"".join(base64.b64decode(part.data_b64) for part in parts)
        try:
            plain = seal.open(blob)
            manifest = await asyncio.to_thread(unpack, self._settings.state_dir, plain)
        except (SealError, HandoverError) as error:
            raise TakeoverError(str(error)) from error
        try:
            self._check(manifest, me.id)
            await asyncio.to_thread(self._remember, manifest, me.name)
        except BaseException:
            await asyncio.to_thread(delete_session, self._settings.state_dir, manifest.room)
            raise
        self.manifest = manifest
        self.notes = await self.compare(manifest)
        relay = self._link.url.removesuffix(f"/{self._link.room}")
        return self._settings.model_copy(
            update={"room": manifest.room, "relay_url": relay, "host_name": me.name}
        )

    async def finish(self, host: Host) -> None:
        """Says the session is here, takes the old host's word and hands it to the relay."""
        if not isinstance(host.transport, RelayLink):
            raise TakeoverError("a room is handed over through a relay")
        await self._send(HostHandoverReady())
        await self._until(lambda: self._grant is not None or self._ended is not None)
        if self._grant is None:
            raise TakeoverError("the handover was called off")
        host.transport.succeed_with(self._grant.statement)
        await self.close()

    async def close(self) -> None:
        if self._reader is not None:
            self._reader.cancel()
            with suppress(asyncio.CancelledError, CommandRejected):
                await self._reader
            self._reader = None

    async def compare(self, manifest: HandoverManifest) -> list[str]:
        """How this folder differs from where the old host's agent worked. It is never changed."""
        was, here = manifest.repo, await repo_facts(self._settings.workspace)
        head = await git_head(self._settings.workspace)
        notes: list[str] = []
        if was.repo_id is not None and here.repo_id != was.repo_id:
            where = here.repo_id or "no git repository"
            notes.append(f"this folder is {where}, the session was in {was.repo_id}")
        elif was.head is not None and head != was.head:
            notes.append(
                f"the session was on commit {was.head} ({was.branch}), this folder is at "
                f"{head or 'no commit'}: check out the same one first"
            )
        if was.dirty:
            notes.append(
                f"the old host had {was.dirty} uncommitted change(s) that did not come along"
            )
        return notes

    def _check(self, manifest: HandoverManifest, me_id: str) -> None:
        if manifest.room != self._link.room:
            raise TakeoverError("the session that arrived is for another room")
        if manifest.successor_id != me_id:
            raise TakeoverError("the session that arrived is for someone else")

    def _remember(self, manifest: HandoverManifest, name: str) -> None:
        """What the host that starts from this log needs and the log does not say."""
        path = session_path(self._settings.state_dir, manifest.room)
        db = sqlite3.connect(path)
        try:
            row = db.execute("SELECT value FROM meta WHERE key = 'previous_hosts'").fetchone()
            known: dict[str, str] = json.loads(row[0]) if row else {}
            known[manifest.host_key] = manifest.former_host_id
            pending = HostHandedOver(
                former_host_id=manifest.former_host_id,
                former_host_name=manifest.host_name,
                participant_id=manifest.successor_id,
                name=name,
            )
            db.executemany(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                [
                    ("previous_hosts", json.dumps(known)),
                    ("handover_pending", pending.model_dump_json()),
                ],
            )
            db.commit()
        finally:
            db.close()

    async def _fetch(self, part: int) -> HostHandoverChunk:
        deadline = monotonic() + BUSY_PATIENCE_S
        while True:
            try:
                await self._client.send(HostHandoverFetch(part=part))
                break
            except CommandRejected as error:
                if error.error.code is not ErrorCode.CONFLICT or monotonic() > deadline:
                    raise TakeoverError(error.error.message) from error
                self._notice(error.error.message)
                await asyncio.sleep(POLL_S)
        await self._until(lambda: part in self._chunks)
        return self._chunks[part]

    async def _send(self, command: HostHandoverAnswer | HostHandoverReady) -> None:
        try:
            await self._client.send(command)
        except CommandRejected as error:
            raise TakeoverError(error.error.message) from error

    async def _until(self, ready: Callable[[], bool]) -> None:
        async def wait() -> None:
            async with self._changed:
                await self._changed.wait_for(lambda: ready() or self._failure is not None)

        try:
            await asyncio.wait_for(wait(), STEP_TIMEOUT_S)
        except TimeoutError as error:
            raise TakeoverError("the old host did not answer in time") from error
        if self._failure is not None and not ready():
            raise TakeoverError(str(self._failure))

    async def _read(self) -> None:
        try:
            async for event in self._client.events():
                async with self._changed:
                    match event:
                        case SessionSnapshot():
                            self._snapshot = True
                        case HostHandoverChunk(part=part):
                            self._chunks[part] = event
                        case HostHandoverGrant():
                            self._grant = event
                        case HostHandoverEnded():
                            self._ended = event
                        case _:
                            pass
                    self._changed.notify_all()
        except CommandRejected as error:
            self._failure = error
        except Exception as error:
            self._failure = error
        async with self._changed:
            self._changed.notify_all()
