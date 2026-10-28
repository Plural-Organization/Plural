from plural.core.errors import Invalid, NotFound
from plural.protocol.commands import MAX_MENTIONS, ChatSend
from plural.protocol.events import ChatPosted
from plural.protocol.models import Participant, Role, SessionState


def post(
    state: SessionState, *, message_id: str, author: Participant, command: ChatSend
) -> ChatPosted:
    to = command.to
    if to is not None:
        recipient = state.participants.get(to)
        if recipient is None:
            raise NotFound("no such participant")
        if to == author.id:
            raise Invalid("a private message needs someone else")
        if recipient.role is Role.VIEWER:
            raise Invalid(f"{recipient.name} watches the session and cannot get private messages")
    if len(command.mentions) > MAX_MENTIONS:
        raise Invalid(f"a message can mention at most {MAX_MENTIONS} people")
    mentions: list[str] = []
    for mention in command.mentions:
        if mention not in state.participants:
            raise NotFound("no such participant")
        if mention not in mentions:
            mentions.append(mention)
    return ChatPosted(
        message_id=message_id,
        author_id=author.id,
        text=command.text,
        to=to,
        mentions=tuple(mentions),
    )
