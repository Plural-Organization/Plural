"""Claude OAuth credentials for the Anthropic Messages provider."""

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from anthropic import AsyncAnthropic
from pydantic import BaseModel, ConfigDict, Field

from plural.agent.providers.api.anthropic import AnthropicProvider
from plural.agent.providers.base import Effort, LlmEvent, LlmRequest, ProviderError

# Same public OAuth client and token endpoint used by pi's Anthropic login.
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
REFRESH_MARGIN_S = 300


class OAuthCredentials(BaseModel):
    model_config = ConfigDict(extra="ignore")

    access: str = Field(min_length=1)
    refresh: str = Field(min_length=1)
    expires: float = Field(gt=0)


def load_credentials(path: Path) -> OAuthCredentials:
    try:
        return OAuthCredentials.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ProviderError(
            "Claude login missing or invalid; sign in again in Model settings"
        ) from error


def save_credentials(path: Path, credentials: OAuthCredentials) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as file:
            temporary = file.name
            os.fchmod(file.fileno(), 0o600)
            file.write(credentials.model_dump_json())
            file.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def _refresh(refresh_token: str) -> OAuthCredentials:
    body = json.dumps(
        {"grant_type": "refresh_token", "client_id": CLIENT_ID, "refresh_token": refresh_token}
    ).encode()
    request = Request(
        TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            result: dict[str, Any] = json.load(response)
        return OAuthCredentials(
            access=result["access_token"],
            refresh=result["refresh_token"],
            expires=time.time() + float(result["expires_in"]),
        )
    except (HTTPError, URLError, KeyError, ValueError, TypeError) as error:
        # The response body can include sensitive account details; never include it in errors.
        raise ProviderError("Claude login expired; sign in again in Model settings") from error


class AnthropicOAuthProvider:
    def __init__(
        self,
        *,
        credentials_path: Path,
        model: str,
        max_tokens: int,
        effort: Effort | None,
    ) -> None:
        self._path = credentials_path
        self._model = model
        self._max_tokens = max_tokens
        self._effort: Effort | None = effort
        self._refresh_lock = asyncio.Lock()
        load_credentials(credentials_path)

    async def token(self) -> str:
        """A valid access token, refreshed when it is about to expire."""
        async with self._refresh_lock:
            credentials = await asyncio.to_thread(load_credentials, self._path)
            if credentials.expires <= time.time() + REFRESH_MARGIN_S:
                credentials = await asyncio.to_thread(_refresh, credentials.refresh)
                await asyncio.to_thread(save_credentials, self._path, credentials)
            return credentials.access

    async def stream(
        self, request: LlmRequest, *, cancel: asyncio.Event
    ) -> AsyncIterator[LlmEvent]:
        token = await self.token()
        client = AsyncAnthropic(
            api_key=None,
            auth_token=token,
            max_retries=0,
        )
        try:
            provider = AnthropicProvider(
                api_key=token,
                model=self._model,
                max_tokens=self._max_tokens,
                effort=self._effort,
                client=client,
                oauth=True,
            )
            async for event in provider.stream(request, cancel=cancel):
                yield event
        finally:
            await client.close()
