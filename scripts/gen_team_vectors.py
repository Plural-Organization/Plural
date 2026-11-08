import json
import sys
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from plural.host.team import is_tunnel_host
from plural.security.identity import (
    Identity,
    authorization,
    build_team_proof,
    join_message,
    request_message,
)

OUTPUT = Path(__file__).resolve().parents[1] / "client" / "test" / "fixtures" / "team-vectors.json"

SEED = bytes(range(32))
PKCS8_PREFIX = bytes.fromhex("302e020100300506032b657004220420")
CERTIFICATE = "eyJ0ZXN0IjoxfQ.c2ln"
TIMESTAMP = 1767225600
NONCE = "0011223344556677"

REQUESTS = (
    ("GET", "/teams/t_1/sessions", b""),
    ("POST", "/teams/t_1/invites", b""),
    ("post", "/teams/t_1/members", '{"name":"Алия","role":"member"}'.encode()),
)
JOINS = (
    ("wss://relay.example.com/r_abc", "r_abc"),
    ("wss://127.0.0.1:8787/r_x?token=1", "r_x"),
)
TUNNEL_HOSTS = (
    "abc.trycloudflare.com",
    "ABC.Ngrok-Free.App:443",
    "x.ngrok-free.dev",
    "x.ngrok.io",
    "x.loca.lt",
    "relay.example.com",
    "relay.example.com:8787",
    "mytrycloudflare.com",
    "trycloudflare.com",
    "127.0.0.1:8787",
)


def render() -> str:
    identity = Identity(Ed25519PrivateKey.from_private_bytes(SEED))
    document: dict[str, Any] = {
        "identity": {
            "seed_hex": SEED.hex(),
            "pkcs8_hex": (PKCS8_PREFIX + SEED).hex(),
            "public_key": identity.public_b64,
            "member_id": identity.member_id,
        },
        "certificate": CERTIFICATE,
        "requests": [
            {
                "method": method,
                "path": path,
                "body_hex": body.hex(),
                "timestamp": TIMESTAMP,
                "nonce": NONCE,
                "message": request_message(method, path, body, TIMESTAMP, NONCE).decode(),
                "signature": identity.sign(request_message(method, path, body, TIMESTAMP, NONCE)),
                "authorization": authorization(
                    identity, CERTIFICATE, method, path, body, timestamp=TIMESTAMP, nonce=NONCE
                ),
            }
            for method, path, body in REQUESTS
        ],
        "joins": [
            {
                "url": url,
                "room": room,
                "timestamp": TIMESTAMP,
                "nonce": NONCE,
                "message": join_message(url, room, TIMESTAMP, NONCE).decode(),
                "proof": build_team_proof(
                    identity, CERTIFICATE, url, room, timestamp=TIMESTAMP, nonce=NONCE
                ).model_dump(),
            }
            for url, room in JOINS
        ],
        "tunnel_hosts": [{"host": host, "tunnel": is_tunnel_host(host)} for host in TUNNEL_HOSTS],
    }
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    rendered = render()
    if "--check" in sys.argv:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != rendered:
            print("team vectors are stale: run scripts/gen_team_vectors.py", file=sys.stderr)
            return 1
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
