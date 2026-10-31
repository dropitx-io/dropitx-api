"""Firebase ID token and session cookie verification through the auth dependencies.

Tokens are signed with throwaway RSA keys and the public-cert endpoints are
faked at the HTTP layer, so the full verification path runs for real.
"""

import asyncio
import datetime
import importlib
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi.exceptions import HTTPException
from jose import jwt

from app.dependencies import get_current_user, get_firebase_claims, get_optional_user
from tests.conftest import unique_ip

PROJECT = "test-project"
ID_TOKEN_ISSUER = f"https://securetoken.google.com/{PROJECT}"
SESSION_ISSUER = f"https://session.firebase.google.com/{PROJECT}"
ID_CERTS_URL = (
    "https://www.googleapis.com/robot/v1/metadata/x509/"
    "securetoken@system.gserviceaccount.com"
)
SESSION_CERTS_URL = (
    "https://www.googleapis.com/identitytoolkit/v3/relyingparty/publicKeys"
)
KID = "kid-1"


class _Keypair:
    """A throwaway RSA key plus the self-signed x509 cert Google would publish."""

    def __init__(self) -> None:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=30))
            .sign(key, hashes.SHA256())
        )
        self.private_pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        self.cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()


@pytest.fixture(scope="module")
def id_key():
    return _Keypair()


@pytest.fixture(scope="module")
def session_key():
    return _Keypair()


class _CertServer:
    """Fake of Google's public-cert endpoints, keyed by URL."""

    def __init__(self, certs_by_url):
        self.certs_by_url = certs_by_url
        self.calls: list[str] = []

    def get(self, url, timeout=None):
        self.calls.append(url)
        response = MagicMock()
        response.json.return_value = self.certs_by_url[url]
        return response


@pytest.fixture
def certs(monkeypatch, id_key, session_key):
    # Cert caches live at module level; reload so no test sees another's keys.
    from core import security

    importlib.reload(security)
    monkeypatch.setattr(security, "settings", SimpleNamespace(firebase_project_id=PROJECT))
    server = _CertServer(
        {
            ID_CERTS_URL: {KID: id_key.cert_pem},
            SESSION_CERTS_URL: {KID: session_key.cert_pem},
        }
    )
    monkeypatch.setattr("httpx.get", server.get)
    return server


def _token(key, issuer, *, aud=PROJECT, kid=KID, **overrides):
    now = int(time.time())
    claims = {
        "iss": issuer,
        "aud": aud,
        "sub": "uid-1",
        "email": "a@b.com",
        "iat": now - 10,
        "auth_time": now - 10,
        "exp": now + 3600,
    }
    claims.update(overrides)
    return jwt.encode(claims, key.private_pem, algorithm="RS256", headers={"kid": kid})


class FakeRequest:
    def __init__(self, token):
        self.headers = {"authorization": f"Bearer {token}"}


def _claims(token):
    return asyncio.run(get_firebase_claims(FakeRequest(token)))


@pytest.fixture
def assert_rejected(certs, session_key):
    """Assert a token gets a 401, after proving a good session cookie is accepted.

    The control keeps a rejection from passing only because session cookies are
    unsupported altogether.
    """

    def check(token):
        assert _claims(_token(session_key, SESSION_ISSUER))["sub"] == "uid-1"
        with pytest.raises(HTTPException) as exc:
            _claims(token)
        assert exc.value.status_code == 401

    return check


def test_valid_session_cookie_returns_user(certs, session_key):
    cookie = _token(session_key, SESSION_ISSUER)
    client = MagicMock()
    client.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        MagicMock(data=[{"id": "uid-1", "email": "a@b.com"}])
    )
    with patch("app.dependencies.get_admin_client", return_value=client):
        user = asyncio.run(get_current_user(FakeRequest(cookie)))
        optional = asyncio.run(get_optional_user(FakeRequest(cookie)))

    assert (user.id, user.email) == ("uid-1", "a@b.com")
    assert optional == user


def test_session_cookie_with_wrong_audience_is_rejected(assert_rejected, session_key):
    assert_rejected(_token(session_key, SESSION_ISSUER, aud="another-project"))


@pytest.mark.parametrize(
    "issuer",
    [
        "https://session.firebase.google.com/another-project",
        "https://securetoken.google.com/another-project",
        "https://evil.example.com/test-project",
        f"https://session.firebase.google.com.evil.example/{PROJECT}",
    ],
)
def test_wrong_issuer_is_rejected(assert_rejected, session_key, issuer):
    assert_rejected(_token(session_key, issuer))


