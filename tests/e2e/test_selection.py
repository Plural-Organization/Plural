from plural.protocol.commands import SelectionSet
from plural.protocol.events import ParticipantSelected
from plural.protocol.models import Role, TextSelection
from tests.e2e.support import Session

PICK = TextSelection(anchor="m_1", start=4, end=12)


async def test_a_selection_is_shown_to_everyone_and_cleared(session: Session) -> None:
    owner = await session.owner()
    guest = await session.guest("Alia")
    me = guest.client.projection.me_id

    await guest.client.send(SelectionSet(selection=PICK))
    shown = await owner.next(ParticipantSelected)
    assert (shown.participant_id, shown.selection) == (me, PICK)

    await guest.client.send(SelectionSet(selection=None))
    cleared = await owner.next(ParticipantSelected)
    assert (cleared.participant_id, cleared.selection) == (me, None)


async def test_clearing_nothing_sends_nothing(session: Session) -> None:
    owner = await session.owner()
    guest = await session.guest("Alia")
    await guest.client.send(SelectionSet(selection=None))
    await guest.client.send(SelectionSet(selection=PICK))
    assert (await owner.next(ParticipantSelected)).selection == PICK
    assert len([e for e in owner.events if isinstance(e, ParticipantSelected)]) == 1


async def test_leaving_clears_the_selection(session: Session) -> None:
    owner = await session.owner()
    guest = await session.guest("Alia")
    await guest.client.send(SelectionSet(selection=PICK))
    await owner.next(ParticipantSelected)
    await guest.stop()
    assert (await owner.next(ParticipantSelected)).selection is None


async def test_viewers_share_what_they_select(session: Session) -> None:
    owner = await session.owner()
    viewer = await session.guest("Eve", Role.VIEWER)
    await viewer.client.send(SelectionSet(selection=PICK))
    assert (await owner.next(ParticipantSelected)).participant_id == viewer.client.projection.me_id
