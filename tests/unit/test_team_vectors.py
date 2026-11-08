import json
from pathlib import Path

from plural.host.team import is_tunnel_host
from plural.security.identity import join_message, request_message, verify_signature

VECTORS = json.loads(
    (
        Path(__file__).resolve().parents[2] / "client" / "test" / "fixtures" / "team-vectors.json"
    ).read_text(encoding="utf-8")
)


def test_every_signed_request_verifies_against_the_public_key() -> None:
    key = VECTORS["identity"]["public_key"]
    for case in VECTORS["requests"]:
        body = bytes.fromhex(case["body_hex"])
        message = request_message(
            case["method"], case["path"], body, case["timestamp"], case["nonce"]
        )
        assert message.decode() == case["message"]
        assert verify_signature(key, message, case["signature"])
        assert case["authorization"].endswith(f"sig={case['signature']}")


def test_every_join_proof_verifies_against_the_public_key() -> None:
    key = VECTORS["identity"]["public_key"]
    for case in VECTORS["joins"]:
        message = join_message(case["url"], case["room"], case["timestamp"], case["nonce"])
        assert message.decode() == case["message"]
        assert verify_signature(key, message, case["proof"]["proof"])


def test_tunnel_hosts_are_told_from_other_hosts() -> None:
    for case in VECTORS["tunnel_hosts"]:
        assert is_tunnel_host(case["host"]) is case["tunnel"], case["host"]
