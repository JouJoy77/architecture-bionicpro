"""Проверка работающего стенда настоящим Authorization Code + PKCE flow."""

import argparse
import base64
import hashlib
import secrets
import time
from contextlib import closing
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx


BASE = "http://localhost:3000"


class LoginForm(HTMLParser):
    action = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form" and attrs.get("id") == "kc-form-login":
            self.action = attrs["action"]


def submit_login(client, response, username, password):
    response.raise_for_status()
    form = LoginForm()
    form.feed(response.text)
    assert form.action, "Keycloak login form is missing"
    # Браузеры разрешают Secure cookies на localhost по HTTP, httpx этого не делает.
    # Повторяем поведение браузера только для фиксированного локального стенда.
    for cookie in client.cookies.jar:
        if cookie.domain == "localhost.local":
            cookie.secure = False
    return client.post(
        form.action,
        data={"username": username, "password": password, "credentialId": ""},
    )


def sign_in(username, password):
    client = httpx.Client(base_url=BASE, follow_redirects=True, timeout=40)
    response = submit_login(client, client.get("/auth/login"), username, password)
    response.raise_for_status()
    session = client.get("/auth/session")
    assert session.status_code == 200, (
        f"Login failed for {username}: {session.status_code}"
    )
    assert set(session.json()) == {"username", "can_report", "csrf_token"}
    return closing(client)


def reject_wrong_verifier():
    # Проверка confidential client требует его локального секрета.
    # Секрет и полученный код не выводятся в результат теста.
    env = dict(
        line.split("=", 1)
        for line in (Path(__file__).resolve().parents[1] / ".env")
        .read_text()
        .splitlines()
        if "=" in line and not line.startswith("#")
    )
    issuer = "http://localhost:8081/realms/reports-realm"
    verifier = secrets.token_urlsafe(32)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    with httpx.Client(follow_redirects=False, timeout=40) as client:
        authorization = client.get(
            issuer + "/protocol/openid-connect/auth",
            params={
                "client_id": "reports-frontend",
                "redirect_uri": BASE + "/auth/callback",
                "response_type": "code",
                "scope": "openid",
                "state": secrets.token_urlsafe(32),
                "nonce": secrets.token_urlsafe(32),
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        callback = submit_login(client, authorization, "prothetic1", "prothetic123")
        assert callback.status_code == 302
        code = parse_qs(urlsplit(callback.headers["location"]).query)["code"][0]
        response = client.post(
            issuer + "/protocol/openid-connect/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": "x" * 43,
                "client_id": "reports-frontend",
                "client_secret": env["BFF_CLIENT_SECRET"],
                "redirect_uri": BASE + "/auth/callback",
            },
        )
        assert (
            response.status_code == 400 and response.json()["error"] == "invalid_grant"
        )
    print("PASS: Keycloak rejects a valid code with the wrong PKCE verifier")


def main(wait_refresh):
    anonymous = httpx.get(BASE + "/reports")
    assert anonymous.status_code == 401
    print("PASS: anonymous request rejected")
    with httpx.Client(follow_redirects=False) as client:
        login = client.get(BASE + "/auth/login")
        params = parse_qs(urlsplit(login.headers["location"]).query)
        assert params["code_challenge_method"] == ["S256"]
        params = {
            k: v[0]
            for k, v in params.items()
            if k not in ("code_challenge", "code_challenge_method")
        }
        rejected = client.get(
            "http://localhost:8081/realms/reports-realm/protocol/openid-connect/auth",
            params=params,
        )
        assert (
            rejected.status_code == 400
            or "error=invalid_request" in rejected.headers.get("location", "")
        )
    print("PASS: Keycloak rejects authorization without PKCE")
    reject_wrong_verifier()

    with sign_in("prothetic1", "prothetic123") as first:
        coverage = first.get("/reports/availability")
        assert coverage.status_code == 200
        dates = coverage.json()["available_dates"]
        assert dates, "Airflow has not published a completed day yet"
        params = {"start_date": dates[0], "end_date": dates[0]}
        response = first.get("/reports", params=params)
        assert response.status_code == 200, response.text
        assert {r["device_id"] for r in response.json()["rows"]} == {"BP-101", "BP-102"}
        assert all(
            r["events_count"] == 12 and r["movements_count"] == 8
            for r in response.json()["rows"]
        )
        csv = first.get("/reports", params={**params, "format": "csv"})
        assert (
            csv.status_code == 200
            and "attachment" in csv.headers["content-disposition"]
        )
        assert "BP-201" not in csv.text
        for key in ("user_id", "subject", "device_id"):
            assert (
                first.get("/reports", params={**params, key: "customer-2"}).status_code
                == 400
            )
        today = datetime.now(timezone.utc).date().isoformat()
        assert (
            first.get(
                "/reports", params={"start_date": today, "end_date": today}
            ).status_code
            == 409
        )
        print(
            "PASS: two own devices, correct totals, CSV, forbidden selectors, unfinished period"
        )

        if wait_refresh:
            print(
                "Waiting 125 seconds to verify a real refresh-token exchange...",
                flush=True,
            )
            time.sleep(125)
            refreshed = first.get("/reports", params=params)
            assert refreshed.status_code == 200
            print("PASS: server refreshes expired access token")

        session = first.get("/auth/session").json()
        assert first.post("/auth/logout").status_code == 403
        assert (
            first.post(
                "/auth/logout",
                headers={"Origin": BASE, "X-CSRF-Token": session["csrf_token"]},
            ).status_code
            == 204
        )
        assert first.get("/reports", params=params).status_code == 401
        print("PASS: logout requires CSRF and invalidates session")

    with sign_in("prothetic2", "prothetic123") as second:
        report = second.get("/reports", params=params)
        assert report.status_code == 200
        assert {r["device_id"] for r in report.json()["rows"]} == {"BP-201"}
        print("PASS: second user sees only their own device")
    with sign_in("prothetic3", "prothetic123") as third:
        report = third.get("/reports", params=params)
        assert report.status_code == 200 and report.json()["rows"] == []
        print("PASS: user without telemetry gets an empty completed report")
    for username, password in (("user1", "password123"), ("admin1", "admin123")):
        with sign_in(username, password) as user:
            assert user.get("/reports", params=params).status_code == 403
            print(f"PASS: {username} cannot bypass report role")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--wait-refresh", action="store_true")
    main(parser.parse_args().wait_refresh)
