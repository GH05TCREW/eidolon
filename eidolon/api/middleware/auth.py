from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from eidolon.config.settings import AuthSettings, get_settings


@dataclass
class IdentityContext:
    user_id: str
    roles: list[str] = field(default_factory=lambda: ["viewer"])
    claims: dict[str, Any] = field(default_factory=dict)

    def has_role(self, role: str) -> bool:
        return role in self.roles


class AuthError(RuntimeError):
    pass


def _parse_roles(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(role).strip() for role in value if str(role).strip()]
    if isinstance(value, str):
        normalized = value.replace(",", " ")
        return [role for role in (item.strip() for item in normalized.split()) if role]
    return []


def _b64url_decode(segment: str) -> bytes:
    padded = segment + "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8"))


def extract_bearer_token(headers: Mapping[str, str]) -> str | None:
    auth_header = headers.get("authorization") or headers.get("Authorization")
    if not auth_header:
        return None
    parts = auth_header.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


def _verify_jwt(token: str, settings: AuthSettings) -> dict[str, Any]:
    if not settings.jwt_secret:
        raise AuthError("JWT secret not configured")
    parts = token.split(".")
    if len(parts) != 3:
        raise AuthError("invalid token format")
    try:
        header = json.loads(_b64url_decode(parts[0]).decode("utf-8"))
        payload = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise AuthError("invalid token payload") from exc
    if header.get("alg") != "HS256":
        raise AuthError("unsupported JWT algorithm")
    signing_input = f"{parts[0]}.{parts[1]}".encode()
    expected_sig = hmac.new(
        settings.jwt_secret.encode("utf-8"),
        signing_input,
        hashlib.sha256,
    ).digest()
    actual_sig = _b64url_decode(parts[2])
    if not hmac.compare_digest(actual_sig, expected_sig):
        raise AuthError("invalid token signature")
    now = int(time.time())
    exp = payload.get("exp")
    if isinstance(exp, (int, float)) and int(exp) < now:
        raise AuthError("token expired")
    nbf = payload.get("nbf")
    if isinstance(nbf, (int, float)) and int(nbf) > now:
        raise AuthError("token not yet valid")
    if settings.jwt_issuer and payload.get("iss") != settings.jwt_issuer:
        raise AuthError("token issuer mismatch")
    if settings.jwt_audience:
        aud = payload.get("aud")
        if isinstance(aud, list):
            if settings.jwt_audience not in [str(item) for item in aud]:
                raise AuthError("token audience mismatch")
        elif aud is None or str(aud) != settings.jwt_audience:
            raise AuthError("token audience mismatch")
    return payload


def resolve_identity(
    headers: Mapping[str, str],
    settings: AuthSettings,
    token: str | None = None,
) -> tuple[IdentityContext | None, str | None]:
    if settings.mode == "none":
        return IdentityContext(user_id="anonymous", roles=["viewer", "planner", "executor"]), None
    if settings.mode == "header":
        user_id = headers.get(settings.header_user_id, "anonymous")
        roles_header = headers.get(settings.header_roles, "viewer")
        roles = _parse_roles(roles_header) or ["viewer"]
        return IdentityContext(user_id=user_id, roles=roles), None

    bearer = token or extract_bearer_token(headers)
    if not bearer:
        return None, "missing bearer token"
    try:
        claims = _verify_jwt(bearer, settings)
    except AuthError as exc:
        return None, str(exc)
    roles = _parse_roles(claims.get("roles") or claims.get("role") or claims.get("scope"))
    if not roles:
        roles = ["viewer"]
    user_id = str(claims.get("sub") or claims.get("user_id") or claims.get("uid") or "anonymous")
    return IdentityContext(user_id=user_id, roles=roles, claims=claims), None


class AuthMiddleware(BaseHTTPMiddleware):
    """Attach identity to request.state using configured auth mode."""

    async def dispatch(self, request: Request, call_next):
        settings = get_settings().auth
        identity, error = resolve_identity(request.headers, settings)
        if identity:
            request.state.identity = identity
        if error:
            request.state.auth_error = error
        response = await call_next(request)
        return response
