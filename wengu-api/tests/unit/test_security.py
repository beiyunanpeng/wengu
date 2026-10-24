from app.core.security import hash_pin, verify_pin


def test_pin_roundtrip() -> None:
    stored = hash_pin("123456")

    assert stored.startswith("scrypt$")
    assert "123456" not in stored
    assert verify_pin("123456", stored) is True


def test_wrong_or_malformed_pin() -> None:
    stored = hash_pin("123456")

    assert verify_pin("654321", stored) is False
    assert verify_pin("123456", "not-a-hash") is False
    assert verify_pin("123456", stored.replace("scrypt", "argon2", 1)) is False
