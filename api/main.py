import asyncio
import base64
import hashlib
import json
import os
import secrets
import time
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from redis.asyncio import Redis
from redis.exceptions import LockError, RedisError

from common.auth import (
    CLIENT_ID,
    INTERNAL_URL,
    ISSUER,
    has_report_role,
    require_report_role,
    verify_token,
)


app = FastAPI(title="BionicPRO API", docs_url=None, redoc_url=None, openapi_url=None)
PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:3000").rstrip("/")
CALLBACK = f"{PUBLIC_URL}/auth/callback"
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "true").lower() == "true"
SESSION_COOKIE = "__Host-bionicpro" if COOKIE_SECURE else "bionicpro_session"
LOGIN_COOKIE = "__Host-bionicpro-login" if COOKIE_SECURE else "bionicpro_login"
SESSION_TTL = 3600
redis = Redis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379/0"))


def cipher():
    return Fernet(os.environ["SESSION_ENCRYPTION_KEY"].encode())


def session_key(sid: str) -> str:
    return "session:" + hashlib.sha256(sid.encode()).hexdigest()


def pkce_challenge(verifier: str) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )


def set_cookie(response: Response, name: str, value: str, max_age: int):
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


@app.middleware("http")
async def private_responses(request: Request, call_next):
    try:
        response = await call_next(request)
    except RedisError:
        response = JSONResponse(
            {"detail": "Хранилище сессий временно недоступно"}, status_code=503
        )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/auth/login")
async def login():
    state, verifier, nonce = (secrets.token_urlsafe(32) for _ in range(3))
    await redis.setex(
        "login:" + state,
        300,
        cipher().encrypt(
            json.dumps(
                {
                    "verifier": verifier,
                    "nonce": nonce,
                }
            ).encode()
        ),
    )
    query = urlencode(
        {
            "client_id": CLIENT_ID,
            "redirect_uri": CALLBACK,
            "response_type": "code",
            "scope": "openid",
            "state": state,
            "nonce": nonce,
            "code_challenge": pkce_challenge(verifier),
            "code_challenge_method": "S256",
        }
    )
    response = RedirectResponse(
        f"{ISSUER}/protocol/openid-connect/auth?{query}", status_code=302
    )
    set_cookie(response, LOGIN_COOKIE, state, 300)
    return response


async def token_request(data: dict):
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{INTERNAL_URL}/protocol/openid-connect/token",
                data={
                    **data,
                    "client_id": CLIENT_ID,
                    "client_secret": os.environ["BFF_CLIENT_SECRET"],
                },
            )
        if response.status_code in (400, 401):
            raise HTTPException(401, "Не удалось подтвердить вход. Войдите снова")
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, "Сервис входа временно недоступен") from exc


@app.get("/auth/callback")
async def callback(request: Request, state: str = "", code: str = "", error: str = ""):
    cookie_state = request.cookies.get(LOGIN_COOKIE, "")
    if (
        not state
        or not cookie_state
        or not secrets.compare_digest(state.encode(), cookie_state.encode())
    ):
        raise HTTPException(400, "Некорректное состояние входа")
    raw = await redis.getdel("login:" + state)
    if not raw or error or not code:
        raise HTTPException(400, "Вход не завершен или время ожидания истекло")
    transaction = json.loads(cipher().decrypt(raw))
    tokens = await token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": CALLBACK,
            "code_verifier": transaction["verifier"],
        }
    )
    identity = await asyncio.to_thread(verify_token, tokens["id_token"], id_token=True)
    if identity.get("nonce") != transaction["nonce"]:
        raise HTTPException(401, "Некорректный ответ сервиса входа")
    claims = await asyncio.to_thread(verify_token, tokens["access_token"])
    if claims["sub"] != identity["sub"]:
        raise HTTPException(401, "Некорректный ответ сервиса входа")
    old_sid = request.cookies.get(SESSION_COOKIE)
    if old_sid:
        await redis.delete(session_key(old_sid))
    sid = secrets.token_urlsafe(32)
    session = {
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "sub": claims["sub"],
        "expires_at": time.time() + tokens["expires_in"],
        "deadline": time.time() + SESSION_TTL,
        "csrf": secrets.token_urlsafe(32),
    }
    await redis.setex(
        session_key(sid), SESSION_TTL, cipher().encrypt(json.dumps(session).encode())
    )
    response = RedirectResponse("/", status_code=303)
    set_cookie(response, SESSION_COOKIE, sid, SESSION_TTL)
    response.delete_cookie(
        LOGIN_COOKIE, path="/", secure=COOKIE_SECURE, httponly=True, samesite="lax"
    )
    return response


