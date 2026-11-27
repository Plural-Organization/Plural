"""A signed statement that a new key now holds a room (ADR 0019)."""

from datetime import datetime, timedelta

from pydantic import ValidationError

from plural.protocol.capability import SuccessionClaims
from plural.security.tokens import TokenSigner, TokenVerifier, b64decode, b64encode

# Long enough for the new host to unpack and open the room, short enough that a handover which did
# not complete cannot be finished after the old host has taken its room back.
STATEMENT_TTL = timedelta(minutes=2)


class InvalidSuccession(Exception):
    pass


def sign_succession(signer: TokenSigner, claims: SuccessionClaims) -> str:
    body = claims.model_dump_json().encode()
    return f"{b64encode(body)}.{signer.prove(body)}"


def read_succession(statement: str) -> SuccessionClaims:
    """The claims of a statement, unchecked: `verify_succession` says whether to believe them."""
    try:
        body_b64, _ = statement.split(".")
        return SuccessionClaims.model_validate_json(b64decode(body_b64))
    except (ValueError, ValidationError) as error:
        raise InvalidSuccession("malformed statement") from error


def verify_succession(
    statement: str, *, room: str, current_key: str, new_key: str, now: datetime
) -> SuccessionClaims:
    """The claims, when `current_key` signed them for this room and successor and they are fresh."""
    claims = read_succession(statement)
    body_b64, signature = statement.split(".")
    if claims.room != room or claims.from_key != current_key or claims.to_key != new_key:
        raise InvalidSuccession("the statement is for another room or another key")
    if claims.exp <= now:
        raise InvalidSuccession("the statement has expired")
    try:
        verifier = TokenVerifier.from_b64(current_key)
    except ValueError as error:
        raise InvalidSuccession("not a public key") from error
    if not verifier.verify_proof(b64decode(body_b64), signature):
        raise InvalidSuccession("the statement was not signed by the room's host")
    return claims
