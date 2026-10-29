from typing import Final

from plural.protocol.events import (
    AdmissionChanged,
    AgentChanged,
    AgentsChanged,
    ApprovalRequested,
    ApprovalResolved,
    AttachmentAdded,
    BoardCleared,
    BoardErased,
    BoardOpened,
    BoardStroked,
    ChatPosted,
    ContextCompacted,
    ContextUsage,
    EventRecord,
    JoinRequested,
    JoinResolved,
    McpChanged,
    MessageEnded,
    ParticipantJoined,
    ParticipantLeft,
    ParticipantRevoked,
    ParticipantRoleChanged,
    PermissionModeChanged,
    PolicyRuleAdded,
    PolicyRuleRemoved,
    PromptAccepted,
    PromptDequeued,
    PromptModeChanged,
    ProposalApproved,
    ProposalCreated,
    ProposalRejected,
    RunEnded,
    RunStarted,
    SkillsChanged,
    ToolEnded,
    ToolStarted,
    UsageRecorded,
)
from plural.protocol.models import (
    BOARD_STROKES_LIMIT,
    BOARD_TOTAL_POINTS,
    BoardStroke,
    ChatEntry,
    EntryKind,
    QueuedPrompt,
    RunView,
    SessionState,
    TranscriptEntry,
    UsageLine,
)

TRANSCRIPT_LIMIT: Final = 200
CHAT_LIMIT: Final = 200
OUTPUT_PREVIEW_CHARS: Final = 2000


def _within_budget(strokes: tuple[BoardStroke, ...]) -> tuple[BoardStroke, ...]:
    total = sum(len(stroke.points) for stroke in strokes)
    start = 0
    while total > BOARD_TOTAL_POINTS and start < len(strokes) - 1:
        total -= len(strokes[start].points)
        start += 1
    return strokes[start:]


def reduce(state: SessionState, record: EventRecord) -> SessionState:
    return _apply(state, record).model_copy(update={"last_seq": record.seq})


