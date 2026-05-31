-- ============================================================
-- PaperLens — Research Radar Schema
-- Run ONCE in Supabase SQL Editor:
--   Dashboard → SQL Editor → New Query → paste → Run
--
-- Tables created:
--   content_items       — all Radar content (papers, models, blog posts)
--   saved_items         — user bookmarks
--   read_items          — read history per user
--   email_verifications — OTP records for email digest setup
--   user_preferences    — plan, topic prefs, digest settings
--
-- Also creates:
--   SQL functions for atomic increment/decrement of counters
--   Indexes for fast querying
--   RLS policies (Row Level Security)
-- ============================================================


-- ============================================================
-- content_items — all Radar content
-- ============================================================
CREATE TABLE IF NOT EXISTS content_items (
    id               UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    title            TEXT NOT NULL,
    source_url       TEXT UNIQUE NOT NULL,   -- deduplication key
    source_name      TEXT NOT NULL,          -- "arXiv", "Anthropic", etc.
    content_type     TEXT NOT NULL           -- "paper", "model", "blog_post"
                     CHECK (content_type IN ('paper', 'model', 'blog_post')),
    arxiv_id         TEXT,                   -- normalized, e.g. "2301.00001"
    authors          TEXT[]  DEFAULT '{}',
    full_content     TEXT    DEFAULT '',     -- abstract / description (not shown in list)
    published_at     TIMESTAMPTZ,
    fetched_at       TIMESTAMPTZ DEFAULT NOW(),
    released_at      TIMESTAMPTZ,

    -- Processor-computed fields
    topic            TEXT DEFAULT 'Other',
    difficulty       TEXT DEFAULT 'Intermediate'
                     CHECK (difficulty IN ('Easy', 'Intermediate', 'Advanced')),
    attention_score  FLOAT  DEFAULT 0.0,
    signal_label     TEXT   DEFAULT 'Quick Skim'
                     CHECK (signal_label IN ('High Signal', 'Worth Peeling', 'Worth Watching', 'Quick Skim')),
    key_tags         TEXT[] DEFAULT '{}',    -- up to 6 impact keywords found

    -- Summarizer-computed fields (set after LLM call)
    summary          TEXT,
    why_it_matters   TEXT,
    is_summarized    BOOLEAN DEFAULT false,

    -- Visibility
    is_released      BOOLEAN DEFAULT false,  -- false = only Pro sees it until 4AM batch

    -- Peeler linkage
    has_peeler       BOOLEAN DEFAULT false,
    peel_count       INTEGER DEFAULT 0,

    -- Engagement counters (updated via RPC functions, not direct writes)
    read_count       INTEGER DEFAULT 0,
    save_count       INTEGER DEFAULT 0,

    -- Extra source-specific data (HF tags, arXiv category, etc.)
    metadata_json    JSONB DEFAULT '{}'
);

-- Indexes — tuned for the query patterns in routes/radar.py
CREATE INDEX IF NOT EXISTS idx_ci_type          ON content_items(content_type);
CREATE INDEX IF NOT EXISTS idx_ci_type_summed   ON content_items(content_type, is_summarized);
CREATE INDEX IF NOT EXISTS idx_ci_score         ON content_items(attention_score DESC);
CREATE INDEX IF NOT EXISTS idx_ci_released      ON content_items(is_released);
CREATE INDEX IF NOT EXISTS idx_ci_fetched       ON content_items(fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_ci_published     ON content_items(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_ci_topic         ON content_items(topic);
CREATE INDEX IF NOT EXISTS idx_ci_arxiv_id      ON content_items(arxiv_id) WHERE arxiv_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ci_signal        ON content_items(signal_label);
-- Composite: most common radar query pattern
CREATE INDEX IF NOT EXISTS idx_ci_feed          ON content_items(content_type, is_summarized, is_released, attention_score DESC);
CREATE INDEX IF NOT EXISTS idx_ci_brief         ON content_items(content_type, is_summarized, fetched_at DESC, attention_score DESC);


-- ============================================================
-- saved_items — user bookmarks
-- ============================================================
CREATE TABLE IF NOT EXISTS saved_items (
    id       UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id  UUID NOT NULL,
    item_id  UUID NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
    saved_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, item_id)
);

CREATE INDEX IF NOT EXISTS idx_saved_user ON saved_items(user_id);
CREATE INDEX IF NOT EXISTS idx_saved_user_date ON saved_items(user_id, saved_at DESC);


-- ============================================================
-- read_items — per-user read history
-- ============================================================
CREATE TABLE IF NOT EXISTS read_items (
    id      UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL,
    item_id UUID NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
    read_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, item_id)
);

