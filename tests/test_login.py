import json
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from api import main


class MemoryRedis:
    def __init__(self):
        self.values = {}

    async def setex(self, key, ttl, value):
        self.values[key] = value

    async def getdel(self, key):
        return self.values.pop(key, None)

    async def delete(self, key):
        self.values.pop(key, None)


@pytest.fixture
def login_client(monkeypatch):
    monkeypatch.setenv("SESSION_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(main, "COOKIE_SECURE", False)
    monkeypatch.setattr(main, "redis", MemoryRedis())
    with TestClient(main.app, follow_redirects=False) as client:
        yield client


def test_pkce_rfc7636_vector():
    assert main.pkce_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == (
        "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    )


def test_login_uses_s256_and_hides_verifier(login_client):
    response = login_client.get("/auth/login")
    params = parse_qs(urlsplit(response.headers["location"]).query)
    assert params["code_challenge_method"] == ["S256"]
    assert params["response_type"] == ["code"]
    assert "code_verifier" not in params
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]
    saved = json.loads(
        main.cipher().decrypt(main.redis.values["login:" + params["state"][0]])
    )
    assert params["code_challenge"] == [main.pkce_challenge(saved["verifier"])]


def test_callback_rejects_wrong_state(login_client):
    login_client.get("/auth/login")
    assert (
        login_client.get("/auth/callback?state=foreign&code=stolen").status_code == 400
    )


def test_callback_rejects_non_ascii_state(login_client):
    login_client.get("/auth/login")
    assert (
        login_client.get(
            "/auth/callback", params={"state": "чужой", "code": "code"}
        ).status_code
        == 400
    )


def test_code_exchange_and_one_time_state(login_client, monkeypatch):
    login = login_client.get("/auth/login")
    params = parse_qs(urlsplit(login.headers["location"]).query)
    state = params["state"][0]
    saved = json.loads(main.cipher().decrypt(main.redis.values["login:" + state]))

    async def token_request(data):
        assert data["code_verifier"] == saved["verifier"]
        assert data["grant_type"] == "authorization_code"
        return {
            "id_token": "id-secret",
            "access_token": "access-secret",
            "refresh_token": "refresh-secret",
            "expires_in": 120,
        }

    monkeypatch.setattr(main, "token_request", token_request)
    monkeypatch.setattr(
        main,
        "verify_token",
        lambda *args, **kwargs: {"sub": "patient", "nonce": saved["nonce"]},
    )
    response = login_client.get(f"/auth/callback?state={state}&code=code")
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "access-secret" not in str(response.headers)
    assert "refresh-secret" not in response.text
    assert (
        login_client.get(f"/auth/callback?state={state}&code=code").status_code == 400
    )
