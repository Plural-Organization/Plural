from collections.abc import AsyncGenerator
from pathlib import Path

import pytest

from plural.agent.providers.fake import FakeProvider, reply, use_tool
from tests.e2e.support import Session, running_session


@pytest.fixture(params=["direct", "relay"])
async def session(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncGenerator[Session]:
    provider = FakeProvider([use_tool("bash", command="cat notes.txt"), reply("All good.")])
    async with running_session(
        tmp_path, relayed=request.param == "relay", provider=provider
    ) as running:
        yield running
