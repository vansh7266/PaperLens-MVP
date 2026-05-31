# tests/test_radar_email.py
#
# Tests for email OTP verification flow.
# All DB and email-sending calls are mocked.

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from main import app
from routes.auth import get_current_user
from radar.routes.email import _generate_otp, _hash_otp, _verify_otp_hash

MOCK_USER = {"sub": "test-user-uuid-5678", "email": "user@example.com"}


@pytest.fixture
def client():
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# OTP security helpers
# ---------------------------------------------------------------------------

class TestOTPHelpers:

    def test_generate_otp_is_6_digits(self):
        otp = _generate_otp()
        assert len(otp) == 6
        assert otp.isdigit()

    def test_generate_otp_is_different_each_time(self):
        # Very unlikely to collide 10 times in a row
        otps = {_generate_otp() for _ in range(10)}
        assert len(otps) > 1

    def test_hash_is_deterministic(self):
        h1 = _hash_otp("123456", "user-abc")
        h2 = _hash_otp("123456", "user-abc")
        assert h1 == h2

    def test_different_otp_different_hash(self):
        h1 = _hash_otp("123456", "user-abc")
        h2 = _hash_otp("654321", "user-abc")
        assert h1 != h2

    def test_different_user_different_hash(self):
        h1 = _hash_otp("123456", "user-abc")
        h2 = _hash_otp("123456", "user-xyz")
        assert h1 != h2

    def test_verify_correct_otp_returns_true(self):
        otp  = "123456"
        uid  = "user-abc"
        h    = _hash_otp(otp, uid)
        assert _verify_otp_hash(otp, uid, h) is True

    def test_verify_wrong_otp_returns_false(self):
        uid  = "user-abc"
        h    = _hash_otp("123456", uid)
        assert _verify_otp_hash("000000", uid, h) is False

    def test_verify_wrong_user_returns_false(self):
        otp  = "123456"
        h    = _hash_otp(otp, "user-abc")
        assert _verify_otp_hash(otp, "user-xyz", h) is False


# ---------------------------------------------------------------------------
# POST /api/radar/email/send-otp
# ---------------------------------------------------------------------------

