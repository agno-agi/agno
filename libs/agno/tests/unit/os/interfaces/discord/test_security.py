import time
from unittest.mock import patch

import pytest

from agno.os.interfaces.discord.security import verify_discord_signature


@pytest.fixture
def ed25519_keypair():
    from nacl.signing import SigningKey

    signing_key = SigningKey.generate()
    verify_key = signing_key.verify_key
    public_key_hex = verify_key.encode().hex()
    return signing_key, public_key_hex


def _sign_request(signing_key, body: bytes, timestamp: str) -> str:
    message = timestamp.encode() + body
    signed = signing_key.sign(message)
    return signed.signature.hex()


class TestVerifyDiscordSignature:
    def test_valid_signature(self, ed25519_keypair):
        signing_key, public_key_hex = ed25519_keypair
        body = b'{"type": 1}'
        timestamp = str(int(time.time()))
        signature = _sign_request(signing_key, body, timestamp)

        with patch("agno.os.interfaces.discord.security.DISCORD_PUBLIC_KEY", public_key_hex):
            assert verify_discord_signature(body, timestamp, signature) is True

    def test_invalid_signature(self, ed25519_keypair):
        _, public_key_hex = ed25519_keypair
        body = b'{"type": 1}'
        timestamp = str(int(time.time()))
        bad_signature = "aa" * 64

        with patch("agno.os.interfaces.discord.security.DISCORD_PUBLIC_KEY", public_key_hex):
            assert verify_discord_signature(body, timestamp, bad_signature) is False

    def test_tampered_body(self, ed25519_keypair):
        signing_key, public_key_hex = ed25519_keypair
        body = b'{"type": 1}'
        timestamp = str(int(time.time()))
        signature = _sign_request(signing_key, body, timestamp)

        with patch("agno.os.interfaces.discord.security.DISCORD_PUBLIC_KEY", public_key_hex):
            assert verify_discord_signature(b'{"type": 2}', timestamp, signature) is False

    def test_replay_protection_old_timestamp(self, ed25519_keypair):
        signing_key, public_key_hex = ed25519_keypair
        body = b'{"type": 1}'
        old_timestamp = str(int(time.time()) - 400)
        signature = _sign_request(signing_key, body, old_timestamp)

        with patch("agno.os.interfaces.discord.security.DISCORD_PUBLIC_KEY", public_key_hex):
            assert verify_discord_signature(body, old_timestamp, signature) is False

    def test_replay_protection_within_window(self, ed25519_keypair):
        signing_key, public_key_hex = ed25519_keypair
        body = b'{"type": 1}'
        recent_timestamp = str(int(time.time()) - 60)
        signature = _sign_request(signing_key, body, recent_timestamp)

        with patch("agno.os.interfaces.discord.security.DISCORD_PUBLIC_KEY", public_key_hex):
            assert verify_discord_signature(body, recent_timestamp, signature) is True

    def test_missing_public_key(self):
        with patch("agno.os.interfaces.discord.security.DISCORD_PUBLIC_KEY", None):
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as exc_info:
                verify_discord_signature(b"body", "123", "abc")
            assert exc_info.value.status_code == 500

    def test_invalid_timestamp_format(self, ed25519_keypair):
        _, public_key_hex = ed25519_keypair
        with patch("agno.os.interfaces.discord.security.DISCORD_PUBLIC_KEY", public_key_hex):
            assert verify_discord_signature(b"body", "not_a_number", "aa" * 64) is False
