import asyncio
import json
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from plural.cli.main import app
from plural.host.team import (
    DirectoryClient,
    TeamError,
    TeamProfile,
    TeamStore,
    create_team,
    join_team,
)
from tests.e2e.support import RelayServer


@pytest.fixture
async def relay(tmp_path: Path) -> AsyncGenerator[RelayServer]:
    server = RelayServer(teams=tmp_path / "relay" / "teams.db")
    await server.start()
    yield server
    await server.stop()


class Person:
    def __init__(self, root: Path, name: str) -> None:
        self.name = name
        self.store = TeamStore(root / name)
        self.profile: TeamProfile | None = None

    @property
    def directory(self) -> DirectoryClient:
        assert self.profile is not None
        return DirectoryClient(self.store, self.profile)


async def founder(relay: RelayServer, root: Path) -> tuple[Person, str]:
    vlad = Person(root, "vlad")
    vlad.profile = await create_team(
        relay.url, vlad.store.identity(), team="Backend", member="vlad"
    )
    invite = await vlad.directory.invite()
    return vlad, invite.code


async def test_two_people_form_a_team_and_see_each_other(
    relay: RelayServer, tmp_path: Path
) -> None:
    vlad, code = await founder(relay, tmp_path)
    alia = Person(tmp_path, "alia")
    alia.profile = await join_team(relay.url, alia.store.identity(), code=code, member="alia")

    assert alia.profile.team_id == vlad.profile.team_id  # type: ignore[union-attr]
    for person in (vlad, alia):
        listing = await person.directory.members()
        assert (listing.team_name, [m.name for m in listing.members]) == (
            "Backend",
            ["vlad", "alia"],
        )


async def test_an_invite_code_is_used_once_over_the_wire(
    relay: RelayServer, tmp_path: Path
) -> None:
    _, code = await founder(relay, tmp_path)
    alia, bek = Person(tmp_path, "alia"), Person(tmp_path, "bek")
    await join_team(relay.url, alia.store.identity(), code=code, member="alia")
    with pytest.raises(TeamError, match="wrong, used or expired"):
        await join_team(relay.url, bek.store.identity(), code=code, member="bek")


async def test_a_stranger_sees_nothing_of_a_team(relay: RelayServer, tmp_path: Path) -> None:
    vlad, _ = await founder(relay, tmp_path)
    stranger = Person(tmp_path, "mallory")
    assert vlad.profile is not None
    stranger.profile = vlad.profile
    with pytest.raises(TeamError, match="not a member"):
        await stranger.directory.members()


async def test_only_the_owner_invites_and_kicks_and_a_kicked_member_is_out(
    relay: RelayServer, tmp_path: Path
) -> None:
    vlad, code = await founder(relay, tmp_path)
    alia = Person(tmp_path, "alia")
    alia.profile = await join_team(relay.url, alia.store.identity(), code=code, member="alia")

    with pytest.raises(TeamError, match="only the team owner"):
        await alia.directory.invite()
    with pytest.raises(TeamError, match="only the team owner"):
        await alia.directory.remove("vlad")

    removed = await vlad.directory.remove("alia")
    assert removed.name == "alia"
    with pytest.raises(TeamError, match="not a member"):
        await alia.directory.members()


async def test_guessing_codes_is_slowed_down(relay: RelayServer, tmp_path: Path) -> None:
    await founder(relay, tmp_path)
    guesser = Person(tmp_path, "guesser")
    answers: list[str] = []
    for attempt in range(8):
        try:
            await join_team(
                relay.url, guesser.store.identity(), code=f"tm-aaaa{attempt}-bbbbb", member="g"
            )
        except TeamError as error:
            answers.append(str(error))
    assert any("too many tries" in answer for answer in answers)


async def test_a_relay_without_a_directory_says_so(tmp_path: Path) -> None:
    server = RelayServer()
    await server.start()
    try:
        person = Person(tmp_path, "vlad")
        with pytest.raises(TeamError):
            await create_team(server.url, person.store.identity(), team="Backend", member="vlad")
    finally:
        await server.stop()


async def test_the_commands_do_the_whole_round_trip(
    relay: RelayServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = CliRunner()

    async def command(home: str, *args: str) -> str:
        monkeypatch.setenv("PLURAL_DATA_DIR", str(tmp_path / home))
        result = await asyncio.to_thread(runner.invoke, app, ["team", *args])
        assert result.exit_code == 0, result.output
        return result.output

    created = await command("vlad", "create", "Backend", "--relay", relay.url, "--as", "vlad")
    assert "Teammates run: plural team join" in created
    code = next(word for word in created.split() if word.startswith("tm-")).rstrip(",.")
    await command("alia", "join", code, "--relay", relay.url, "--as", "alia")

    listing = await command("alia", "members")
    assert "vlad" in listing
    assert "alia" in listing
    assert "Backend" in await command("alia", "status")

    await command("vlad", "kick", "alia")
    monkeypatch.setenv("PLURAL_DATA_DIR", str(tmp_path / "alia"))
    denied = await asyncio.to_thread(runner.invoke, app, ["team", "members"])
    assert denied.exit_code == 1
    assert "not a member" in denied.output

    again = await command("vlad", "invite")
    second = next(word for word in again.split() if word.startswith("tm-")).rstrip(",.")
    await command("bek", "join", second, "--relay", relay.url, "--as", "bek")
    assert "You left" in await command("bek", "leave")
    assert "bek" not in await command("vlad", "members")

    assert "gone" in await command("vlad", "disband", "--yes")
    assert "Not in a team" in await command("vlad", "status")


async def test_create_can_print_the_invite_as_json(
    relay: RelayServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PLURAL_DATA_DIR", str(tmp_path / "vlad"))
    result = await asyncio.to_thread(
        CliRunner().invoke,
        app,
        ["team", "create", "Backend", "--relay", relay.url, "--as", "vlad", "--json"],
    )
    assert result.exit_code == 0, result.output
    printed = json.loads(result.output)
    assert (printed["team"], printed["relay"], printed["minutes"]) == ("Backend", relay.url, 60)
    assert printed["code"].startswith("tm-")

    alia = Person(tmp_path, "alia")
    joined = await join_team(relay.url, alia.store.identity(), code=printed["code"], member="alia")
    assert joined.team_name == "Backend"
