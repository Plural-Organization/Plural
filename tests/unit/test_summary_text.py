from plural.agent.context.compaction import RESULT_CHARS, serialize, summary_request, with_files
from plural.agent.loop.messages import AssistantTurn, SummaryTurn, ToolResultTurn, UserTurn
from plural.agent.providers.base import ToolCallRequest
from plural.core.provenance import direct
from plural.protocol.models import Actor, ActorKind, Role


def _said(name: str, text: str) -> UserTurn:
    actor = Actor(id=f"p_{name}", kind=ActorKind.HUMAN, name=name)
    return UserTurn(
        id=f"pm_{text}", author=actor, provenance=direct(actor.id, Role.HOST), text=text
    )


def _calls(*calls: tuple[str, str]) -> AssistantTurn:
    return AssistantTurn(
        tool_calls=tuple(
            ToolCallRequest(id=f"c{i}", name=name, args={"path": path})
            for i, (name, path) in enumerate(calls)
        )
    )


def test_the_conversation_is_written_out_with_long_results_cut() -> None:
    text = serialize(
        [
            _said("Alia", "fix the build"),
            AssistantTurn(
                text="looking",
                tool_calls=(ToolCallRequest(id="c1", name="bash", args={"command": "make"}),),
            ),
            ToolResultTurn(
                call_id="c1", name="bash", content="e" * (RESULT_CHARS + 50), is_error=True
            ),
            SummaryTurn(text="never shown"),
        ]
    )
    assert "[Alia]\nfix the build" in text
    assert '[agent calls] bash({"command": "make"})' in text
    assert "[bash result failed]" in text
    assert "[50 characters the agent read are left out here]" in text
    assert "never shown" not in text


def test_files_read_and_changed_carry_over_from_the_earlier_summary() -> None:
    earlier = "old\n\n<read-files>\na.py\nb.py\n</read-files>"
    history = [_calls(("read", "c.py"), ("edit", "b.py"), ("read", "output:1"), ("write", "d.py"))]
    summary = with_files("new", history, earlier)
    assert summary == (
        "new\n\n<read-files>\na.py\nc.py\n</read-files>\n\n<modified-files>\nb.py\nd.py\n</modified-files>"
    )


def test_an_update_shows_the_earlier_summary_without_its_file_lists() -> None:
    asked = summary_request(
        [_said("Alia", "go on")], "old work\n\n<read-files>\na.py\n</read-files>"
    )
    assert "<previous_summary>\nold work\n</previous_summary>" in asked
    assert asked.index("<conversation>") < asked.index("<previous_summary>")