async def get_session(request: Request):
    sid = request.cookies.get(SESSION_COOKIE, "")
    if not sid:
        raise HTTPException(401, "Сначала войдите в приложение")
    key = session_key(sid)
    try:
        # Сериализация обновления нужна из-за одноразового refresh-токена.
        async with redis.lock(key + ":lock", timeout=45, blocking_timeout=12):
            raw = await redis.get(key)
            if not raw:
                raise HTTPException(401, "Сессия завершена. Войдите снова")
            session = json.loads(cipher().decrypt(raw))
            remaining = int(session["deadline"] - time.time())
            if remaining <= 0:
                await redis.delete(key)
                raise HTTPException(401, "Сессия завершена. Войдите снова")
            if session["expires_at"] < time.time() + 30:
                try:
                    tokens = await token_request(
                        {
                            "grant_type": "refresh_token",
                            "refresh_token": session["refresh_token"],
                        }
                    )
                    claims = await asyncio.to_thread(
                        verify_token, tokens["access_token"]
                    )
                    if claims["sub"] != session["sub"]:
                        raise HTTPException(401, "Учетная запись изменилась")
                except HTTPException as exc:
                    if exc.status_code == 401:
                        await redis.delete(key)
                    raise
                session.update(
                    access_token=tokens["access_token"],
                    refresh_token=tokens["refresh_token"],
                    expires_at=time.time() + tokens["expires_in"],
                )
                await redis.setex(
                    key, remaining, cipher().encrypt(json.dumps(session).encode())
                )
    except LockError as exc:
        raise HTTPException(503, "Сессия обновляется. Повторите запрос") from exc
    claims = await asyncio.to_thread(verify_token, session["access_token"])
    return session, claims


@app.get("/auth/session")
async def session_info(request: Request):
    session, claims = await get_session(request)
    return {
        "username": claims.get("preferred_username", "Пользователь"),
        "can_report": has_report_role(claims),
        "csrf_token": session["csrf"],
    }


@app.post("/auth/logout")
async def logout(request: Request):
    if request.headers.get("origin") != PUBLIC_URL:
        raise HTTPException(403, "Не удалось проверить запрос")
    sid = request.cookies.get(SESSION_COOKIE)
    session = None
    if sid:
        key = session_key(sid)
        try:
            # Выход не требует действующего access-токена и доступности IdP.
            # Общая блокировка с refresh исключает восстановление удаленной сессии.
            async with redis.lock(key + ":lock", timeout=45, blocking_timeout=12):
                raw = await redis.get(key)
                if raw:
                    session = json.loads(cipher().decrypt(raw))
                    if not secrets.compare_digest(
                        request.headers.get("x-csrf-token", "").encode(),
                        session["csrf"].encode(),
                    ):
                        raise HTTPException(403, "Не удалось проверить запрос")
                    await redis.delete(key)
        except LockError as exc:
            raise HTTPException(503, "Сессия обновляется. Повторите запрос") from exc
    if session:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"{INTERNAL_URL}/protocol/openid-connect/logout",
                    data={
                        "client_id": CLIENT_ID,
                        "client_secret": os.environ["BFF_CLIENT_SECRET"],
                        "refresh_token": session["refresh_token"],
                    },
                )
        except httpx.HTTPError:
            pass  # Локальная сессия уже закрыта, cookie все равно удаляем.
    response = Response(status_code=204)
    response.delete_cookie(
        SESSION_COOKIE, path="/", secure=COOKIE_SECURE, httponly=True, samesite="lax"
    )
    return response


async def proxy_report(request: Request, path: str):
    session, claims = await get_session(request)
    require_report_role(claims)
    try:
        async with httpx.AsyncClient(timeout=35) as client:
            upstream = await client.get(
                os.environ.get("REPORTS_URL", "http://reports:8000") + path,
                params=request.query_params.multi_items(),
                headers={"Authorization": "Bearer " + session["access_token"]},
            )
        if upstream.status_code >= 500:
            raise HTTPException(
                503, "Отчеты временно недоступны. Повторите запрос позже"
            )
        headers = {
            key: upstream.headers[key]
            for key in ("content-disposition", "content-type")
            if key in upstream.headers
        }
        return Response(
            upstream.content, status_code=upstream.status_code, headers=headers
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            503, "Отчеты временно недоступны. Повторите запрос позже"
        ) from exc


@app.get("/reports")
async def reports(request: Request):
    return await proxy_report(request, "/reports")


@app.get("/reports/availability")
async def availability(request: Request):
    return await proxy_report(request, "/reports/availability")
