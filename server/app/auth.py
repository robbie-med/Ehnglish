"""Identity from Cloudflare Access.

Cloudflare Access sits in front of the tunnel and adds `Cf-Access-Jwt-Assertion` (a signed JWT)
to every request. We verify it against the team's public keys and take the email claim. In dev
and test a fixed EHNGLISH_DEV_EMAIL stands in, mirroring the diet-logger convention on this box.
"""

from __future__ import annotations

import time

import httpx
import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .db import get_db
from .models import User

_JWKS_CACHE: dict[str, tuple[float, dict]] = {}
_JWKS_TTL_S = 3600


def fetch_jwks(team_domain: str) -> dict:
    now = time.time()
    hit = _JWKS_CACHE.get(team_domain)
    if hit and now - hit[0] < _JWKS_TTL_S:
        return hit[1]
    url = f"https://{team_domain}.cloudflareaccess.com/cdn-cgi/access/certs"
    resp = httpx.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    _JWKS_CACHE[team_domain] = (now, data)
    return data


def verify_access_jwt(token: str, settings: Settings) -> str:
    if not settings.cf_access_team_domain or not settings.cf_access_aud:
        raise HTTPException(500, "Cloudflare Access is not configured on the server")
    try:
        header = jwt.get_unverified_header(token)
        jwks = fetch_jwks(settings.cf_access_team_domain)
        key = next((k for k in jwks.get("keys", []) if k.get("kid") == header.get("kid")), None)
        if key is None:
            _JWKS_CACHE.pop(settings.cf_access_team_domain, None)  # key rotation: refetch next time
            raise HTTPException(401, "unknown signing key")
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
        claims = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=settings.cf_access_aud,
            issuer=f"https://{settings.cf_access_team_domain}.cloudflareaccess.com",
        )
    except HTTPException:
        raise
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"invalid Access token: {e}") from e
    email = claims.get("email")
    if not email:
        raise HTTPException(401, "Access token carries no email")
    return str(email).lower()


def resolve_email(request: Request, settings: Settings) -> str:
    token = request.headers.get("cf-access-jwt-assertion")
    if token:
        email = verify_access_jwt(token, settings)
    elif settings.env in ("dev", "test") and settings.dev_email:
        email = settings.dev_email.lower()
    else:
        raise HTTPException(401, "not authenticated (no Cloudflare Access token)")
    allowed = settings.allowed_email_set
    if allowed and email not in allowed:
        raise HTTPException(403, "email not on the allow list")
    return email


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    email = resolve_email(request, settings)
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        # Concurrent first requests (the PWA fires several at once) must not race on the insert.
        db.execute(
            insert(User).values(email=email).on_conflict_do_nothing(index_elements=["email"])
        )
        db.commit()
        user = db.scalar(select(User).where(User.email == email))
        assert user is not None
    role = settings.role_for(email)
    if user.role != role:
        user.role = role
        db.commit()
    return user
