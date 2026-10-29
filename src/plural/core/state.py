from typing import Final

from plural.protocol.events import (
    AccessRequested,
    AccessResolved,
    AdmissionChanged,
    AgentChanged,
    AgentsChanged,
    ApprovalRequested,
    ApprovalResolved,
    AttachmentAdded,
    BoardCleared,
    BoardErased,
    BoardMoved,
    BoardOpened,
    BoardStroked,
    BriefingImported,
    BriefingRequested,
    BriefingResolved,
    BriefingSharingChanged,
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
    PluginsChanged,
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
    ToolsLoaded,
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
IMPORTS_KEPT: Final = 10
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
            left = _patch_participant(state, participant_id, {"connected": False})
            return _without_briefings(left, participant_id)
        case ParticipantRoleChanged(participant_id=participant_id, role=role):
            patched = _patch_participant(state, participant_id, {"role": role})
            return patched.model_copy(
                update={"access_requests": _without(patched.access_requests, participant_id)}
            )
        case ParticipantRevoked(participant_id=participant_id):
            return state.model_copy(
                update={
                    "participants": _without(state.participants, participant_id),
                    "access_requests": _without(state.access_requests, participant_id),
                    "briefing_requests": {
                        key: ask
                        for key, ask in state.briefing_requests.items()
                        if ask.participant_id != participant_id
                    },
                }
            )
        case BriefingRequested(request=request):
            return state.model_copy(
                update={"briefing_requests": {**state.briefing_requests, request.id: request}}
            )
        case BriefingResolved(request_id=request_id):
            return state.model_copy(
                update={"briefing_requests": _without(state.briefing_requests, request_id)}
            )
        case BriefingSharingChanged(mode=mode):
            return state.model_copy(update={"briefing_sharing": mode})
        case BriefingImported(item=item):
            return state.model_copy(
                update={"briefings_imported": (*state.briefings_imported, item)[-IMPORTS_KEPT:]}
            )
        case AccessRequested(request=request):
            return state.model_copy(
                update={
                    "access_requests": {**state.access_requests, request.participant_id: request}
                }
            )
        case AccessResolved(participant_id=participant_id):
            return state.model_copy(
                update={"access_requests": _without(state.access_requests, participant_id)}
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
        case ToolsLoaded(tools=tools):
            loaded = tuple(dict.fromkeys((*state.loaded_tools, *tools)))
            return state.model_copy(update={"loaded_tools": loaded})
        case PluginsChanged(plugins=plugins, commands=commands):
            return state.model_copy(update={"plugins": plugins, "commands": commands})
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
        case BoardMoved(stroke_id=stroke_id, points=points):
            strokes = tuple(
                stroke.model_copy(update={"points": points}) if stroke.id == stroke_id else stroke
                for stroke in state.board.strokes
            )
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


def _without_briefings(state: SessionState, participant_id: str) -> SessionState:
    kept = {
        key: ask
        for key, ask in state.briefing_requests.items()
        if ask.participant_id != participant_id
    }
    return (
        state
        if len(kept) == len(state.briefing_requests)
        else state.model_copy(update={"briefing_requests": kept})
    )


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