def _apply(state: SessionState, record: EventRecord) -> SessionState:
    event = record.event
    match event:
        case ParticipantJoined(participant=participant):
            return state.model_copy(
                update={"participants": {**state.participants, participant.id: participant}}
            )
        case ParticipantLeft(participant_id=participant_id):
            return _patch_participant(state, participant_id, {"connected": False})
        case ParticipantRoleChanged(participant_id=participant_id, role=role):
            return _patch_participant(state, participant_id, {"role": role})
        case ParticipantRevoked(participant_id=participant_id):
            return state.model_copy(
                update={"participants": _without(state.participants, participant_id)}
            )
        case AdmissionChanged(mode=mode):
            return state.model_copy(update={"admission": mode})
        case JoinRequested(request=request):
            return state.model_copy(
                update={"join_requests": {**state.join_requests, request.id: request}}
            )
        case JoinResolved(request_id=request_id):
            return state.model_copy(
                update={"join_requests": _without(state.join_requests, request_id)}
            )
        case AgentChanged(agent=agent, fast=fast):
            return state.model_copy(update={"agent": agent, "fast_agent": fast})
        case PromptModeChanged(mode=mode):
            return state.model_copy(update={"prompt_mode": mode})
        case PermissionModeChanged(mode=mode):
            return state.model_copy(update={"permission_mode": mode})
        case AgentsChanged(agents=agents):
            return state.model_copy(update={"agents": agents})
        case UsageRecorded(lines=lines):
            return state.model_copy(update={"usage": _add_usage(state.usage, lines)})
        case McpChanged(servers=servers):
            return state.model_copy(update={"mcp": servers})
        case ContextUsage(context=context):
            return state.model_copy(update={"context": context})
        case SkillsChanged(skills=skills):
            return state.model_copy(update={"skills": skills})
        case ProposalCreated(proposal=proposal):
            return state.model_copy(
                update={"proposals": {**state.proposals, proposal.id: proposal}}
            )
        case ProposalApproved(proposal_id=proposal_id) | ProposalRejected(proposal_id=proposal_id):
            return state.model_copy(update={"proposals": _without(state.proposals, proposal_id)})
        case PromptAccepted():
            entry = TranscriptEntry(
                id=event.prompt_id,
                kind=EntryKind.PROMPT,
                author_id=event.author_id,
                text=event.text,
            )
            queued = state.run is not None
            if queued:
                state = state.model_copy(
                    update={
                        "queue": (
                            *state.queue,
                            QueuedPrompt(
                                prompt_id=event.prompt_id,
                                author_id=event.author_id,
                                text=event.text,
                                delivery=event.delivery,
                            ),
                        )
                    }
                )
            return _append(state, entry)
        case ChatPosted():
            entry = ChatEntry(
                id=event.message_id,
                author_id=event.author_id,
                text=event.text,
                ts=record.ts,
                to=event.to,
                mentions=event.mentions,
            )
            return state.model_copy(update={"chat": (*state.chat, entry)[-CHAT_LIMIT:]})
        case BoardOpened(open=open_):
            return state.model_copy(
                update={"board": state.board.model_copy(update={"open": open_})}
            )
        case BoardStroked(stroke=stroke):
            strokes = _within_budget((*state.board.strokes, stroke)[-BOARD_STROKES_LIMIT:])
            return state.model_copy(
                update={"board": state.board.model_copy(update={"strokes": strokes})}
            )
        case BoardErased(stroke_id=stroke_id):
            strokes = tuple(stroke for stroke in state.board.strokes if stroke.id != stroke_id)
            return state.model_copy(
                update={"board": state.board.model_copy(update={"strokes": strokes})}
            )
        case BoardCleared(author_id=author_id):
            kept = (
                ()
                if author_id is None
                else tuple(s for s in state.board.strokes if s.author_id != author_id)
            )
            return state.model_copy(
                update={"board": state.board.model_copy(update={"strokes": kept})}
            )
        case PromptDequeued(prompt_id=prompt_id):
            kept = tuple(entry for entry in state.queue if entry.prompt_id != prompt_id)
            return state.model_copy(update={"queue": kept})
        case RunStarted():
            run = RunView(id=event.run_id, prompt_id=event.prompt_id, provenance=event.provenance)
            return state.model_copy(update={"run": run})
        case RunEnded():
            return state.model_copy(update={"run": None})
        case MessageEnded(message_id=message_id, text=text):
            return _append(
                state, TranscriptEntry(id=message_id, kind=EntryKind.ASSISTANT, text=text)
            )
        case ContextCompacted(summary=summary, tokens_before=tokens_before):
            entry = TranscriptEntry(
                id=record.id,
                kind=EntryKind.COMPACTION,
                text=f"context compacted ({tokens_before} tokens summarized)",
            )
            return _append(state.model_copy(update={"summary": summary}), entry)
        case ToolStarted(call=call):
            return _append(state, TranscriptEntry(id=call.id, kind=EntryKind.TOOL, tool=call))
        case ToolEnded(call_id=call_id, ok=ok, output=output):
            finished = {"ok": ok, "output": output[:OUTPUT_PREVIEW_CHARS]}
            transcript = tuple(
                entry.model_copy(update=finished) if entry.id == call_id else entry
                for entry in state.transcript
            )
            return state.model_copy(update={"transcript": transcript})
        case ApprovalRequested(approval=approval):
            return state.model_copy(
                update={"approvals": {**state.approvals, approval.id: approval}}
            )
        case ApprovalResolved(approval_id=approval_id):
            return state.model_copy(update={"approvals": _without(state.approvals, approval_id)})
        case PolicyRuleAdded(rule=rule):
            return state.model_copy(update={"policy": (*state.policy, rule)})
        case PolicyRuleRemoved(rule_id=rule_id):
            kept = tuple(rule for rule in state.policy if rule.id != rule_id)
            return state.model_copy(update={"policy": kept})
        case AttachmentAdded(attachment=attachment):
            return state.model_copy(
                update={"attachments": {**state.attachments, attachment.id: attachment}}
            )
        case _:
            return state


def _patch_participant(
    state: SessionState, participant_id: str, changes: dict[str, object]
) -> SessionState:
    participant = state.participants.get(participant_id)
    if participant is None:
        return state
    patched = participant.model_copy(update=changes)
    return state.model_copy(
        update={"participants": {**state.participants, participant_id: patched}}
    )


def _append(state: SessionState, entry: TranscriptEntry) -> SessionState:
    return state.model_copy(update={"transcript": (*state.transcript, entry)[-TRANSCRIPT_LIMIT:]})


def _without[V](mapping: dict[str, V], key: str) -> dict[str, V]:
    return {k: v for k, v in mapping.items() if k != key}


def _add_usage(total: tuple[UsageLine, ...], lines: tuple[UsageLine, ...]) -> tuple[UsageLine, ...]:
    merged = {(line.role, line.model, line.agent): line for line in total}
    for line in lines:
        key = (line.role, line.model, line.agent)
        previous = merged.get(key)
        merged[key] = (
            line
            if previous is None
            else previous.model_copy(
                update={"uses": previous.uses + line.uses, "usage": previous.usage + line.usage}
            )
        )
    return tuple(merged.values())
