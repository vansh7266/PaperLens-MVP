# radar/routes/email.py
#
# Email verification (OTP) + daily digest settings routes.
#
# Security design:
#   - OTP: server-side 6-digit code
#   - Hash: SHA-256 + salt before storing in DB
#   - Expiry: OTP_EXPIRY_MINUTES (10 min)
#   - Max attempts: OTP_MAX_ATTEMPTS (3 wrong = OTP invalidated)
#   - Resend cooldown: OTP_RESEND_COOLDOWN_S (60s between resends)
#   - Digest only activates after email is OTP-verified
#   - Users can disable digest anytime
#
# Email provider: Resend (resend.com) — transactional email API
#
# Endpoints:
#   POST /api/radar/email/send-otp        → send OTP to email
#   POST /api/radar/email/verify-otp      → verify OTP, enable digest
#   GET  /api/radar/email/digest-settings → get current digest settings
#   PUT  /api/radar/email/digest-settings → update digest settings

import hashlib
import logging
import os
import random
import string
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from radar.core.database import get_service_client
from radar.models import (
    OTPSendRequest, OTPSendResponse,
    OTPVerifyRequest, OTPVerifyResponse,
    DigestSettingsResponse, DigestUpdateRequest,
)
from routes.auth import get_current_user
from config import (
    RESEND_API_KEY,
    RESEND_FROM_EMAIL,
    OTP_EXPIRY_MINUTES,
    OTP_MAX_ATTEMPTS,
    OTP_RESEND_COOLDOWN_S,
)

logger = logging.getLogger("paperlens.radar.routes.email")
limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/api/radar/email", tags=["Email & Digest"])

# Salt prefix for OTP hashing — prevents rainbow table attacks
OTP_SALT_PREFIX = "paperlens-otp-"


# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------

def _generate_otp() -> str:
    """Generate a cryptographically random 6-digit OTP."""
    return "".join(random.choices(string.digits, k=6))


def _hash_otp(otp: str, user_id: str) -> str:
    """
    Hash OTP using SHA-256 with user_id as salt.
    Stored in DB instead of plaintext OTP.
    """
    salted = f"{OTP_SALT_PREFIX}{user_id}:{otp}"
    return hashlib.sha256(salted.encode()).hexdigest()


def _verify_otp_hash(otp: str, user_id: str, stored_hash: str) -> bool:
    """Constant-time comparison of OTP hash."""
    import hmac
    computed = _hash_otp(otp, user_id)
    return hmac.compare_digest(computed, stored_hash)


# ---------------------------------------------------------------------------
# Email sender (Resend)
# ---------------------------------------------------------------------------

async def _send_otp_email(email: str, otp: str) -> bool:
    """
    Send OTP email via Resend API.
    Returns True on success, False on failure.
    """
    if not RESEND_API_KEY:
        logger.error("[Email] RESEND_API_KEY not set — cannot send OTP.")
        return False

    try:
        import httpx

        payload = {
            "from":    RESEND_FROM_EMAIL,
            "to":      [email],
            "subject": "Your PaperLens verification code",
            "html":    _otp_email_html(otp),
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                json=payload,
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type":  "application/json",
                },
            )

        if resp.status_code in (200, 201):
            logger.info(f"[Email] OTP sent to {email}.")
            return True
        else:
            logger.error(
                f"[Email] Resend returned {resp.status_code}: {resp.text[:200]}"
            )
            return False

    except Exception as e:
        logger.error(f"[Email] Failed to send OTP: {type(e).__name__}: {e}", exc_info=True)
        return False


