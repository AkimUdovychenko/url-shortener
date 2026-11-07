import base64
import hashlib
import re
from uuid import uuid4
import pytest
from fastapi import HTTPException
from app.logic import LIMITS
from app.oauth import validate_client, validate_pkce
from app.security import create_token, hash_password, verify_password
import jwt
from app.config import settings


def test_password_argon2id():
    stored = hash_password("some-long-password")
    assert stored.startswith("$argon2id$")
    assert verify_password("some-long-password", stored)
    assert not verify_password("wrong-password", stored)


def test_jwt():
    token = create_token(42)
    assert jwt.decode(token, settings.secret_key, algorithms=["HS256"])["sub"] == "42"


def test_limits():
    assert LIMITS == {"user": 3, "premium": 5}


def test_pkce_validation():
    verifier = "a" * 64
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    validate_pkce(challenge, "S256")
    with pytest.raises(HTTPException):
        validate_pkce(challenge, "plain")
    with pytest.raises(HTTPException):
        validate_client("swagger-ui", "https://evil.example/docs/oauth2-redirect")
