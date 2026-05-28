# ============================================================
# config.py — PaperLens Master Configuration
# ============================================================
# This is the SINGLE SOURCE OF TRUTH for the entire backend.
# Every other file imports from here.
# To change anything — model, limit, setting — change it HERE.
# Never hardcode values in other files.
# ============================================================

import os
from dotenv import load_dotenv

# ── Load .env file ──────────────────────────────────────────
# Reads your .env file and makes all keys available via os.getenv()
# Must be called before any os.getenv() calls below
load_dotenv()


# ============================================================
# SUPABASE — Database & Auth
# ============================================================
# ANON_KEY   → limited access, safe for frontend
# SERVICE_KEY → full admin access, backend ONLY, never expose

SUPABASE_URL         = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY    = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
PEELER_STORAGE       = os.getenv("PEELER_STORAGE", "memory")  # memory or supabase


# ============================================================
# AI / LLM SETTINGS
# ============================================================
# ACTIVE_LLM → controls which model the entire system uses
# Change this ONE variable to switch providers everywhere
#
#   "openai" → OpenAI models (Paper Peeler production default)
#   "gemini" → Gemini 2.0 Flash (legacy/testing)
#   "claude" → Claude Sonnet 4.6 (legacy/testing)
#
# ── TO SWITCH TO CLAUDE: change "gemini" to "claude" below ──

ACTIVE_LLM = os.getenv("ACTIVE_LLM", "openai")

# Exact model strings per provider
MODELS = {
    "openai": os.getenv("OPENAI_PEEL_MODEL", "gpt-5-mini"),
    "openai_cheap": os.getenv("OPENAI_CHEAP_MODEL", "gpt-5-nano"),
    "embedding": os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
    "gemini": "gemini-2.0-flash",
    "claude": "claude-sonnet-4-6",
    "groq": os.getenv("GROQ_PEEL_MODEL", "llama-3.1-8b-instant"),
}

# API Keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")   # empty for now
GROQ_API_KEY = os.getenv("GROQ_API_KEY")


# ============================================================
# ARXIV — Data Source Settings
# ============================================================
# arXiv category codes we monitor for new papers
# These are the official arXiv subject classifications
#
#   cs.AI  → Artificial Intelligence
#   cs.LG  → Machine Learning
#   cs.CV  → Computer Vision and Pattern Recognition
#   cs.CL  → Computation and Language (NLP)
#   cs.NE  → Neural and Evolutionary Computing
#   stat.ML→ Statistics - Machine Learning

ARXIV_CATEGORIES = [
    "cs.AI",
    "cs.LG",
    "cs.CV",
    "cs.CL",
    "cs.NE",
    "stat.ML",
]

# How many papers to fetch per arXiv API call
MAX_PAPERS_PER_FETCH = 50


# ============================================================
# FETCHER / SCHEDULER SETTINGS
# ============================================================
# How often the fetcher runs (in minutes)
# Every 5 minutes → checks all sources for new content
FETCH_INTERVAL_MINUTES = 5
ENABLE_FEED_SCHEDULER = os.getenv("ENABLE_FEED_SCHEDULER", "false").lower() == "true"

# RSS blog sources we monitor
# These are official company engineering/research blogs
RSS_FEEDS = {
    "Anthropic":       "https://www.anthropic.com/news/rss.xml",
    "OpenAI":          "https://openai.com/blog/rss.xml",
    "Google DeepMind": "https://deepmind.google/blog/rss.xml",
    "Meta AI":         "https://ai.meta.com/blog/rss/",
    "Mistral AI":      "https://mistral.ai/news/rss.xml",
    "HuggingFace":     "https://huggingface.co/blog/feed.xml",
}


# ============================================================
# FREE vs PRO DELIVERY SETTINGS
# ============================================================
# PRO users → papers appear within PRO_DELAY_MINUTES of publishing
# FREE users → papers released once per day at FREE_DIGEST_TIME
#              only the top FREE_TOP_PAPERS by attention score

# Pro: near real-time (3 minutes after paper is fetched)
PRO_DELAY_MINUTES = 3

# Free: daily batch release time (24-hour format, UTC)
FREE_DIGEST_TIME = "04:00"

# Free: maximum papers shown per day
# Ranked by attention score (citations + HN + Reddit)
FREE_TOP_PAPERS = 20


# ============================================================
# PLAN LIMITS
# ============================================================
# -1 means unlimited (Pro/Team plans)
# These are enforced in the API routes