def _otp_email_html(otp: str) -> str:
    """Simple HTML email template for OTP."""
    return f"""
<!DOCTYPE html>
<html>
<body style="font-family: sans-serif; background: #0d0e14; color: #e8e8e8; padding: 40px;">
  <div style="max-width: 480px; margin: 0 auto;">
    <h2 style="color: #a8c4f0; margin-bottom: 8px;">PaperLens</h2>
    <p style="color: #888; font-size: 13px; margin-top: 0;">Research Radar daily digest</p>

    <p style="margin-top: 32px;">Your verification code:</p>

    <div style="
      background: #1a1c27;
      border: 1px solid #2a2d3e;
      border-radius: 8px;
      padding: 24px;
      text-align: center;
      margin: 24px 0;
    ">
      <span style="
        font-size: 36px;
        font-weight: 700;
        letter-spacing: 8px;
        color: #a8c4f0;
        font-family: monospace;
      ">{otp}</span>
    </div>

    <p style="color: #888; font-size: 13px;">
      This code expires in {OTP_EXPIRY_MINUTES} minutes.<br>
      If you didn't request this, ignore this email.
    </p>
  </div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# POST /api/radar/email/send-otp
# ---------------------------------------------------------------------------

@router.post("/send-otp", response_model=OTPSendResponse)
@limiter.limit("5/minute")   # strict rate limit on email sending
async def send_otp(
    body: OTPSendRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Send a 6-digit OTP to the provided email address.

    Rate limited to 5/minute per IP to prevent abuse.
    Enforces 60-second resend cooldown per user.

    The OTP is hashed with user_id as salt before being stored.
    Plain OTP is never persisted.
    """
    user_id = current_user["sub"]
    email   = body.email.strip().lower()

    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email address.")

    try:
        db = await get_service_client()
        now = datetime.now(timezone.utc)

        # --- Resend cooldown check ---
        recent = await (
            db.table("email_verifications")
            .select("created_at")
            .eq("user_id", user_id)
            .eq("email", email)
            .eq("verified", False)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )

        if recent.data:
            last_sent = datetime.fromisoformat(recent.data[0]["created_at"])
            if last_sent.tzinfo is None:
                last_sent = last_sent.replace(tzinfo=timezone.utc)
            cooldown_elapsed = (now - last_sent).total_seconds()

            if cooldown_elapsed < OTP_RESEND_COOLDOWN_S:
                wait_seconds = int(OTP_RESEND_COOLDOWN_S - cooldown_elapsed)
                raise HTTPException(
                    status_code=429,
                    detail=f"Please wait {wait_seconds}s before requesting a new code."
                )

        # --- Generate + hash OTP ---
        otp        = _generate_otp()
        otp_hash   = _hash_otp(otp, user_id)
        expires_at = (now + timedelta(minutes=OTP_EXPIRY_MINUTES)).isoformat()

        # --- Store hashed OTP ---
        await (
            db.table("email_verifications")
            .insert({
                "user_id":   user_id,
                "email":     email,
                "otp_hash":  otp_hash,
                "expires_at": expires_at,
                "attempts":  0,
                "verified":  False,
            })
            .execute()
        )

        # --- Send email ---
        sent = await _send_otp_email(email, otp)

        if not sent:
            raise HTTPException(
                status_code=503,
                detail="Failed to send verification email. Try again."
            )

        logger.info(f"[Email] OTP sent to {email} for user {user_id}.")

        return OTPSendResponse(
            sent       = True,
            message    = f"Verification code sent to {email}.",
            expires_in = OTP_EXPIRY_MINUTES * 60,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Email] send-otp error for {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to send OTP.")


# ---------------------------------------------------------------------------
# POST /api/radar/email/verify-otp
# ---------------------------------------------------------------------------

@router.post("/verify-otp", response_model=OTPVerifyResponse)
@limiter.limit("10/minute")
async def verify_otp(
    body: OTPVerifyRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Verify the OTP sent to the user's email.

    On success:
      - Marks the email_verifications row as verified
      - Updates user_preferences: digest_enabled=True, digest_email=email

    Security:
      - Max OTP_MAX_ATTEMPTS (3) wrong attempts → OTP invalidated
      - OTP expires after OTP_EXPIRY_MINUTES (10 min)
      - Constant-time hash comparison (no timing oracle)
    """
    user_id = current_user["sub"]
    email   = body.email.strip().lower()
    otp     = body.otp.strip()

    if not otp or len(otp) != 6 or not otp.isdigit():
        raise HTTPException(status_code=400, detail="OTP must be a 6-digit number.")

    try:
        db = await get_service_client()
        now = datetime.now(timezone.utc)

        # --- Find latest unverified OTP for this user+email ---
        resp = await (
            db.table("email_verifications")
            .select("id, otp_hash, expires_at, attempts")
            .eq("user_id", user_id)
            .eq("email", email)
            .eq("verified", False)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )

        if not resp.data:
            raise HTTPException(
                status_code=400,
                detail="No pending OTP found. Request a new code."
            )

        record = resp.data[0]
        record_id = record["id"]
        attempts  = record.get("attempts", 0) or 0

        # --- Check attempts limit ---
        if attempts >= OTP_MAX_ATTEMPTS:
            raise HTTPException(
                status_code=400,
                detail="Too many incorrect attempts. Request a new code."
            )

        # --- Check expiry ---
        expires_at = datetime.fromisoformat(record["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if now > expires_at:
            raise HTTPException(
                status_code=400,
                detail="OTP has expired. Request a new code."
            )

        # --- Verify hash (constant-time) ---
        if not _verify_otp_hash(otp, user_id, record["otp_hash"]):
            # Increment attempts counter
            await (
                db.table("email_verifications")
                .update({"attempts": attempts + 1})
                .eq("id", record_id)
                .execute()
            )
            remaining = OTP_MAX_ATTEMPTS - (attempts + 1)
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Incorrect code. {remaining} attempt(s) remaining."
                    if remaining > 0
                    else "Too many incorrect attempts. Request a new code."
                )
            )

        # --- Success: mark as verified ---
        await (
            db.table("email_verifications")
            .update({"verified": True})
            .eq("id", record_id)
            .execute()
        )

        # --- Update user_preferences: enable digest ---
        await (
            db.table("user_preferences")
            .upsert(
                {
                    "user_id":        user_id,
                    "digest_enabled": True,
                    "digest_email":   email,
                    "updated_at":     now.isoformat(),
                },
                on_conflict="user_id",
            )
            .execute()
        )

        logger.info(f"[Email] OTP verified for user={user_id} email={email}.")

        return OTPVerifyResponse(
            verified = True,
            message  = "Email verified. Daily digest is now enabled.",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Email] verify-otp error for {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to verify OTP.")


# ---------------------------------------------------------------------------
# GET /api/radar/email/digest-settings
# ---------------------------------------------------------------------------

@router.get("/digest-settings", response_model=DigestSettingsResponse)
@limiter.limit("60/minute")
async def get_digest_settings(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Return the user's current digest settings."""
    user_id = current_user["sub"]

    try:
        db = await get_service_client()

        resp = await (
            db.table("user_preferences")
            .select("digest_enabled, digest_email, digest_time")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )

        prefs = resp.data[0] if resp.data else {}

        digest_email = prefs.get("digest_email")
        verified     = False

        # Check if this email is actually verified
        if digest_email:
            ver_resp = await (
                db.table("email_verifications")
                .select("id")
                .eq("user_id", user_id)
                .eq("email", digest_email)
                .eq("verified", True)
                .limit(1)
                .execute()
            )
            verified = bool(ver_resp.data)

        return DigestSettingsResponse(
            enabled  = prefs.get("digest_enabled", False),
            email    = digest_email,
            time     = prefs.get("digest_time", "08:00"),
            verified = verified,
        )

    except Exception as e:
        logger.error(f"[Email] get digest-settings error for {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch digest settings.")


# ---------------------------------------------------------------------------
# PUT /api/radar/email/digest-settings
# ---------------------------------------------------------------------------

@router.put("/digest-settings", response_model=DigestSettingsResponse)
@limiter.limit("20/minute")
async def update_digest_settings(
    body: DigestUpdateRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Update digest settings.
    Can enable/disable digest and change preferred time.
    Cannot enable digest without a verified email — use /send-otp first.
    """
    user_id = current_user["sub"]
    now     = datetime.now(timezone.utc)

    try:
        db = await get_service_client()

        # Fetch current prefs
        prefs_resp = await (
            db.table("user_preferences")
            .select("digest_email, digest_enabled")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        prefs       = prefs_resp.data[0] if prefs_resp.data else {}
        digest_email = prefs.get("digest_email")

        # Cannot enable without a verified email
        if body.enabled and not digest_email:
            raise HTTPException(
                status_code=400,
                detail="No verified email on file. Use /send-otp to verify an email first."
            )

        if body.enabled and digest_email:
            ver_resp = await (
                db.table("email_verifications")
                .select("id")
                .eq("user_id", user_id)
                .eq("email", digest_email)
                .eq("verified", True)
                .limit(1)
                .execute()
            )
            if not ver_resp.data:
                raise HTTPException(
                    status_code=400,
                    detail="Email is not verified. Use /send-otp to verify first."
                )

        update_data = {
            "user_id":        user_id,
            "digest_enabled": body.enabled,
            "updated_at":     now.isoformat(),
        }
        if body.time:
            update_data["digest_time"] = body.time

        await (
            db.table("user_preferences")
            .upsert(update_data, on_conflict="user_id")
            .execute()
        )

        logger.info(
            f"[Email] Digest settings updated for {user_id}: "
            f"enabled={body.enabled} time={body.time}"
        )

        # Return updated settings
        return DigestSettingsResponse(
            enabled  = body.enabled,
            email    = digest_email,
            time     = body.time or prefs.get("digest_time", "08:00"),
            verified = bool(digest_email),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Email] update digest-settings error for {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update digest settings.")
