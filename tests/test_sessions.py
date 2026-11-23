import json
import time
from contextlib import asynccontextmanager

import pytest
import httpx
from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api import main


class SessionRedis:
    def __init__(self, value):
        self.value = value

    @asynccontextmanager
    async def lock(self, *args, **kwargs):
        yield

    async def get(self, key):
        return self.value

    async def setex(self, key, ttl, value):
        assert 0 < ttl <= 3600
        self.value = value

    async def delete(self, key):
        self.value = None


@pytest.fixture
def context(monkeypatch):
    monkeypatch.setenv("SESSION_ENCRYPTION_KEY", Fernet.generate_key().decode())
    session = {
        "sub": "patient-1",
        "access_token": "old-access",
        "refresh_token": "old-refresh",
        "expires_at": time.time() - 1,
        "deadline": time.time() + 3500,
        "csrf": "csrf",
    }
    store = SessionRedis(main.cipher().encrypt(json.dumps(session).encode()))
    monkeypatch.setattr(main, "redis", store)
    monkeypatch.setattr(
        main,
        "verify_token",
        lambda token: {
            "sub": "patient-1",
            "realm_access": {"roles": ["prothetic_user"]},
        },
    )
    with TestClient(main.app, cookies={main.SESSION_COOKIE: "session-id"}) as client:
        yield client, store, session


def test_refresh_replaces_both_tokens_and_keeps_deadline(context, monkeypatch):
    client, store, original = context
    requests = []

    async def token_request(data):
        requests.append(data)
        return {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 120,
        }

    monkeypatch.setattr(main, "token_request", token_request)
    assert client.get("/auth/session").status_code == 200
    assert client.get("/auth/session").status_code == 200
    assert requests == [{"grant_type": "refresh_token", "refresh_token": "old-refresh"}]
    saved = json.loads(main.cipher().decrypt(store.value))
    assert saved["refresh_token"] == "new-refresh"
    assert saved["access_token"] == "new-access"
    assert saved["deadline"] == original["deadline"]
    assert "new-access" not in client.get("/auth/session").text


def test_revoked_refresh_removes_session(context, monkeypatch):
    client, store, _ = context

    async def token_request(data):
        raise HTTPException(401, "Refresh rejected")

    monkeypatch.setattr(main, "token_request", token_request)
    assert client.get("/auth/session").status_code == 401
    assert store.value is None


def test_idp_outage_does_not_destroy_session(context, monkeypatch):
    client, store, _ = context

    async def token_request(data):
        raise HTTPException(503, "IdP unavailable")

    monkeypatch.setattr(main, "token_request", token_request)
    assert client.get("/auth/session").status_code == 503
    assert store.value is not None


def test_expired_session_cannot_be_refreshed(context):
    client, store, session = context
    session["deadline"] = time.time() - 1
    store.value = main.cipher().encrypt(json.dumps(session).encode())
    assert client.get("/auth/session").status_code == 401
    assert store.value is None


def test_logout_works_with_expired_access_token_and_unavailable_idp(
    context, monkeypatch
):
    client, store, session = context
    monkeypatch.setenv("BFF_CLIENT_SECRET", "test-secret")
    requests = []
    async_client = httpx.AsyncClient

    def offline(request):
        requests.append(request.url.path)
        raise httpx.ConnectError("IdP is offline", request=request)

    monkeypatch.setattr(
        main.httpx,
        "AsyncClient",
        lambda **kwargs: async_client(transport=httpx.MockTransport(offline), **kwargs),
    )
    response = client.post(
        "/auth/logout",
        headers={
            "Origin": main.PUBLIC_URL,
            "X-CSRF-Token": session["csrf"],
        },
    )
    assert response.status_code == 204
    assert store.value is None
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert requests == ["/realms/reports-realm/protocol/openid-connect/logout"]
    assert client.get("/auth/session").status_code == 401


@pytest.mark.parametrize(
    "origin,csrf",
    [
        (None, None),
        ("https://foreign.example", "csrf"),
        (main.PUBLIC_URL, "wrong"),
    ],
)
def test_logout_rejects_invalid_origin_or_csrf_before_contacting_idp(
    context, monkeypatch, origin, csrf
):
    client, store, _ = context

    def unexpected_call(**kwargs):
        pytest.fail("Invalid logout request must not contact the IdP")

    monkeypatch.setattr(main.httpx, "AsyncClient", unexpected_call)
    headers = {}
    if origin:
        headers["Origin"] = origin
    if csrf:
        headers["X-CSRF-Token"] = csrf
    assert client.post("/auth/logout", headers=headers).status_code == 403
    assert store.value is not None
