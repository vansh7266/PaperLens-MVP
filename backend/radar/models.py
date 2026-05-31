# radar/models.py
#
# Pydantic response models for all Radar API endpoints.
# These define exactly what the API returns — prevents leaking internal fields.

from typing import Optional
from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Feed item — used in all list views (papers, models, company updates)
# ---------------------------------------------------------------------------

class RadarItem(BaseModel):
    """Single card in any Radar feed. Omits full_content (too large for lists)."""
    id:               str
    title:            str
    summary:          Optional[str]
    why_it_matters:   Optional[str]
    source_url:       str
    source_name:      str
    content_type:     str            # "paper", "model", "blog_post"
    authors:          Optional[list[str]]
    published_at:     Optional[str]
    fetched_at:       Optional[str]
    topic:            Optional[str]
    difficulty:       Optional[str]
    attention_score:  Optional[float]
    signal_label:     Optional[str]  # "High Signal" | "Worth Peeling" | "Worth Watching" | "Quick Skim"
    key_tags:         Optional[list[str]]
    has_peeler:       bool
    is_summarized:    bool
    avg_rating:       Optional[float]   = 0.0
    rating_count:     Optional[int]     = 0
    ranking_score:    Optional[float]   = 0.0

    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Today's Brief response
# ---------------------------------------------------------------------------

class BriefResponse(BaseModel):
    papers:          list[RadarItem]
    models:          list[RadarItem]
    company_updates: list[RadarItem]
    total:           int
    generated_at:    str
    date_label:      str     # e.g. "Today, May 29"
    plan:            str


# ---------------------------------------------------------------------------
# Paginated feed response
# ---------------------------------------------------------------------------

class FeedResponse(BaseModel):
    items:    list[RadarItem]
    count:    int
    offset:   int
    has_more: bool
    plan:     str


# ---------------------------------------------------------------------------
# Stats response (for sidebar / header counts)
# ---------------------------------------------------------------------------

class StatsResponse(BaseModel):
    scanned_today:    int
    high_signal:      int
    by_type:          dict[str, int]
    by_topic:         dict[str, int]


# ---------------------------------------------------------------------------
# Saved item
# ---------------------------------------------------------------------------

class SavedItem(BaseModel):
    id:       str    # saved_items row UUID
    item_id:  str    # content_items UUID
    saved_at: str
    item:     RadarItem

    model_config = ConfigDict(extra="ignore")


class SavedResponse(BaseModel):
    items:  list[SavedItem]
    count:  int
    plan:   str


# ---------------------------------------------------------------------------
# Action responses
# ---------------------------------------------------------------------------

class SaveActionResponse(BaseModel):
    saved:   bool
    item_id: str
    message: str


class ReadActionResponse(BaseModel):
    marked_read: bool
    item_id:     str


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------

class UserPreferences(BaseModel):
    preferred_topics: list[str]
    digest_enabled:   bool
    digest_email:     Optional[str]
    digest_time:      str     # e.g. "08:00"


class PreferencesResponse(BaseModel):
    preferences: UserPreferences
    plan:        str


# ---------------------------------------------------------------------------
# Email OTP
# ---------------------------------------------------------------------------

class OTPSendRequest(BaseModel):
    email: str


class OTPSendResponse(BaseModel):
    sent:       bool
    message:    str
    expires_in: int   # seconds until OTP expires


class OTPVerifyRequest(BaseModel):
    email: str
    otp:   str


class OTPVerifyResponse(BaseModel):
    verified: bool
    message:  str


# ---------------------------------------------------------------------------
# Digest settings
# ---------------------------------------------------------------------------

class DigestSettingsResponse(BaseModel):
    enabled:    bool
    email:      Optional[str]
    time:       str       # "08:00"
    verified:   bool      # email is verified


class DigestUpdateRequest(BaseModel):
    enabled: bool
    time:    Optional[str]   # "08:00"
