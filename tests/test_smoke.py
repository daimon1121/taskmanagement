"""
Smoke tests for nagare Flask app.
DB calls are mocked via get_db; no real network required.
"""
import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

import app as nagare


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    nagare.app.config["TESTING"] = True
    nagare.app.config["WTF_CSRF_ENABLED"] = False
    nagare.app.config["RATELIMIT_ENABLED"] = False
    with nagare.app.test_client() as c:
        yield c


def _make_cursor(rows=None):
    """Return a mock cursor that yields given rows."""
    cur = MagicMock()
    cur.fetchone.return_value = rows[0] if rows else None
    cur.fetchall.return_value = rows or []
    return cur


@contextmanager
def _mock_db(rows=None):
    cur = _make_cursor(rows)
    yield MagicMock(), cur


def _user(plan="free"):
    return {
        "id": "test-uid-1",
        "email": "test@example.com",
        "password": nagare.generate_password_hash("Password123"),
        "plan": plan,
        "display_name": None,
    }


# ─── 1. Public pages ──────────────────────────────────────────────────────────

def test_login_page_returns_200(client):
    res = client.get("/login")
    assert res.status_code == 200

def test_signup_page_returns_200(client):
    res = client.get("/signup")
    assert res.status_code == 200

def test_pricing_page_requires_auth(client):
    res = client.get("/pricing")
    assert res.status_code == 302
    assert "/login" in res.headers["Location"]

def test_index_requires_auth(client):
    res = client.get("/")
    assert res.status_code == 302


# ─── 2. Auth — login ─────────────────────────────────────────────────────────

def test_login_wrong_password(client):
    with patch("app.get_db", return_value=_mock_db([_user()])):
        res = client.post("/login", data={
            "email": "test@example.com",
            "password": "wrongpassword",
        })
    assert res.status_code == 200
    assert "正しくありません" in res.data.decode("utf-8")

def test_login_unknown_email(client):
    with patch("app.get_db", return_value=_mock_db([])):
        res = client.post("/login", data={
            "email": "nobody@example.com",
            "password": "anypassword",
        })
    assert res.status_code == 200

def test_login_success_redirects(client):
    u = _user()
    with patch("app.get_db", return_value=_mock_db([u])):
        res = client.post("/login", data={
            "email": "test@example.com",
            "password": "Password123",
        })
    assert res.status_code == 302


# ─── 3. Auth — signup validation ─────────────────────────────────────────────

def test_signup_invalid_email(client):
    with patch("app.get_db", return_value=_mock_db([])):
        res = client.post("/signup", data={
            "email": "not-an-email",
            "password": "Password123",
        })
    assert res.status_code == 200
    assert "有効なメールアドレス" in res.data.decode("utf-8")

def test_signup_short_password(client):
    with patch("app.get_db", return_value=_mock_db([])):
        res = client.post("/signup", data={
            "email": "new@example.com",
            "password": "short",
        })
    assert res.status_code == 200
    assert "8文字以上" in res.data.decode("utf-8")

def test_signup_duplicate_email(client):
    with patch("app.get_db", return_value=_mock_db([_user()])):
        res = client.post("/signup", data={
            "email": "test@example.com",
            "password": "Password123",
        })
    assert res.status_code == 200
    assert "すでに登録" in res.data.decode("utf-8")


# ─── 4. Task API — unauthenticated ───────────────────────────────────────────

def test_get_tasks_requires_auth(client):
    res = client.get("/api/tasks")
    assert res.status_code == 302

def test_post_task_requires_auth(client):
    res = client.post("/api/tasks", json={"name": "test"})
    assert res.status_code == 302


# ─── 5. Task API — validation ────────────────────────────────────────────────

def _authenticated_client(client):
    """Inject a session so current_user() returns a free user."""
    with client.session_transaction() as sess:
        sess["user_id"] = "test-uid-1"
    return client

def test_add_task_missing_name(client):
    _authenticated_client(client)
    with patch("app.get_db", return_value=_mock_db([_user()])):
        res = client.post("/api/tasks", json={"status": "未着手"})
    assert res.status_code == 400
    assert "必須" in res.get_json()["error"]

def test_add_task_invalid_status(client):
    _authenticated_client(client)
    with patch("app.get_db", return_value=_mock_db([_user()])):
        res = client.post("/api/tasks", json={"name": "test", "status": "INVALID"})
    assert res.status_code == 400

def test_add_task_name_too_long(client):
    _authenticated_client(client)
    with patch("app.get_db", return_value=_mock_db([_user()])):
        res = client.post("/api/tasks", json={"name": "x" * 201})
    assert res.status_code == 400


# ─── 6. Feedback validation ───────────────────────────────────────────────────

def test_feedback_invalid_rating(client):
    _authenticated_client(client)
    with patch("app.get_db", return_value=_mock_db([_user()])):
        res = client.post("/api/feedback", json={"rating": 99, "message": "test"})
    assert res.status_code == 400

def test_feedback_non_numeric_rating(client):
    _authenticated_client(client)
    with patch("app.get_db", return_value=_mock_db([_user()])):
        res = client.post("/api/feedback", json={"rating": "bad", "message": "test"})
    assert res.status_code == 400


# ─── 7. Webhook — no CSRF required ───────────────────────────────────────────

def test_webhook_bad_signature_returns_400(client):
    res = client.post("/webhook",
                      data=b"payload",
                      headers={"Stripe-Signature": "bad"})
    assert res.status_code == 400
