import base64
from typing import Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# Fixed salt for key derivation — changing this invalidates all encrypted data
_KDF_SALT = b"agno-google-oauth-v1"


def get_fernet(encryption_key: str) -> Fernet:
    # If it's a valid Fernet key (44 chars, base64), use directly
    try:
        return Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)
    except ValueError:
        pass

    # Otherwise treat as passphrase and derive a key via PBKDF2
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=_KDF_SALT, iterations=480_000)
    derived = base64.urlsafe_b64encode(kdf.derive(encryption_key.encode()))
    return Fernet(derived)


def encrypt_data(plaintext: bytes, encryption_key: str) -> bytes:
    return get_fernet(encryption_key).encrypt(plaintext)


def decrypt_data(ciphertext: bytes, encryption_key: str) -> Optional[bytes]:
    from cryptography.fernet import InvalidToken

    try:
        return get_fernet(encryption_key).decrypt(ciphertext)
    except InvalidToken:
        return None


def generate_rsa_keys():
    """Generate RSA key pair for RS256 JWT signing/verification."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    # Private key PEM (used by auth server to sign tokens)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    # Public key PEM (used by AgentOS to verify tokens)
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    return private_pem.decode("utf-8"), public_pem.decode("utf-8")
