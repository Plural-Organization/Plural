from collections.abc import Iterable, Mapping

from plural.agent.messages import (
    AssistantTurn,
    Message,
    NotesTurn,
    SummaryTurn,
    ToolResultTurn,
    UserTurn,
)
from plural.agent.providers.base import ToolCallRequest
from plural.protocol.events import (
    BriefingImported,
    ContextCompacted,
    EventRecord,
    MessageEnded,
    PromptAccepted,
    PromptDequeued,
    RunEnded,
    RunStarted,
    ToolEnded,
    ToolStarted,
)
from plural.protocol.models import Actor, ActorKind, DequeueReason

INTERRUPTED = "Not executed: run interrupted"


def replay(
    records: Iterable[EventRecord], *, names: Mapping[str, str], texts: Mapping[str, str]
) -> list[Message]:
    messages: list[Message] = []
    prompts: dict[str, UserTurn] = {}
    tool_names: dict[str, str] = {}
    attached: set[str] = set()
    run_prompt: UserTurn | None = None
    assistant_at: int | None = None
    notes: list[NotesTurn] = []
    for record in records:
        match record.event:
            case PromptAccepted(prompt_id=prompt_id, author_id=author_id, provenance=provenance):
                prompts[prompt_id] = UserTurn(
                    id=prompt_id,
                    author=Actor(
                        id=author_id, kind=ActorKind.HUMAN, name=names.get(author_id, author_id)
                    ),
                    provenance=provenance,
                    text=texts.get(prompt_id, record.event.text),
                )
            case RunStarted(prompt_id=prompt_id):
                _settle(messages)
                messages.extend(notes)
                notes.clear()
                run_prompt = prompts.get(prompt_id)
                if run_prompt is not None:
                    messages.append(run_prompt)
                assistant_at = None
            case PromptDequeued(prompt_id=prompt_id, reason=DequeueReason.DELIVERED) if (
                run_prompt is not None and prompt_id != run_prompt.id and prompt_id in prompts
            ):
                messages.append(prompts[prompt_id])
                assistant_at = None
            case MessageEnded(text=text):
                messages.append(AssistantTurn(text=text))
                assistant_at = len(messages) - 1
            case ToolStarted(call=view):
                tool_names[view.id] = view.name
                if assistant_at is not None:
                    attached.add(view.id)
                    turn = messages[assistant_at]
                    assert isinstance(turn, AssistantTurn)
                    call = ToolCallRequest(id=view.id, name=view.name, args=view.args)
                    messages[assistant_at] = turn.model_copy(
                        update={"tool_calls": (*turn.tool_calls, call)}
                    )
            case ToolEnded(call_id=call_id, ok=ok, output=output) if call_id in attached:
                messages.append(
                    ToolResultTurn(
                        call_id=call_id,
                        name=tool_names.get(call_id, ""),
                        content=output,
                        is_error=not ok,
                    )
                )
            case BriefingImported(item=item, text=text):
                turn = NotesTurn(source=item.source, text=text)
                (notes if run_prompt is not None else messages).append(turn)
            case ContextCompacted(summary=summary):
                messages = [SummaryTurn(text=summary)]
                if run_prompt is not None:
                    messages.append(run_prompt)
                assistant_at = None
            case RunEnded():
                _settle(messages)
                run_prompt = None
                assistant_at = None
            case _:
                pass
    _settle(messages)
    _order_results(messages)
    messages.extend(notes)
    return [
        message
        for message in messages
        if not isinstance(message, AssistantTurn) or message.text or message.tool_calls
    ]


def _order_results(messages: list[Message]) -> None:
    for index, message in enumerate(messages):
        if not isinstance(message, AssistantTurn) or not message.tool_calls:
            continue
        end = index + 1
        while end < len(messages) and isinstance(messages[end], ToolResultTurn):
            end += 1
        position = {call.id: order for order, call in enumerate(message.tool_calls)}
        results = [m for m in messages[index + 1 : end] if isinstance(m, ToolResultTurn)]
        results.sort(key=lambda result: position.get(result.call_id, len(position)))
        messages[index + 1 : end] = results


def _settle(messages: list[Message]) -> None:
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if isinstance(message, AssistantTurn):
            answered = {m.call_id for m in messages[index + 1 :] if isinstance(m, ToolResultTurn)}
            messages.extend(
                ToolResultTurn(call_id=call.id, name=call.name, content=INTERRUPTED, is_error=True)
                for call in message.tool_calls
                if call.id not in answered
            )
            return