def test_expired_session_cookie_is_rejected(assert_rejected, session_key):
    assert_rejected(_token(session_key, SESSION_ISSUER, exp=int(time.time()) - 60))


def test_id_token_still_works(certs, id_key):
    claims = _claims(_token(id_key, ID_TOKEN_ISSUER))
    assert claims["sub"] == "uid-1"
    assert claims["email"] == "a@b.com"


def test_id_token_signed_with_session_key_is_rejected(assert_rejected, session_key):
    assert_rejected(_token(session_key, ID_TOKEN_ISSUER))


def test_session_cookie_signed_with_id_token_key_is_rejected(assert_rejected, id_key):
    assert_rejected(_token(id_key, SESSION_ISSUER))


def test_session_cookie_requires_subject(assert_rejected, session_key):
    assert_rejected(_token(session_key, SESSION_ISSUER, sub=""))


@pytest.mark.parametrize("claim", ["iat", "auth_time"])
def test_session_cookie_issued_in_the_future_is_rejected(assert_rejected, session_key, claim):
    assert_rejected(_token(session_key, SESSION_ISSUER, **{claim: int(time.time()) + 3600}))


@pytest.mark.parametrize("claim", ["iat", "auth_time"])
def test_session_cookie_missing_time_claim_is_rejected(assert_rejected, session_key, claim):
    now = int(time.time())
    claims = {
        "iss": SESSION_ISSUER,
        "aud": PROJECT,
        "sub": "uid-1",
        "iat": now - 10,
        "auth_time": now - 10,
        "exp": now + 3600,
    }
    del claims[claim]
    token = jwt.encode(claims, session_key.private_pem, algorithm="RS256", headers={"kid": KID})
    assert_rejected(token)


def test_each_key_set_has_its_own_cache(certs, id_key, session_key):
    _claims(_token(session_key, SESSION_ISSUER))
    _claims(_token(session_key, SESSION_ISSUER))
    _claims(_token(id_key, ID_TOKEN_ISSUER))

    assert certs.calls.count(SESSION_CERTS_URL) == 1
    assert certs.calls.count(ID_CERTS_URL) == 1


def test_unknown_kid_refetches_its_own_key_set_once(certs, session_key, monkeypatch):
    from core import security

    monkeypatch.setattr(security, "_CERTS_REFETCH_MIN_INTERVAL", 0)
    rotated = _Keypair()
    _claims(_token(session_key, SESSION_ISSUER))
    certs.certs_by_url[SESSION_CERTS_URL] = {KID: session_key.cert_pem, "kid-2": rotated.cert_pem}

    claims = _claims(_token(rotated, SESSION_ISSUER, kid="kid-2"))

    assert claims["sub"] == "uid-1"
    assert certs.calls == [SESSION_CERTS_URL, SESSION_CERTS_URL]


def _token_without(key, issuer, claim):
    now = int(time.time())
    claims = {
        "iss": issuer,
        "aud": PROJECT,
        "sub": "uid-1",
        "iat": now - 10,
        "auth_time": now - 10,
        "exp": now + 3600,
    }
    del claims[claim]
    return jwt.encode(claims, key.private_pem, algorithm="RS256", headers={"kid": KID})


@pytest.mark.parametrize("claim", ["exp", "aud"])
def test_token_missing_a_required_claim_is_rejected(assert_rejected, session_key, claim):
    assert_rejected(_token_without(session_key, SESSION_ISSUER, claim))


def test_unknown_kid_within_the_refetch_interval_does_not_refetch(certs, session_key):
    stranger = _Keypair()
    _claims(_token(session_key, SESSION_ISSUER))

    for _ in range(2):
        with pytest.raises(HTTPException) as exc:
            _claims(_token(stranger, SESSION_ISSUER, kid="unknown-kid"))
        assert exc.value.status_code == 401

    assert certs.calls == [SESSION_CERTS_URL]


def test_unknown_kid_after_the_refetch_interval_refetches(certs, session_key, monkeypatch):
    from core import security

    _claims(_token(session_key, SESSION_ISSUER))
    session_kind = next(k for k in security._TOKEN_KINDS if k.certs_url == SESSION_CERTS_URL)
    session_kind.last_fetch_at -= security._CERTS_REFETCH_MIN_INTERVAL
    rotated = _Keypair()
    certs.certs_by_url[SESSION_CERTS_URL] = {KID: session_key.cert_pem, "kid-2": rotated.cert_pem}

    claims = _claims(_token(rotated, SESSION_ISSUER, kid="kid-2"))

    assert claims["sub"] == "uid-1"
    assert certs.calls == [SESSION_CERTS_URL, SESSION_CERTS_URL]


