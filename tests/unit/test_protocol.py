import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from plural.protocol.codec import ProtocolError, decode_command, encode_command
from plural.protocol.commands import PromptSubmit
from plural.protocol.envelope import Envelope, ErrorCode, Kind
from plural.protocol.models import Delivery

FIXTURES = Path(__file__).parents[1] / "fixtures" / "protocol"
TS = datetime(2026, 10, 22, 12, tzinfo=UTC)


def _envelope(**overrides: object) -> Envelope:
    base: dict[str, object] = {
        "id": "01JB8X2K7Q",
        "kind": Kind.CMD,
        "type": "prompt.submit",
        "room": "r_7f3a",
        "ts": TS,
        "payload": {"text": "hi"},
    }
    return Envelope.model_validate({**base, **overrides})


def test_command_roundtrip() -> None:
    command = PromptSubmit(text="run the tests", delivery=Delivery.STEER)
    envelope = encode_command(command, envelope_id="01J", room="r_1", ts=TS, token="tok")
    restored = Envelope.model_validate_json(envelope.model_dump_json())
    assert decode_command(restored) == command


def test_prompt_submit_matches_golden() -> None:
    command = PromptSubmit(text="run the tests")
    envelope = encode_command(command, envelope_id="01JB8X2K7Q", room="r_7f3a", ts=TS, token="tok")
    golden = json.loads((FIXTURES / "prompt_submit.json").read_text())
    assert envelope.model_dump(mode="json") == golden


def test_unknown_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        decode_command(_envelope(type="nope"))


def test_unknown_fields_are_ignored() -> None:
    command = decode_command(_envelope(payload={"text": "hi", "future": 1}))
    assert command == PromptSubmit(text="hi")


def test_version_mismatch() -> None:
    with pytest.raises(ProtocolError) as info:
        decode_command(_envelope(v=99))
    assert info.value.code is ErrorCode.VERSION_MISMATCH