FREE_PEEL_LIMIT  = int(os.getenv("FREE_PEEL_LIMIT", "3"))      # beta new uncached peels / 7 days
PRO_PEEL_LIMIT   = int(os.getenv("PRO_PEEL_LIMIT", "30"))      # Pro Starter new uncached peels / month

FREE_CHAT_LIMIT  = int(os.getenv("FREE_CHAT_LIMIT", "20"))     # beta paper-chat replies / 7 days
PRO_CHAT_LIMIT   = int(os.getenv("PRO_CHAT_LIMIT", "300"))     # Pro Starter replies / month

FREE_SAVED_LIMIT = 20    # saved papers
PRO_SAVED_LIMIT  = -1    # unlimited


# ============================================================
# TOPIC CLASSIFICATION MAP
# ============================================================
# Used by processor.py to classify papers into topics
# Pure keyword matching — zero AI cost, runs instantly
#
# How it works:
#   1. Take paper title + abstract
#   2. Convert to lowercase
#   3. Check which keywords appear
#   4. Assign the topic with most keyword matches
#
# You can add new topics or keywords anytime here

TOPIC_MAP = {
    "LLMs": [
        "language model", "llm", "large language", "gpt", "transformer",
        "bert", "llama", "instruction tuning", "fine-tuning", "chat",
        "text generation", "autoregressive", "pretraining", "token",
        "context window", "prompt", "in-context learning", "rlhf",
    ],
    "Computer Vision": [
        "image", "vision", "visual", "object detection", "segmentation",
        "classification", "recognition", "convolutional", "cnn",
        "video", "optical flow", "depth estimation", "pose estimation",
        "image generation", "vit", "detr",
    ],
    "RL / Agents": [
        "reinforcement learning", "reward", "policy", "agent",
        "environment", "markov", "q-learning", "actor-critic",
        "multi-agent", "planning", "exploration", "tool use",
        "autonomous", "decision making", "ppo", "dqn",
    ],
    "Diffusion Models": [
        "diffusion", "denoising", "score matching", "ddpm", "ddim",
        "stable diffusion", "image synthesis", "text-to-image",
        "generative model", "noise", "latent diffusion", "flow matching",
    ],
    "NLP": [
        "natural language", "nlp", "text classification", "sentiment",
        "named entity", "question answering", "summarization",
        "machine translation", "parsing", "coreference",
        "information extraction", "reading comprehension",
    ],
    "Multimodal": [
        "multimodal", "vision-language", "image-text", "clip",
        "visual question answering", "vqa", "image captioning",
        "audio-visual", "cross-modal", "llava", "flamingo",
    ],
    "AI Safety": [
        "alignment", "safety", "interpretability", "explainability",
        "robustness", "adversarial", "hallucination", "bias",
        "fairness", "red teaming", "jailbreak", "constitutional ai",
    ],
    "Model Efficiency": [
        "quantization", "pruning", "distillation", "compression",
        "efficient", "lightweight", "lora", "adapter", "mixture of experts",
        "moe", "sparse", "inference", "latency", "throughput",
    ],
    "Robotics": [
        "robot", "robotics", "manipulation", "locomotion", "grasping",
        "sim-to-real", "embodied", "navigation", "physical",
    ],
}


# ============================================================
# DIFFICULTY DETECTION RULES
# ============================================================
# Used by processor.py to assign difficulty level to each paper
# Pure keyword counting — zero AI cost
#
# How it works:
#   Count advanced keywords in title + abstract
#   Count easy keywords in title + abstract
#   3+ advanced keywords   → "Advanced"
#   1+ easy keywords       → "Easy"
#   Everything else        → "Intermediate"

DIFFICULTY_KEYWORDS = {
    "advanced": [
        "theorem", "proof", "convergence", "stochastic",
        "gradient", "variational", "posterior", "bayesian",
        "asymptotic", "manifold", "topology", "eigenvalue",
        "optimization landscape", "regret bound",
    ],
    "easy": [
        "introduction to", "survey", "overview", "tutorial",
        "beginner", "practical guide", "simple", "easy",
        "getting started", "primer", "explained",
    ],
}

# Threshold: how many advanced keywords = Advanced difficulty
ADVANCED_THRESHOLD = 3


# ============================================================
# ATTENTION SCORE WEIGHTS
# ============================================================
# Used to rank papers for free users (top 20 selection)
# Each signal contributes to the paper's attention score
#
# attention_score =
#   (citation_count   * WEIGHT_CITATIONS)
# + (hacker_news_pts  * WEIGHT_HN)
# + (reddit_upvotes   * WEIGHT_REDDIT)
# + (hours_since_pub  * WEIGHT_RECENCY)  ← negative (newer = better)