class TestSendOTP:

    def test_invalid_email_returns_400(self, client):
        resp = client.post(
            "/api/radar/email/send-otp",
            json={"email": "not-an-email"}
        )
        assert resp.status_code == 400

    def test_empty_email_returns_400(self, client):
        resp = client.post(
            "/api/radar/email/send-otp",
            json={"email": ""}
        )
        assert resp.status_code == 400

    def test_successful_send_returns_200(self, client):
        mock_db = _make_mock_db(recent_data=[])

        with patch("radar.routes.email.get_service_client", new=AsyncMock(return_value=mock_db)):
            with patch("radar.routes.email._send_otp_email", new=AsyncMock(return_value=True)):
                resp = client.post(
                    "/api/radar/email/send-otp",
                    json={"email": "valid@example.com"}
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["sent"] is True
        assert data["expires_in"] > 0

    def test_resend_cooldown_returns_429(self, client):
        # Simulate a recent send 10 seconds ago (within cooldown)
        recent_sent = (
            datetime.now(timezone.utc) - timedelta(seconds=10)
        ).isoformat()

        mock_db = _make_mock_db(recent_data=[{"created_at": recent_sent}])

        with patch("radar.routes.email.get_service_client", new=AsyncMock(return_value=mock_db)):
            resp = client.post(
                "/api/radar/email/send-otp",
                json={"email": "valid@example.com"}
            )

        assert resp.status_code == 429

    def test_email_service_failure_returns_503(self, client):
        mock_db = _make_mock_db(recent_data=[])

        with patch("radar.routes.email.get_service_client", new=AsyncMock(return_value=mock_db)):
            with patch("radar.routes.email._send_otp_email", new=AsyncMock(return_value=False)):
                resp = client.post(
                    "/api/radar/email/send-otp",
                    json={"email": "valid@example.com"}
                )

        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# POST /api/radar/email/verify-otp
# ---------------------------------------------------------------------------

class TestVerifyOTP:

    def test_invalid_otp_format_returns_400(self, client):
        resp = client.post(
            "/api/radar/email/verify-otp",
            json={"email": "valid@example.com", "otp": "abc"}
        )
        assert resp.status_code == 400

    def test_non_digit_otp_returns_400(self, client):
        resp = client.post(
            "/api/radar/email/verify-otp",
            json={"email": "valid@example.com", "otp": "12345a"}
        )
        assert resp.status_code == 400

    def test_no_pending_otp_returns_400(self, client):
        mock_db = _make_mock_db(otp_record=None)

        with patch("radar.routes.email.get_service_client", new=AsyncMock(return_value=mock_db)):
            resp = client.post(
                "/api/radar/email/verify-otp",
                json={"email": "valid@example.com", "otp": "123456"}
            )

        assert resp.status_code == 400

    def test_expired_otp_returns_400(self, client):
        expired_at = (
            datetime.now(timezone.utc) - timedelta(minutes=5)
        ).isoformat()

        record = {
            "id":         "rec-1",
            "otp_hash":   _hash_otp("123456", MOCK_USER["sub"]),
            "expires_at": expired_at,
            "attempts":   0,
        }
        mock_db = _make_mock_db(otp_record=record)

        with patch("radar.routes.email.get_service_client", new=AsyncMock(return_value=mock_db)):
            resp = client.post(
                "/api/radar/email/verify-otp",
                json={"email": "valid@example.com", "otp": "123456"}
            )

        assert resp.status_code == 400
        assert "expired" in resp.json()["detail"].lower()

    def test_wrong_otp_returns_400_with_attempts(self, client):
        valid_expires = (
            datetime.now(timezone.utc) + timedelta(minutes=8)
        ).isoformat()

        record = {
            "id":         "rec-2",
            "otp_hash":   _hash_otp("999999", MOCK_USER["sub"]),  # correct is 999999
            "expires_at": valid_expires,
            "attempts":   0,
        }
        mock_db = _make_mock_db(otp_record=record)

        with patch("radar.routes.email.get_service_client", new=AsyncMock(return_value=mock_db)):
            resp = client.post(
                "/api/radar/email/verify-otp",
                json={"email": "valid@example.com", "otp": "111111"}  # wrong OTP
            )

        assert resp.status_code == 400
        assert "Incorrect" in resp.json()["detail"]

    def test_correct_otp_returns_verified_true(self, client):
        valid_expires = (
            datetime.now(timezone.utc) + timedelta(minutes=8)
        ).isoformat()
        correct_otp = "234567"

        record = {
            "id":         "rec-3",
            "otp_hash":   _hash_otp(correct_otp, MOCK_USER["sub"]),
            "expires_at": valid_expires,
            "attempts":   0,
        }
        mock_db = _make_mock_db(otp_record=record)

        with patch("radar.routes.email.get_service_client", new=AsyncMock(return_value=mock_db)):
            resp = client.post(
                "/api/radar/email/verify-otp",
                json={"email": "valid@example.com", "otp": correct_otp}
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["verified"] is True

    def test_max_attempts_exceeded_returns_400(self, client):
        from config import OTP_MAX_ATTEMPTS
        valid_expires = (
            datetime.now(timezone.utc) + timedelta(minutes=8)
        ).isoformat()

        record = {
            "id":         "rec-4",
            "otp_hash":   _hash_otp("123456", MOCK_USER["sub"]),
            "expires_at": valid_expires,
            "attempts":   OTP_MAX_ATTEMPTS,  # already at limit
        }
        mock_db = _make_mock_db(otp_record=record)

        with patch("radar.routes.email.get_service_client", new=AsyncMock(return_value=mock_db)):
            resp = client.post(
                "/api/radar/email/verify-otp",
                json={"email": "valid@example.com", "otp": "123456"}
            )

        assert resp.status_code == 400
        assert "Too many" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Mock DB builder — creates the nested async mock chain
# that matches how supabase-py v2 query builder works
# ---------------------------------------------------------------------------

def _make_mock_db(recent_data=None, otp_record=None):
    """
    Build a mock async Supabase DB client for email tests.

    Distinguishes SELECT calls by the fields requested:
      - Cooldown check (send-otp): selects "created_at" → returns recent_data
      - OTP lookup (verify-otp):   selects "id, otp_hash, ..." → returns otp_record
      - Everything else             → returns []

    All INSERT / UPDATE / UPSERT return success.
    """

    def _make_chain(execute_mock):
        """Return a chainable query object whose .execute is execute_mock."""
        c = MagicMock()
        c.execute = execute_mock
        c.eq    = lambda *a, **kw: _make_chain(execute_mock)
        c.order = lambda *a, **kw: _make_chain(execute_mock)
        c.limit = lambda *a, **kw: _make_chain(execute_mock)
        c.gte   = lambda *a, **kw: _make_chain(execute_mock)
        return c

    ok_execute     = AsyncMock(return_value=MagicMock(data=[{"id": "new-id"}]))
    recent_execute = AsyncMock(return_value=MagicMock(data=recent_data or []))
    otp_execute    = AsyncMock(
        return_value=MagicMock(data=[otp_record] if otp_record else [])
    )
    empty_execute  = AsyncMock(return_value=MagicMock(data=[]))

    def ev_select(fields, *args, **kwargs):
        """
        email_verifications SELECT:
          - fields contains "created_at" → cooldown check → recent_data
          - fields contains "otp_hash"   → OTP lookup     → otp_record
          - otherwise                    → empty
        """
        if "created_at" in fields:
            return _make_chain(recent_execute)
        elif "otp_hash" in fields:
            return _make_chain(otp_execute)
        else:
            return _make_chain(empty_execute)

    def table_factory(name):
        tbl = MagicMock()

        if name == "email_verifications":
            tbl.select = ev_select
        else:
            tbl.select = lambda *a, **kw: _make_chain(empty_execute)

        tbl.insert = lambda *a, **kw: _make_chain(ok_execute)
        tbl.update = lambda *a, **kw: _make_chain(ok_execute)
        tbl.upsert = lambda *a, **kw: _make_chain(ok_execute)

        return tbl

    mock_db = MagicMock()
    mock_db.table = table_factory
    return mock_db
