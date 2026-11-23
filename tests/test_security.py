import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from common import auth


@pytest.fixture
def signing(monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(
        auth,
        "jwks_client",
        lambda: SimpleNamespace(
            get_signing_key_from_jwt=lambda token: SimpleNamespace(
                key=private.public_key()
            )
        ),
    )
    claims = {
        "iss": auth.ISSUER,
        "sub": "patient-1",
        "aud": auth.AUDIENCE,
        "exp": int(time.time()) + 120,
        "iat": int(time.time()),
        "typ": "Bearer",
        "azp": auth.CLIENT_ID,
        "realm_access": {"roles": [auth.REPORT_ROLE]},
    }
    return private, claims


def test_valid_access_token(signing):
    private, claims = signing
    result = auth.verify_token(jwt.encode(claims, private, algorithm="RS256"))
    assert result["sub"] == "patient-1"
    auth.require_report_role(result)


@pytest.mark.parametrize(
    "field,value",
    [
        ("iss", "https://attacker.example/realm"),
        ("aud", "another-api"),
        ("exp", 1),
        ("typ", "ID"),
        ("azp", "other-client"),
        ("sub", ""),
    ],
)
def test_reject_invalid_claims(signing, field, value):
    private, claims = signing
    claims[field] = value
    with pytest.raises(HTTPException) as error:
        auth.verify_token(jwt.encode(claims, private, algorithm="RS256"))
    assert error.value.status_code == 401


def test_reject_forged_signature(signing):
    _, claims = signing
    foreign = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(HTTPException) as error:
        auth.verify_token(jwt.encode(claims, foreign, algorithm="RS256"))
    assert error.value.status_code == 401


@pytest.mark.parametrize("roles", [[], ["administrator"], ["user"]])
def test_roles_do_not_override_ownership(roles):
    with pytest.raises(HTTPException) as error:
        auth.require_report_role({"realm_access": {"roles": roles}})
    assert error.value.status_code == 403


def test_id_token_audience_and_type(signing):
    private, claims = signing
    claims.update(aud=auth.CLIENT_ID, typ="ID", nonce="nonce")
    token = jwt.encode(claims, private, algorithm="RS256")
    assert auth.verify_token(token, id_token=True)["nonce"] == "nonce"
    with pytest.raises(HTTPException):
        auth.verify_token(token)


@pytest.mark.parametrize("field", ["exp", "iat", "iss", "sub", "aud"])
def test_required_claims(signing, field):
    private, claims = signing
    del claims[field]
    with pytest.raises(HTTPException) as error:
        auth.verify_token(jwt.encode(claims, private, algorithm="RS256"))
    assert error.value.status_code == 401


@pytest.mark.parametrize(
    "realm_access",
    [
        None,
        [],
        {"roles": None},
        {"roles": "prothetic_user"},
        {"roles": {"prothetic_user": True}},
        {"roles": ["prothetic_user", 1]},
    ],
)
def test_malformed_roles_do_not_grant_access(realm_access):
    with pytest.raises(HTTPException) as error:
        auth.require_report_role({"realm_access": realm_access})
    assert error.value.status_code == 403


@pytest.mark.parametrize("field,value", [("azp", "another-client"), ("typ", "Bearer")])
def test_id_token_must_belong_to_this_client(signing, field, value):
    private, claims = signing
    claims.update(aud=auth.CLIENT_ID, typ="ID")
    claims[field] = value
    with pytest.raises(HTTPException) as error:
        auth.verify_token(jwt.encode(claims, private, algorithm="RS256"), id_token=True)
    assert error.value.status_code == 401
