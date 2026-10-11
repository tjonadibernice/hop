from app.security import hash_password, verify_password

PASSWORD = "correct horse battery staple"


def test_hash_is_not_the_password():
    password_hash = hash_password(PASSWORD)

    assert PASSWORD not in password_hash
    assert password_hash.startswith("$argon2id$")


def test_verify_correct_password():
    assert verify_password(hash_password(PASSWORD), PASSWORD) is True


def test_verify_wrong_password():
    assert verify_password(hash_password(PASSWORD), "wrong password") is False


def test_verify_malformed_hash():
    assert verify_password("not-a-hash", PASSWORD) is False


def test_same_password_different_hashes():
    # Argon2 adds a random salt to every hash
    assert hash_password(PASSWORD) != hash_password(PASSWORD)
