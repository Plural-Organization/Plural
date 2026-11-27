"""Sealing a blob to one recipient's public key, so a relay that carries it cannot read it.

The sender makes a key pair for the one message (X25519), derives a key from the shared secret
(HKDF-SHA256) and encrypts with ChaCha20-Poly1305. The recipient needs only its own private key."""

import os
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from plural.security.tokens import b64decode, b64encode

KEY_BYTES: Final = 32
NONCE_BYTES: Final = 12
_INFO: Final = b"plural.seal.v1"


class SealError(Exception):
    pass


class SealKey:
    """A recipient's key pair for one transfer. The private half never leaves the process."""

    def __init__(self, key: X25519PrivateKey | None = None) -> None:
        self._key = key or X25519PrivateKey.generate()

    @property
    def public_b64(self) -> str:
        return b64encode(self._key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))

    def open(self, sealed: bytes) -> bytes:
        if len(sealed) < KEY_BYTES + NONCE_BYTES + 16:
            raise SealError("the sealed data is too short")
        sender = X25519PublicKey.from_public_bytes(sealed[:KEY_BYTES])
        nonce = sealed[KEY_BYTES : KEY_BYTES + NONCE_BYTES]
        try:
            return ChaCha20Poly1305(_derive(self._key.exchange(sender))).decrypt(
                nonce, sealed[KEY_BYTES + NONCE_BYTES :], sealed[:KEY_BYTES]
            )
        except InvalidTag as error:
            raise SealError("the sealed data was not made for this key, or was changed") from error


def seal(recipient_b64: str, plaintext: bytes) -> bytes:
    try:
        recipient = X25519PublicKey.from_public_bytes(b64decode(recipient_b64))
    except ValueError as error:
        raise SealError("not a public key") from error
    ephemeral = X25519PrivateKey.generate()
    sender = ephemeral.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    nonce = os.urandom(NONCE_BYTES)
    body = ChaCha20Poly1305(_derive(ephemeral.exchange(recipient))).encrypt(
        nonce, plaintext, sender
    )
    return sender + nonce + body


def _derive(shared: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=KEY_BYTES, salt=None, info=_INFO).derive(shared)
