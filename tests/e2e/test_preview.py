import base64

import pytest

from plural.client.connection import CommandRejected
from plural.host.preview import PreviewFetcher, Resource
from plural.protocol.commands import PreviewFetch, PreviewSet
from plural.protocol.events import PreviewChanged, PreviewData, SessionSnapshot
from plural.protocol.models import Role
from tests.e2e.support import Session


async def test_only_host_shares_and_late_viewers_discover_preview(session: Session) -> None:
    owner = await session.owner()
    guest = await session.guest("Alia")
    with pytest.raises(CommandRejected):
        await guest.client.send(PreviewSet(port=3000))
    await owner.client.send(PreviewSet(port=3000, title="Landing"))
    preview = (await guest.next(PreviewChanged)).preview
    assert preview is not None
    assert (preview.port, preview.title) == (3000, "Landing")
    late = await session.guest("Viewer", Role.VIEWER)
    snapshot = next(event for event in late.events if isinstance(event, SessionSnapshot))
    assert snapshot.state.preview == preview
    await owner.client.send(PreviewSet())
    assert (await guest.next(PreviewChanged)).preview is None
    with pytest.raises(CommandRejected):
        await guest.client.send(PreviewFetch(preview_id=preview.id, request_id="stale"))


async def test_preview_bytes_are_private_to_requester_and_not_logged(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fetch(self: PreviewFetcher, port: int, path: str) -> Resource:
        assert (port, path) == (3000, "/logo.png?v=1")
        return Resource(200, "image/png", b"picture bytes")

    monkeypatch.setattr(PreviewFetcher, "fetch", fetch)
    owner = await session.owner()
    viewer = await session.guest("Viewer", Role.VIEWER)
    await owner.client.send(PreviewSet(port=3000))
    preview = (await viewer.next(PreviewChanged)).preview
    assert preview is not None
    await viewer.client.send(
        PreviewFetch(preview_id=preview.id, request_id="r1", path="/logo.png?v=1")
    )
    data = await viewer.next(PreviewData)
    assert base64.b64decode(data.content_b64) == b"picture bytes"
    assert data.request_id == "r1"
    await owner.client.send(PreviewSet())
    await owner.next(PreviewChanged)
    assert not any(isinstance(event, PreviewData) for event in owner.events)
    assert not PreviewData.durable