WEIGHT_CITATIONS = 2.0    # citations matter most
WEIGHT_HN        = 1.5    # HN points
WEIGHT_REDDIT    = 1.0    # Reddit upvotes
WEIGHT_RECENCY   = -0.1   # small penalty per hour of age (newer = better)


# ============================================================
# APP SETTINGS
# ============================================================
APP_NAME    = "PaperLens"
APP_VERSION = "0.1.0"
DEBUG       = os.getenv("DEBUG", "false").lower() == "true"

# Backend server
HOST = "0.0.0.0"
PORT = 8000

# Frontend URL (for CORS and email links)
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

# Paper Peeler upload safety
MAX_PDF_UPLOAD_MB = int(os.getenv("MAX_PDF_UPLOAD_MB", "25"))
MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "40"))


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def get_active_model() -> str:
    """
    Returns the exact model string for the currently active LLM.

    Usage in any file:
        from config import get_active_model
        model = get_active_model()
        # Returns "gemini-2.0-flash" right now
        # Returns "claude-sonnet-4-6" when you switch to Claude
    """
    return MODELS.get(ACTIVE_LLM, MODELS["openai"])


def get_active_llm() -> str:
    """
    Returns which LLM provider is active.
    Returns: "openai", "gemini", or "claude"
    """
    return ACTIVE_LLM


def is_pro_user(plan: str) -> bool:
    """
    Check if a user has Pro or Team access.
    Usage: if is_pro_user(user.plan): ...
    """
    return plan in ("pro", "team")


def get_peel_limit(plan: str) -> int:
    """
    Returns the Paper Peeler limit for a given plan.
    Returns -1 for unlimited (Pro/Team).
    """
    if is_pro_user(plan):
        return PRO_PEEL_LIMIT
    return FREE_PEEL_LIMIT


def get_chat_limit(plan: str) -> int:
    """Returns the paper-chat response limit for a given plan."""
    if is_pro_user(plan):
        return PRO_CHAT_LIMIT
    return FREE_CHAT_LIMIT


def validate_config() -> list:
    """
    Checks that all required environment variables are set.
    Call this when the app starts to catch missing keys early.
    Returns a list of missing variable names.
    """
    required = {}
    # Supabase only required when not in DEBUG or using supabase storage
    if not DEBUG and PEELER_STORAGE != "memory":
        required["SUPABASE_URL"]              = SUPABASE_URL
        required["SUPABASE_ANON_KEY"]         = SUPABASE_ANON_KEY
        required["SUPABASE_SERVICE_ROLE_KEY"] = SUPABASE_SERVICE_KEY
    # LLM key: only required if NO fallback key exists
    has_any_llm_key = bool(OPENAI_API_KEY or GROQ_API_KEY or GEMINI_API_KEY or CLAUDE_API_KEY)
    if not has_any_llm_key:
        required["OPENAI_API_KEY_or_GROQ_API_KEY"] = None
    missing = [name for name, value in required.items() if not value]
    return missing


# ============================================================
# QUICK TEST — run this file directly to verify config loads
# Command: python config.py
# ============================================================
if __name__ == "__main__":
    print(f"\n{'='*50}")
    print(f"  {APP_NAME} v{APP_VERSION} — Config Check")
    print(f"{'='*50}")

    missing = validate_config()
    if missing:
        print(f"\n❌ Missing environment variables:")
        for m in missing:
            print(f"   - {m}")
        print(f"\n   Add these to your .env file\n")
    else:
        print(f"\n✅ All required environment variables found")

    print(f"\n📋 Active settings:")
    print(f"   LLM Provider  : {ACTIVE_LLM}")
    print(f"   Active model  : {get_active_model()}")
    print(f"   Fetch interval: every {FETCH_INTERVAL_MINUTES} minutes")
    print(f"   Free digest   : {FREE_DIGEST_TIME} daily")
    print(f"   Free top papers: {FREE_TOP_PAPERS}")
    print(f"   Free peel limit: {FREE_PEEL_LIMIT}/month")
    print(f"   arXiv categories: {', '.join(ARXIV_CATEGORIES)}")
    print(f"   Topics supported: {len(TOPIC_MAP)}")
    print(f"   Debug mode    : {DEBUG}")
    print(f"\n{'='*50}\n")
