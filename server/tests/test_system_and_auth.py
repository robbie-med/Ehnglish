import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app import auth
from app.config import Settings, get_settings


def test_health(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["pipeline_version"] == "test.0.1"


def test_me_uses_dev_email_in_test_env(client: TestClient) -> None:
    r = client.get("/api/me")
    assert r.status_code == 200
    assert r.json()["email"] == "tester@example.com"


def test_prod_requires_access_token(client: TestClient) -> None:
    from app.main import app

    base = get_settings()
    app.dependency_overrides[get_settings] = lambda: base.model_copy(update={"env": "prod"})
    r = client.get("/api/me")
    assert r.status_code == 401


@pytest.fixture
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks_for(key, kid: str) -> dict:
    pub = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    pub["kid"] = kid
    pub["alg"] = "RS256"
    pub["use"] = "sig"
    return {"keys": [pub]}


def _token(key, kid: str, email: str, aud: str, team: str, **extra) -> str:
    now = int(time.time())
    claims = {
        "email": email,
        "aud": [aud],
        "iss": f"https://{team}.cloudflareaccess.com",
        "iat": now,
        "exp": now + 300,
        **extra,
    }
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


def test_access_jwt_accepted(client: TestClient, rsa_key, monkeypatch) -> None:
    from app.main import app

    team, aud = "myteam", "a" * 64
    monkeypatch.setattr(auth, "fetch_jwks", lambda _team: _jwks_for(rsa_key, "k1"))
    base = get_settings()
    app.dependency_overrides[get_settings] = lambda: base.model_copy(
        update={"env": "prod", "cf_access_team_domain": team, "cf_access_aud": aud}
    )
    tok = _token(rsa_key, "k1", "Learner@Example.com", aud, team)
    r = client.get("/api/me", headers={"Cf-Access-Jwt-Assertion": tok})
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "learner@example.com"  # normalised


def test_access_jwt_wrong_audience_rejected(client: TestClient, rsa_key, monkeypatch) -> None:
    from app.main import app

    team = "myteam"
    monkeypatch.setattr(auth, "fetch_jwks", lambda _team: _jwks_for(rsa_key, "k1"))
    base = get_settings()
    app.dependency_overrides[get_settings] = lambda: base.model_copy(
        update={"env": "prod", "cf_access_team_domain": team, "cf_access_aud": "b" * 64}
    )
    tok = _token(rsa_key, "k1", "x@example.com", "a" * 64, team)
    r = client.get("/api/me", headers={"Cf-Access-Jwt-Assertion": tok})
    assert r.status_code == 401


def test_access_jwt_unknown_kid_rejected(client: TestClient, rsa_key, monkeypatch) -> None:
    from app.main import app

    team, aud = "myteam", "a" * 64
    monkeypatch.setattr(auth, "fetch_jwks", lambda _team: _jwks_for(rsa_key, "other"))
    base = get_settings()
    app.dependency_overrides[get_settings] = lambda: base.model_copy(
        update={"env": "prod", "cf_access_team_domain": team, "cf_access_aud": aud}
    )
    tok = _token(rsa_key, "k1", "x@example.com", aud, team)
    r = client.get("/api/me", headers={"Cf-Access-Jwt-Assertion": tok})
    assert r.status_code == 401


def test_allow_list_blocks_other_emails(client: TestClient) -> None:
    from app.main import app

    base = get_settings()
    app.dependency_overrides[get_settings] = lambda: base.model_copy(
        update={"allowed_emails": "someone@else.com"}
    )
    assert client.get("/api/me").status_code == 403
    app.dependency_overrides[get_settings] = lambda: base.model_copy(
        update={"allowed_emails": "Tester@example.com, someone@else.com"}
    )
    assert client.get("/api/me").status_code == 200


def test_settings_allow_list_parsing() -> None:
    s = Settings(allowed_emails=" A@x.com ,b@y.org,, ")
    assert s.allowed_email_set == {"a@x.com", "b@y.org"}
