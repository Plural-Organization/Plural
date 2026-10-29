import time
from pathlib import Path

from websockets.asyncio.client import connect

from plural.host.team import DirectoryClient, TeamStore, create_team, join_team
from plural.security.identity import authorization
from tests.e2e.support import RelayServer


class Member:
    def __init__(self, root: Path, name: str) -> None:
        self.name = name
        self.store = TeamStore(root / name / "data")
        self.root = root / name

    async def client(self) -> DirectoryClient:
        profile = self.store.load()
        assert profile is not None
        return DirectoryClient(self.store, profile)


async def two_members(relay: RelayServer, root: Path) -> tuple[Member, Member]:
    vlad, alia = Member(root, "vlad"), Member(root, "alia")
    vlad.store.save(
        await create_team(relay.url, vlad.store.identity(), team="Backend", member="vlad")
    )
    invite = await (await vlad.client()).invite()
    alia.store.save(
        await join_team(relay.url, alia.store.identity(), code=invite.code, member="alia")
    )
    return vlad, alia


def connect_as(member: Member, relay: RelayServer) -> connect:
    profile = member.store.load()
    assert profile is not None
    url = f"{relay.url}/teams/{profile.team_id}/presence"
    header = authorization(
        member.store.identity(),
        profile.certificate,
        "GET",
        f"/teams/{profile.team_id}/presence",
        b"",
        timestamp=int(time.time()),
        nonce=time.time_ns().to_bytes(8, "big").hex(),
    )
    return connect(url, additional_headers={"authorization": header})