CREATE INDEX IF NOT EXISTS idx_read_user ON read_items(user_id);


-- ============================================================
-- email_verifications — OTP flow for digest setup
-- ============================================================
CREATE TABLE IF NOT EXISTS email_verifications (
    id         UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id    UUID    NOT NULL,
    email      TEXT    NOT NULL,
    otp_hash   TEXT    NOT NULL,    -- SHA-256(salt + user_id + OTP), never plaintext
    expires_at TIMESTAMPTZ NOT NULL,
    attempts   INTEGER DEFAULT 0,   -- wrong attempt counter (max = OTP_MAX_ATTEMPTS)
    verified   BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ev_user_email ON email_verifications(user_id, email);
CREATE INDEX IF NOT EXISTS idx_ev_expires    ON email_verifications(expires_at);


-- ============================================================
-- user_preferences — plan, topic prefs, digest settings
-- ============================================================
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id          UUID PRIMARY KEY,
    plan             TEXT DEFAULT 'free'
                     CHECK (plan IN ('trial', 'free', 'pro')),
    preferred_topics TEXT[]  DEFAULT '{}',
    digest_enabled   BOOLEAN DEFAULT false,
    digest_email     TEXT,
    digest_time      TEXT    DEFAULT '08:00',   -- "HH:MM" UTC
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);


-- ============================================================
-- SQL Functions — atomic counter updates
-- These are called via db.rpc() from the backend.
-- Using functions prevents race conditions (not read-then-write).
-- ============================================================

-- Increment save_count (floor = 0)
CREATE OR REPLACE FUNCTION increment_save_count(item_uuid UUID)
RETURNS void LANGUAGE sql AS $$
    UPDATE content_items
    SET save_count = save_count + 1
    WHERE id = item_uuid;
$$;

-- Decrement save_count (floor at 0 — never negative)
CREATE OR REPLACE FUNCTION decrement_save_count(item_uuid UUID)
RETURNS void LANGUAGE sql AS $$
    UPDATE content_items
    SET save_count = GREATEST(save_count - 1, 0)
    WHERE id = item_uuid;
$$;

-- Increment read_count
CREATE OR REPLACE FUNCTION increment_read_count(item_uuid UUID)
RETURNS void LANGUAGE sql AS $$
    UPDATE content_items
    SET read_count = read_count + 1
    WHERE id = item_uuid;
$$;


-- ============================================================
-- Row Level Security
-- ============================================================

ALTER TABLE content_items      ENABLE ROW LEVEL SECURITY;
ALTER TABLE saved_items        ENABLE ROW LEVEL SECURITY;
ALTER TABLE read_items         ENABLE ROW LEVEL SECURITY;
ALTER TABLE email_verifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_preferences   ENABLE ROW LEVEL SECURITY;

-- content_items: public read (respects is_released via app logic, not RLS)
-- Service role handles all writes
CREATE POLICY "content_items_public_read"
    ON content_items FOR SELECT USING (true);

CREATE POLICY "content_items_service_write"
    ON content_items FOR ALL USING (auth.role() = 'service_role');

-- saved_items: users manage their own rows only
CREATE POLICY "saved_items_own_read"
    ON saved_items FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "saved_items_own_insert"
    ON saved_items FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "saved_items_own_delete"
    ON saved_items FOR DELETE USING (auth.uid() = user_id);

CREATE POLICY "saved_items_service_all"
    ON saved_items FOR ALL USING (auth.role() = 'service_role');

-- read_items: users manage their own rows only
CREATE POLICY "read_items_own_read"
    ON read_items FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "read_items_own_insert"
    ON read_items FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "read_items_service_all"
    ON read_items FOR ALL USING (auth.role() = 'service_role');

-- email_verifications: users see own rows only
CREATE POLICY "email_ver_own"
    ON email_verifications FOR ALL USING (auth.uid() = user_id);

CREATE POLICY "email_ver_service"
    ON email_verifications FOR ALL USING (auth.role() = 'service_role');

-- user_preferences: users manage their own row only
CREATE POLICY "user_prefs_own"
    ON user_preferences FOR ALL USING (auth.uid() = user_id);

CREATE POLICY "user_prefs_service"
    ON user_preferences FOR ALL USING (auth.role() = 'service_role');

