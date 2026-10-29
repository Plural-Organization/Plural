import pytest
from pydantic import SecretStr

from plural.host.config import HostSettings
from plural.host.routing import build_helper, fast_settings

NO_ENV: dict[str, str] = {}
GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai/"


@pytest.mark.parametrize(
    ("settings", "environ", "expected"),
    [
        (HostSettings(provider="anthropic"), NO_ENV, ("anthropic", "claude-haiku-5-5")),
        (HostSettings(provider="anthropic_oauth"), NO_ENV, ("anthropic_oauth", "claude-haiku-5-5")),
        (HostSettings(provider="openai", model="gpt-5"), NO_ENV, ("openai", "gpt-5-mini")),
        (
            HostSettings(provider="openai", model="gemini-2.5-pro", base_url=GEMINI),
            NO_ENV,
            ("openai", "gemini-2.5-flash"),
        ),
        (
            HostSettings(provider="claude_code"),
            {"ANTHROPIC_API_KEY": "k"},
            ("anthropic", "claude-haiku-5-5"),
        ),
        (HostSettings(provider="codex_cli"), {"OPENAI_API_KEY": "k"}, ("openai", "gpt-5-mini")),
    ],
)
def test_the_fast_role_uses_a_cheaper_model_the_host_can_reach(
    settings: HostSettings, environ: dict[str, str], expected: tuple[str, str]
) -> None:
    fast = fast_settings(settings, environ)
    assert fast is not None
    assert (fast.provider, fast.model) == expected


@pytest.mark.parametrize(
    ("settings", "environ"),
    [
        (HostSettings(provider="anthropic", model="claude-haiku-5-5"), NO_ENV),
        (
            HostSettings(provider="openai", model="x", base_url="https://openrouter.ai/api/v1"),
            NO_ENV,
        ),
        (HostSettings(provider="claude_code"), NO_ENV),
        (HostSettings(provider="fake"), NO_ENV),
    ],
)
def test_there_is_no_fast_role_without_something_cheaper(
    settings: HostSettings, environ: dict[str, str]
) -> None:
    assert fast_settings(settings, environ) is None


def test_an_explicit_fast_model_wins() -> None:
    settings = HostSettings(
        provider="openai",
        model="gpt-5",
        base_url="https://openrouter.ai/api/v1",
        fast_model="qwen/qwen3-coder",
    )
    fast = fast_settings(settings, NO_ENV)
    assert fast is not None
    assert (fast.provider, fast.model, fast.base_url) == (
        "openai",
        "qwen/qwen3-coder",
        settings.base_url,
    )


def test_a_helper_needs_working_credentials() -> None:
    assert build_helper(HostSettings(provider="openai", model="gpt-5"), NO_ENV) is None
    settings = HostSettings(provider="anthropic", api_key=SecretStr("sk-ant-test-key-123"))
    helper = build_helper(settings, NO_ENV)
    assert helper is not None
    assert helper.label == "claude-haiku-5-5"
    assert "sk-ant-test-key-123" in helper.secrets
