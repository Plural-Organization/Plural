from plural.protocol.events import ChatPosted, Event, EventRecord, JoinRequested, JoinResolved
from plural.protocol.models import HOST_PARTICIPANT_ID, SessionState


def visible_to(event: Event, viewer_id: str) -> bool:
    if isinstance(event, ChatPosted) and event.to is not None:
        return viewer_id in (event.author_id, event.to)
    if isinstance(event, JoinRequested | JoinResolved):
        return viewer_id == HOST_PARTICIPANT_ID
    return True


def record_visible_to(record: EventRecord, viewer_id: str) -> bool:
    return visible_to(record.event, viewer_id)


def state_for(state: SessionState, viewer_id: str) -> SessionState:
    chat = tuple(
        entry
        for entry in state.chat
        if entry.to is None or viewer_id in (entry.author_id, entry.to)
    )
    changes: dict[str, object] = {}
    if len(chat) != len(state.chat):
        changes["chat"] = chat
    if viewer_id != HOST_PARTICIPANT_ID and state.join_requests:
        changes["join_requests"] = {}
    return state.model_copy(update=changes) if changes else state
