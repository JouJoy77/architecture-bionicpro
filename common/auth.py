import os
from functools import lru_cache

import jwt
from fastapi import HTTPException
from jwt import PyJWKClient


ISSUER = os.environ.get("OIDC_ISSUER", "http://localhost:8081/realms/reports-realm")
INTERNAL_URL = os.environ.get(
    "OIDC_INTERNAL_URL", "http://keycloak:8080/realms/reports-realm"
)
CLIENT_ID = "reports-frontend"
AUDIENCE = "reports-api"
REPORT_ROLE = "prothetic_user"  # Название сохранено из исходного realm.


@lru_cache
def jwks_client():
    return PyJWKClient(
        f"{INTERNAL_URL}/protocol/openid-connect/certs", lifespan=300, timeout=5
    )


def verify_token(token: str, *, id_token: bool = False) -> dict:
    try:
        key = jwks_client().get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=ISSUER,
            audience=CLIENT_ID if id_token else AUDIENCE,
            options={"require": ["exp", "iat", "iss", "sub", "aud"]},
            leeway=5,
        )
        if (
            not claims["sub"]
            or claims.get("azp") != CLIENT_ID
            or claims.get("typ") != ("ID" if id_token else "Bearer")
        ):
            raise jwt.InvalidTokenError("Unexpected token type or client")
        return claims
    except jwt.PyJWKClientConnectionError as exc:
        raise HTTPException(503, "Сервис входа временно недоступен") from exc
    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        raise HTTPException(401, "Сессия недействительна. Войдите снова") from exc


def has_report_role(claims: dict) -> bool:
    realm_access = claims.get("realm_access", {})
    if not isinstance(realm_access, dict):
        return False
    roles = realm_access.get("roles", [])
    return (
        isinstance(roles, list)
        and all(isinstance(role, str) for role in roles)
        and REPORT_ROLE in roles
    )


def require_report_role(claims: dict) -> None:
    if not has_report_role(claims):
        raise HTTPException(403, "Для этой учетной записи отчеты недоступны")
