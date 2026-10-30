"""Unit tests for auth dependencies."""

import asyncio
from unittest.mock import patch, MagicMock

import pytest
from fastapi.exceptions import HTTPException

from app.dependencies import get_firebase_claims, get_current_user


class FakeRequest:
    def __init__(self, headers=None):
        self.headers = headers or {}


@pytest.fixture(autouse=True)
def mock_settings():
    with patch("core.config.settings") as mock:
        mock.firebase_project_id = "test-project"
        mock.cors_origins = ["*"]
        yield mock


def _req(token=None):
    headers = {}
    if token:
        headers["authorization"] = f"Bearer {token}"
    return FakeRequest(headers)


def test_claims_missing_token():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_firebase_claims(_req()))
    assert exc.value.status_code == 401


@patch("app.dependencies.verify_firebase_jwt")
def test_claims_valid_token(mock_verify):
    mock_verify.return_value = {"sub": "uid-1", "email": "a@b.com"}
    claims = asyncio.run(get_firebase_claims(_req("tok")))
    assert claims["sub"] == "uid-1"


@patch("app.dependencies.verify_firebase_jwt", side_effect=ValueError("bad sig"))
def test_claims_invalid_token(mock_verify):
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_firebase_claims(_req("tok")))
    assert exc.value.status_code == 401


@patch("app.dependencies.get_admin_client")
@patch("app.dependencies.verify_firebase_jwt")
def test_current_user_provisioned(mock_verify, mock_get_client):
    mock_verify.return_value = {"sub": "uid-1", "email": "a@b.com"}
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"id": "uid-1", "email": "a@b.com"}]
    )
    user = asyncio.run(get_current_user(_req("tok")))
    assert user.id == "uid-1"
    assert user.email == "a@b.com"


@patch("app.dependencies.get_admin_client")
@patch("app.dependencies.verify_firebase_jwt")
def test_current_user_not_provisioned(mock_verify, mock_get_client):
    mock_verify.return_value = {"sub": "uid-2", "email": "x@y.com"}
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_current_user(_req("tok")))
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "user_not_provisioned"


@patch("app.dependencies.get_admin_client")
@patch("app.dependencies.verify_firebase_jwt")
def test_current_user_lookup_error_is_500(mock_verify, mock_get_client):
    mock_verify.return_value = {"sub": "uid-3", "email": "z@w.com"}
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.table.side_effect = RuntimeError("db down")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_current_user(_req("tok")))
    assert exc.value.status_code == 500