@pytest.fixture
def cert_outage(monkeypatch):
    """Google's cert endpoint is unreachable and nothing is cached."""
    from core import security

    importlib.reload(security)
    monkeypatch.setattr(security, "settings", SimpleNamespace(firebase_project_id=PROJECT))

    def unreachable(url, timeout=None):
        raise httpx.ConnectError("cert endpoint unreachable")

    monkeypatch.setattr("httpx.get", unreachable)


def test_cert_outage_is_a_503_for_required_auth(cert_outage, session_key):
    with pytest.raises(HTTPException) as exc:
        _claims(_token(session_key, SESSION_ISSUER))
    assert exc.value.status_code == 503
    assert exc.value.detail == "Auth provider unavailable"


def test_cert_outage_degrades_public_routes_to_anonymous(cert_outage, session_key, client, seed):
    share = seed.share(seed.user(), is_private=False)
    headers = {"authorization": f"Bearer {_token(session_key, SESSION_ISSUER)}"}

    public = client.get(f"/api/shares/{share['slug']}", headers={**headers, **unique_ip()})
    dashboard = client.get("/api/dashboard/shares", headers={**headers, **unique_ip()})

    assert public.status_code == 200
    assert dashboard.status_code == 503


# ---------------------------------------------------------------------------
# Cert endpoint outage with certs already cached
# ---------------------------------------------------------------------------

class _Outage:
    """httpx.get replacement that always fails and counts its calls."""

    def __init__(self):
        self.calls = 0

    def get(self, url, timeout=None):
        self.calls += 1
        raise httpx.ConnectError("cert endpoint unreachable")


def _session_kind(security):
    return next(k for k in security._TOKEN_KINDS if k.certs_url == SESSION_CERTS_URL)


@pytest.fixture
def stale_certs(certs, session_key, monkeypatch):
    """Session-cookie certs are cached, their TTL has run out, and the endpoint is down."""
    from core import security

    _claims(_token(session_key, SESSION_ISSUER))
    _session_kind(security).certs_expire_at = 0.0
    outage = _Outage()
    monkeypatch.setattr("httpx.get", outage.get)
    return outage


def test_expired_cached_certs_keep_verifying_while_the_endpoint_is_down(stale_certs, session_key, caplog):
    claims = _claims(_token(session_key, SESSION_ISSUER))

    assert claims["sub"] == "uid-1"
    assert stale_certs.calls == 1
    assert "serving cached certs" in caplog.text


def test_concurrent_verifications_during_an_outage_make_one_network_call(stale_certs, session_key):
    from concurrent.futures import ThreadPoolExecutor

    from core import security

    token = _token(session_key, SESSION_ISSUER)
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(lambda _: security.verify_firebase_jwt(token), range(10)))

    assert [r["sub"] for r in results] == ["uid-1"] * 10
    assert stale_certs.calls == 1


def test_outage_with_nothing_cached_makes_one_network_call_and_is_503(certs, session_key, monkeypatch):
    outage = _Outage()
    monkeypatch.setattr("httpx.get", outage.get)

    statuses = []
    for _ in range(3):
        with pytest.raises(HTTPException) as exc:
            _claims(_token(session_key, SESSION_ISSUER))
        statuses.append(exc.value.status_code)

    assert statuses == [503, 503, 503]
    assert outage.calls == 1


def test_endpoint_is_retried_once_the_failure_window_has_passed(stale_certs, session_key, monkeypatch):
    from core import security

    _claims(_token(session_key, SESSION_ISSUER))
    assert stale_certs.calls == 1
    _session_kind(security).last_failure_at -= security._CERTS_FAILURE_BACKOFF
    rotated = _Keypair()
    server = _CertServer({SESSION_CERTS_URL: {KID: session_key.cert_pem, "kid-2": rotated.cert_pem}})
    monkeypatch.setattr("httpx.get", server.get)

    claims = _claims(_token(rotated, SESSION_ISSUER, kid="kid-2"))

    assert claims["sub"] == "uid-1"
    assert server.calls == [SESSION_CERTS_URL]


def test_unknown_kid_is_not_made_valid_by_stale_certs(stale_certs, session_key):
    from core import security

    _session_kind(security).last_fetch_at -= security._CERTS_REFETCH_MIN_INTERVAL
    stranger = _Keypair()

    with pytest.raises(HTTPException) as exc:
        _claims(_token(stranger, SESSION_ISSUER, kid="unknown-kid"))

    assert exc.value.status_code == 401
    assert _claims(_token(session_key, SESSION_ISSUER))["sub"] == "uid-1"
