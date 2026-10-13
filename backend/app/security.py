import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

hasher = PasswordHasher()

# A real Argon2 hash of a random value. Login checks unknown emails against it,
# so a missing account takes as long to reject as a wrong password.
DUMMY_PASSWORD_HASH = hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        hasher.verify(password_hash, password)
        return True
    except (VerifyMismatchError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """True if the hash was made with older Argon2 settings than the current ones."""
    return hasher.check_needs_rehash(password_hash)


def generate_token() -> str:
    """A random, URL-safe token with 256 bits of randomness."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA-256 hex digest of a token, for storing tokens without storing them."""
    return hashlib.sha256(token.encode()).hexdigest()
