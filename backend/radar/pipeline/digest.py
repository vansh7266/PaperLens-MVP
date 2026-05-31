# radar/pipeline/digest.py
#
# Daily email digest sender.
# Runs once a day (scheduled via RadarScheduler Job 3).
#
# Flow:
#   1. Fetch all users with digest_enabled=True + verified email
#   2. Fetch top 7 summarized items from last 24h (ranked by ranking_score)
#   3. Send branded HTML email to each subscriber via Resend API
#   4. Log success/failure per user

import logging
from datetime import datetime, timezone, timedelta

import httpx

from radar.core.database import get_service_client
from config import RESEND_API_KEY, RESEND_FROM_EMAIL

logger = logging.getLogger("paperlens.radar.pipeline.digest")

# Number of items to include per digest
DIGEST_ITEM_LIMIT = 7


class DigestSender:
    """Fetches top radar items and emails them to subscribed users."""

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def send_daily_digests(self) -> None:
        """Main entry point called by the scheduler."""
        logger.info("[Digest] Daily digest job starting.")

        if not RESEND_API_KEY:
            logger.error("[Digest] RESEND_API_KEY not set — skipping digest.")
            return

        try:
            db = await get_service_client()

            # 1. Fetch subscribers
            subscribers = await self._get_subscribers(db)
            if not subscribers:
                logger.info("[Digest] No subscribers with digest enabled.")
                return

            logger.info(f"[Digest] {len(subscribers)} subscriber(s) to email.")

            # 2. Fetch top items (same list for everyone)
            items = await self._get_top_items(db)
            if not items:
                logger.info("[Digest] No summarized items in last 24h — skipping.")
                return

            logger.info(f"[Digest] Sending {len(items)} items to {len(subscribers)} users.")

            # 3. Send to each subscriber
            sent = 0
            failed = 0
            for sub in subscribers:
                email = sub.get("digest_email")
                if not email:
                    continue
                ok = await self._send_digest_email(email, items)
                if ok:
                    sent += 1
                else:
                    failed += 1

            logger.info(f"[Digest] Done. Sent: {sent} | Failed: {failed}")

        except Exception as e:
            logger.error(
                f"[Digest] Unhandled error in send_daily_digests: "
                f"{type(e).__name__}: {e}",
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    async def _get_subscribers(self, db) -> list[dict]:
        """
        Return users with digest_enabled=True whose email is verified.
        """
        try:
            # Get all users who enabled digest
            prefs_resp = await (
                db.table("user_preferences")
                .select("user_id, digest_email")
                .eq("digest_enabled", True)
                .not_.is_("digest_email", "null")
                .execute()
            )
            prefs = prefs_resp.data or []
            if not prefs:
                return []

            # Filter to only verified emails
            verified = []
            for pref in prefs:
                ver_resp = await (
                    db.table("email_verifications")
                    .select("id")
                    .eq("user_id", pref["user_id"])
                    .eq("email", pref["digest_email"])
                    .eq("verified", True)
                    .limit(1)
                    .execute()
                )
                if ver_resp.data:
                    verified.append(pref)

            return verified

        except Exception as e:
            logger.error(f"[Digest] _get_subscribers error: {e}", exc_info=True)
            return []

    async def _get_top_items(self, db) -> list[dict]:
        """
        Fetch top DIGEST_ITEM_LIMIT summarized items from last 24h,
        ranked by ranking_score DESC.
        """
        try:
            cutoff = (
                datetime.now(timezone.utc) - timedelta(hours=24)
            ).isoformat()

            resp = await (
                db.table("content_items")
                .select(
                    "title, source_url, source_name, content_type, "
                    "topic, signal_label, summary, why_it_matters, "
                    "ranking_score, published_at"
                )
                .eq("is_summarized", True)
                .gte("fetched_at", cutoff)
                .order("ranking_score", desc=True)
                .limit(DIGEST_ITEM_LIMIT)
                .execute()
            )
            return resp.data or []

        except Exception as e:
            logger.error(f"[Digest] _get_top_items error: {e}", exc_info=True)
            return []

    # ------------------------------------------------------------------
    # Email sender
    # ------------------------------------------------------------------

    async def _send_digest_email(self, email: str, items: list[dict]) -> bool:
        """Send the digest email to one subscriber. Returns True on success."""
        try:
            today = datetime.now(timezone.utc).strftime("%B %d, %Y")
            html = _build_digest_html(items, today)

            payload = {
                "from":    RESEND_FROM_EMAIL,
                "to":      [email],
                "subject": f"PaperLens Daily Digest — {today}",
                "html":    html,
            }

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    "https://api.resend.com/emails",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {RESEND_API_KEY}",
                        "Content-Type":  "application/json",
                    },
                )

            if resp.status_code in (200, 201):
                logger.info(f"[Digest] Sent to {email}.")
                return True
            else:
                logger.error(
                    f"[Digest] Resend {resp.status_code} for {email}: {resp.text[:200]}"
                )
                return False

        except Exception as e:
            logger.error(
                f"[Digest] Failed to send to {email}: {type(e).__name__}: {e}",
                exc_info=True,
            )
            return False


