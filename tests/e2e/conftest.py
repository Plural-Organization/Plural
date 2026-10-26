from collections.abc import AsyncGenerator
from pathlib import Path

import pytest

from plural.agent.providers.fake import FakeProvider, reply, use_tool
from plural.protocol.models import PromptMode
from tests.doubles import StallingProvider
from tests.e2e.support import Session, running_session


async def serve(
    request: pytest.FixtureRequest, tmp_path: Path, mode: PromptMode | None
) -> AsyncGenerator[Session]:
    provider = FakeProvider([use_tool("bash", command="cat notes.txt"), reply("All good.")])
    async with running_session(
        tmp_path,
        relayed=request.param == "relay",
        provider=provider,
        overrides={"prompt_mode": mode},
    ) as running:
        yield running


@pytest.fixture(params=["direct", "relay"])
async def session(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncGenerator[Session]:
    async for running in serve(request, tmp_path, None):
        yield running


@pytest.fixture(params=["direct", "relay"])
async def review_session(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncGenerator[Session]:
    async for running in serve(request, tmp_path, PromptMode.REVIEW):
        yield running


@pytest.fixture
async def stalled_session(tmp_path: Path) -> AsyncGenerator[Session]:
    async with running_session(
        tmp_path, relayed=False, provider=StallingProvider(text="working on it")
    ) as running:
        yield running
