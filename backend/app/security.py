from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

hasher = PasswordHasher()


def hash_password(password: str) -> str:
	return hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
	try:
		hasher.verify(password_hash, password)
		return True
	except (VerifyMismatchError, InvalidHashError):
		return False