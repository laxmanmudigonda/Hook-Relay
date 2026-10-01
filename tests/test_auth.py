import hashlib

from hookrelay.api.auth import hash_api_key


def test_api_key_hash_is_sha256_and_does_not_retain_secret() -> None:
    secret = "hr_test_super_secret"

    digest = hash_api_key(secret)

    assert digest == hashlib.sha256(secret.encode()).hexdigest()
    assert secret not in digest
    assert len(digest) == 64
