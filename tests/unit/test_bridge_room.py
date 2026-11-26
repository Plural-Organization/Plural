import asyncio
from typing import cast

from plural.bridge.model import Place
from plural.bridge.platform import ChatPlatform
from plural.bridge.room import ApprovalBook, RoomFeed, _Sent  # pyright: ignore[reportPrivateUsage]
from plural.core.provenance import direct
from plural.protocol.commands import ClientInfo
from plural.protocol.events import InviteCreated, PromptAccepted
from plural.protocol.models import Delivery, Role


def feed() -> RoomFeed:
    return RoomFeed(
        "r_1",
        cast(ChatPlatform, object()),
        places=list[Place],
        lookup=lambda _room: None,
        approvals=ApprovalBook(),
        client=ClientInfo(kind="test", version="0"),
    )


async def test_prompt_origin_follows_the_request_id_when_identical_prompts_arrive_out_of_order(
) -> None:
    room = feed()
    first = _Sent("p_host", "same", Place("fake", "one"), "m1")
    second = _Sent("p_host", "same", Place("fake", "two"), "m2")
    room._sent = {"first": first, "second": second}  # pyright: ignore[reportPrivateUsage]

    await room._on(  # pyright: ignore[reportPrivateUsage]
        PromptAccepted(
            prompt_id="pm_2",
            author_id="p_host",
            text="same",
            delivery=Delivery.NOW,
            provenance=direct("p_host", Role.HOST),
            client_request_id="second",
        )
    )
    await room._on(  # pyright: ignore[reportPrivateUsage]
        PromptAccepted(
            prompt_id="pm_1",
            author_id="p_host",
            text="same",
            delivery=Delivery.NOW,
            provenance=direct("p_host", Role.HOST),
            client_request_id="first",
        )
    )

    assert room._prompts["pm_2"][2] is second  # pyright: ignore[reportPrivateUsage]
    assert room._prompts["pm_1"][2] is first  # pyright: ignore[reportPrivateUsage]


async def test_going_offline_forgets_unaccepted_and_unstarted_prompts() -> None:
    room = feed()
    sent = _Sent("p_host", "old", Place("fake", "one"), "m1")
    room._sent = {"old": sent}  # pyright: ignore[reportPrivateUsage]
    room._prompts = {"pm_old": ("p_host", "old", sent)}  # pyright: ignore[reportPrivateUsage]

    await room._went_offline()  # pyright: ignore[reportPrivateUsage]

    assert room._sent == {}  # pyright: ignore[reportPrivateUsage]
    assert room._prompts == {}  # pyright: ignore[reportPrivateUsage]


async def test_invite_waiter_accepts_only_its_participant_invite() -> None:
    room = feed()
    room._invite = asyncio.get_running_loop().create_future()  # pyright: ignore[reportPrivateUsage]
    room._invite_request_id = "wanted"  # pyright: ignore[reportPrivateUsage]

    await room._on(  # pyright: ignore[reportPrivateUsage]
        InviteCreated(
            code="viewer",
            role=Role.VIEWER,
            link="plural://viewer",
            client_request_id="wanted",
        )
    )
    await room._on(  # pyright: ignore[reportPrivateUsage]
        InviteCreated(
            code="other",
            role=Role.PARTICIPANT,
            link="plural://other",
            client_request_id="other",
        )
    )
    assert not room._invite.done()  # pyright: ignore[reportPrivateUsage]

    await room._on(  # pyright: ignore[reportPrivateUsage]
        InviteCreated(
            code="participant",
            role=Role.PARTICIPANT,
            link="plural://participant",
            client_request_id="wanted",
        )
    )
    assert room._invite.result() == "plural://participant"  # pyright: ignore[reportPrivateUsage]