# ------------------------------------------------------------------
# HTML email template
# ------------------------------------------------------------------

def _build_digest_html(items: list[dict], date_str: str) -> str:
    """Build the full branded HTML digest email."""

    items_html = ""
    for i, item in enumerate(items):
        signal = item.get("signal_label", "")
        signal_color = {
            "High Signal": "#4ade80",
            "Worth Peeling": "#a8c4f0",
            "Watching": "#f5e6cc",
        }.get(signal, "#888")

        topic = item.get("topic", "")
        source = item.get("source_name", "")
        content_type = item.get("content_type", "")
        title = item.get("title", "Untitled")
        summary = item.get("summary") or ""
        why = item.get("why_it_matters") or ""
        url = item.get("source_url", "#")

        type_label = {
            "paper":        "📄 Paper",
            "model":        "🤖 Model",
            "blog":         "📝 Blog Post",
            "company_news": "🏢 Lab News",
        }.get(content_type, "📌 Update")

        items_html += f"""
    <div style="
      border: 1px solid #1e2035;
      border-radius: 10px;
      padding: 20px 24px;
      margin-bottom: 16px;
      background: #0f1018;
    ">
      <div style="display:flex; gap:8px; margin-bottom:10px; flex-wrap:wrap;">
        <span style="
          font-size:11px; font-weight:600; letter-spacing:.5px;
          color:{signal_color}; background:rgba(255,255,255,.05);
          padding:2px 8px; border-radius:4px;
        ">{signal.upper() if signal else "UPDATE"}</span>
        <span style="
          font-size:11px; color:#888;
          background:rgba(255,255,255,.04);
          padding:2px 8px; border-radius:4px;
        ">{type_label}</span>
        {"<span style='font-size:11px; color:#888; background:rgba(255,255,255,.04); padding:2px 8px; border-radius:4px;'>" + topic + "</span>" if topic else ""}
      </div>

      <h3 style="
        margin: 0 0 10px;
        font-size: 15px;
        font-weight: 600;
        color: #e8e8e8;
        line-height: 1.4;
      ">{title}</h3>

      {"<p style='margin:0 0 8px; font-size:13px; color:#aaa; line-height:1.6;'>" + summary + "</p>" if summary else ""}
      {"<p style='margin:0 0 12px; font-size:12px; color:#888; font-style:italic; line-height:1.5;'>💡 " + why + "</p>" if why else ""}

      <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
        <span style="font-size:11px; color:#555;">{source}</span>
        <a href="{url}" style="
          font-size:12px; color:#a8c4f0;
          text-decoration:none; font-weight:500;
        ">Read →</a>
      </div>
    </div>
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>PaperLens Daily Digest</title>
</head>
<body style="
  margin:0; padding:0;
  background:#09090b;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  color:#e8e8e8;
">
  <div style="max-width:600px; margin:0 auto; padding:32px 16px;">

    <!-- Header -->
    <div style="margin-bottom:32px; padding-bottom:20px; border-bottom:1px solid #1e2035;">
      <div style="display:flex; align-items:center; gap:10px; margin-bottom:6px;">
        <span style="
          font-size:20px; font-weight:700; letter-spacing:-.5px;
          background: linear-gradient(135deg, #a8c4f0, #f5e6cc);
          -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        ">PaperLens</span>
      </div>
      <p style="margin:0; font-size:13px; color:#555;">Daily Research Digest · {date_str}</p>
    </div>

    <!-- Intro -->
    <p style="margin:0 0 24px; font-size:14px; color:#888; line-height:1.6;">
      Here are the top {len(items)} AI/ML updates from the last 24 hours, ranked by signal strength.
    </p>

    <!-- Items -->
    {items_html}

    <!-- Footer -->
    <div style="margin-top:32px; padding-top:20px; border-top:1px solid #1e2035; text-align:center;">
      <a href="https://deluxe-pasca-bcf870.netlify.app/radar.html"
         style="
           display:inline-block;
           padding:10px 24px;
           background: linear-gradient(135deg, #a8c4f0 0%, #f5e6cc 100%);
           color: #09090b;
           font-weight: 600;
           font-size: 13px;
           border-radius: 6px;
           text-decoration: none;
           margin-bottom: 20px;
         ">
        View Full Radar →
      </a>
      <p style="margin:0; font-size:11px; color:#444; line-height:1.6;">
        You're receiving this because you subscribed to PaperLens daily digest.<br>
        Manage preferences in
        <a href="https://deluxe-pasca-bcf870.netlify.app/settings.html"
           style="color:#555; text-decoration:underline;">Settings</a>.
      </p>
    </div>

  </div>
</body>
</html>"""
