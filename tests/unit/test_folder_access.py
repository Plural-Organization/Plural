import asyncio
from pathlib import Path

import pytest
from tests.loop_support import StubGate, collect, make_loop, turn

from plural.agent.events import AgentEvent, ToolEnd
from plural.agent.gate import FolderResult
from plural.agent.providers.fake import FakeProvider, reply, use_tool
from plural.agent.sandbox.base import PathDenied, PathOutsideWorkspace, Workspace
from plural.core import approvals
from plural.core.errors import Invalid
from plural.core.policy.engine import Policy
from plural.core.provenance import direct
from plural.host.approval_registry import ApprovalRegistry
from plural.host.inbox import ApprovalNeeded, Inbox
from plural.host.policy_gate import HostPolicyGate
from plural.host.system import SystemClock, UlidGenerator
from plural.protocol.events import ApprovalResolved
from plural.protocol.models import (
    ApprovalDecision,
    ApprovalView,
    FolderAccess,
    Role,
    SessionState,
    ToolCallView,
    ToolRisk,
)


def _tool_end(events: list[AgentEvent]) -> ToolEnd:
    return next(event for event in events if isinstance(event, ToolEnd))


def _outside(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "work"
    elsewhere = tmp_path / "elsewhere"
    workspace.mkdir()
    elsewhere.mkdir()
    (elsewhere / "notes.txt").write_text("outside\n")
    return workspace, elsewhere


def test_a_path_outside_the_workspace_is_refused_until_a_folder_is_opened(tmp_path: Path) -> None:
    root, elsewhere = _outside(tmp_path)
    workspace = Workspace.at(root)
    with pytest.raises(PathOutsideWorkspace):
        workspace.resolve(str(elsewhere / "notes.txt"))
    assert workspace.outside(str(elsewhere / "notes.txt")) == elsewhere.resolve()
    opened = workspace.granting(elsewhere.resolve(), write=False)
    assert opened.resolve(str(elsewhere / "notes.txt")) == (elsewhere / "notes.txt").resolve()
    assert opened.outside(str(elsewhere / "notes.txt")) is None


def test_a_folder_opened_for_reading_cannot_be_written(tmp_path: Path) -> None:
    root, elsewhere = _outside(tmp_path)
    reading = Workspace.at(root).granting(elsewhere.resolve(), write=False)
    with pytest.raises(PathOutsideWorkspace, match="reading only"):
        reading.resolve(str(elsewhere / "notes.txt"), write=True)
    writing = Workspace.at(root).granting(elsewhere.resolve(), write=True)
    assert writing.resolve(str(elsewhere / "new.txt"), write=True).name == "new.txt"


def test_protected_files_stay_protected_inside_an_opened_folder(tmp_path: Path) -> None:
    root, elsewhere = _outside(tmp_path)
    (elsewhere / ".env").write_text("SECRET=1\n")
    opened = Workspace.at(root).granting(elsewhere.resolve(), write=True)
    with pytest.raises(PathDenied):
        opened.resolve(str(elsewhere / ".env"))


def test_a_link_and_dotdot_do_not_slip_out_of_a_folder(tmp_path: Path) -> None:
    root, elsewhere = _outside(tmp_path)
    (root / "link").symlink_to(elsewhere)
    workspace = Workspace.at(root)
    # a link inside the workspace that points out is outside, not inside
    assert workspace.outside("link/notes.txt") == elsewhere.resolve()
    opened = workspace.granting(elsewhere.resolve(), write=False)
    with pytest.raises(PathOutsideWorkspace):
        opened.resolve(str(elsewhere / ".." / "unrelated" / "x"))


async def test_the_hosts_own_run_opens_a_folder_without_a_question(tmp_path: Path) -> None:
    root, elsewhere = _outside(tmp_path)
    gate = StubGate()
    path = str(elsewhere / "notes.txt")
    provider = FakeProvider([use_tool("read", path=path), reply("done")])
    events = await collect(make_loop(root, provider, gate), turn("read it"))
    result = _tool_end(events)
    assert "outside" in result.result.content
    assert gate.folders == []


async def test_a_guests_run_asks_the_host_and_the_answer_decides(tmp_path: Path) -> None:
    root, elsewhere = _outside(tmp_path)
    gate = StubGate()
    gate.folder_answer = FolderResult(True, False, "read")
    path = str(elsewhere / "notes.txt")
    provider = FakeProvider([use_tool("read", path=path), reply("done")])
    events = await collect(make_loop(root, provider, gate), turn("read it", guest=True))
    result = _tool_end(events)
    assert not result.result.is_error
    assert "outside" in result.result.content
    assert [(folder, write) for folder, write, _ in gate.folders] == [
        (str(elsewhere.resolve()), False)
    ]


async def test_a_refused_folder_stops_the_call_before_the_usual_approval(tmp_path: Path) -> None:
    root, elsewhere = _outside(tmp_path)
    gate = StubGate()
    path = str(elsewhere / "notes.txt")
    provider = FakeProvider([use_tool("read", path=path), reply("done")])
    events = await collect(make_loop(root, provider, gate), turn("read it", guest=True))
    result = _tool_end(events)
    assert result.result.is_error
    assert result.result.content.startswith("Denied")
    assert gate.seen == []


async def test_reading_only_is_not_enough_for_a_write(tmp_path: Path) -> None:
    root, elsewhere = _outside(tmp_path)
    gate = StubGate()
    gate.folder_answer = FolderResult(True, False, "read")
    target = elsewhere / "new.txt"
    provider = FakeProvider([use_tool("write", path=str(target), content="x"), reply("done")])
    events = await collect(make_loop(root, provider, gate), turn("write it", guest=True))
    result = _tool_end(events)
    assert result.result.is_error
    assert "reading only" in result.result.content
    assert not target.exists()


async def test_a_write_opened_by_the_host_goes_on_to_the_usual_approval(tmp_path: Path) -> None:
    root, elsewhere = _outside(tmp_path)
    gate = StubGate()
    gate.folder_answer = FolderResult(True, True, "write")
    target = elsewhere / "new.txt"
    provider = FakeProvider([use_tool("write", path=str(target), content="x"), reply("done")])
    await collect(make_loop(root, provider, gate), turn("write it", guest=True))
    assert target.read_text() == "x"
    assert [subject for subject, _ in gate.seen] == [str(target)]


async def test_a_protected_folder_is_never_asked_for(tmp_path: Path) -> None:
    root, _ = _outside(tmp_path)
    ssh = tmp_path / ".ssh"
    ssh.mkdir()
    (ssh / "known_hosts").write_text("h\n")
    gate = StubGate()
    gate.folder_answer = FolderResult(True, True, "write")
    provider = FakeProvider([use_tool("read", path=str(ssh / "known_hosts")), reply("done")])
    events = await collect(make_loop(root, provider, gate), turn("read it", guest=True))
    result = _tool_end(events)
    assert result.result.is_error
    assert "protected" in result.result.content
    assert gate.folders == []


async def test_bash_never_goes_through_a_folder_grant(tmp_path: Path) -> None:
    root, elsewhere = _outside(tmp_path)
    gate = StubGate()
    provider = FakeProvider([use_tool("bash", command=f"ls {elsewhere}"), reply("done")])
    await collect(make_loop(root, provider, gate), turn("list it", guest=True))
    assert gate.folders == []
    assert [subject for subject, _ in gate.seen] == [f"ls {elsewhere}"]


class _Harness:
    def __init__(self) -> None:
        self.inbox = Inbox()
        self.registry = ApprovalRegistry()
        self.gate = HostPolicyGate(
            policy=Policy(),
            registry=self.registry,
            inbox=self.inbox,
            ids=UlidGenerator(),
            clock=SystemClock(),
            timeout_s=30,
            rejection_limit=2,
        )

    async def ask(
        self, folder: Path, answer: ApprovalDecision, *, write: bool = False
    ) -> tuple[FolderResult, ApprovalView]:
        call = ToolCallView(id="c", name="read", risk=ToolRisk.READ, subject=str(folder))
        guest = direct("p_alia", Role.PARTICIPANT)
        waiting = asyncio.create_task(
            self.gate.ask_folder(call, folder=folder, write=write, provenance=guest)
        )
        message = await asyncio.wait_for(self.inbox.get(), 2)
        assert isinstance(message, ApprovalNeeded)
        self.registry.resolve(message.approval.id, answer)
        return await asyncio.wait_for(waiting, 2), message.approval


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    return tmp_path.resolve()


async def test_the_host_chooses_read_write_or_nothing(folder: Path) -> None:
    harness = _Harness()
    result, approval = await harness.ask(folder, ApprovalDecision.READ)
    assert (result.granted, result.write) == (True, False)
    assert approval.folder == FolderAccess(folder=str(folder), write=False, broad=False)
    result, _ = await harness.ask(folder, ApprovalDecision.WRITE, write=True)
    assert (result.granted, result.write) == (True, True)
    result, _ = await harness.ask(folder, ApprovalDecision.REJECT)
    assert not result.granted
    assert "ask the user" in result.reason


async def test_every_request_is_asked_again_and_a_broad_folder_is_marked(folder: Path) -> None:
    harness = _Harness()
    for _ in range(3):
        await harness.ask(folder, ApprovalDecision.READ)
    _, approval = await harness.ask(Path.home(), ApprovalDecision.REJECT)
    assert approval.folder is not None
    assert approval.folder.broad
    _, root = await harness.ask(Path("/"), ApprovalDecision.REJECT)
    assert root.folder is not None
    assert root.folder.broad


async def test_a_protected_folder_is_not_offered_to_the_host(tmp_path: Path) -> None:
    harness = _Harness()
    call = ToolCallView(id="c", name="read", risk=ToolRisk.READ, subject="x")
    result = await harness.gate.ask_folder(
        call,
        folder=Path.home() / ".ssh",
        write=False,
        provenance=direct("p_alia", Role.PARTICIPANT),
    )
    assert not result.granted
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(harness.inbox.get(), 0.05)


def _state_with(approval_folder: FolderAccess | None) -> SessionState:
    call = ToolCallView(id="c", name="read", risk=ToolRisk.READ, subject="x")
    approval = ApprovalView(
        id="ap_1",
        call=call,
        provenance=direct("p_alia", Role.PARTICIPANT),
        timeout_at=SystemClock().now(),
        folder=approval_folder,
    )
    return SessionState(approvals={"ap_1": approval})


def test_a_folder_request_takes_only_folder_answers() -> None:
    state = _state_with(FolderAccess(folder="/srv", write=False))
    for decision in (ApprovalDecision.READ, ApprovalDecision.WRITE, ApprovalDecision.REJECT):
        resolved = approvals.resolve(state, approval_id="ap_1", decision=decision, resolved_by="h")
        assert isinstance(resolved, ApprovalResolved)
    for decision in (ApprovalDecision.ONCE, ApprovalDecision.ALWAYS, ApprovalDecision.BLOCK):
        with pytest.raises(Invalid):
            approvals.resolve(state, approval_id="ap_1", decision=decision, resolved_by="h")


def test_a_tool_call_does_not_take_a_folder_answer() -> None:
    state = _state_with(None)
    with pytest.raises(Invalid):
        approvals.resolve(
            state, approval_id="ap_1", decision=ApprovalDecision.WRITE, resolved_by="h"
        )
    assert approvals.resolve(
        state, approval_id="ap_1", decision=ApprovalDecision.ONCE, resolved_by="h"
    )
