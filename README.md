# PaperLens

### Track the field. Understand any paper. Every paper, peeled.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Hackathon](https://img.shields.io/badge/AI--Builders-Hackathon%20MVP-orange)](https://github.com/vansh7266/PaperLens-MVP)
[![Python](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.135%2B-green.svg)](https://fastapi.tiangolo.com/)
[![Status](https://img.shields.io/badge/Status-MVP%20%2F%20Prototype-yellow)](https://github.com/vansh7266/PaperLens-MVP)

---

PaperLens is an AI research intelligence platform that solves two problems at once: **tracking the AI field in real time** and **deeply understanding any paper you find** — in one unified workflow.

There are tools that track research. There are tools that summarize papers. Nobody has combined both into a single intelligent platform — until PaperLens.

> **Built for the AI Builders Hackathon** by Vansh Gupta (BTech 2nd Year, IIIT Bhopal), pair-programmed with Claude (Anthropic) using an AI-assisted Codex workflow.

> **Honest status:** This is a working MVP. The core loop — Radar + multi-agent Peeler + caching + community ratings — is fully functional with real data. Full Version 1 ships in a few weeks with OpenAI production backend, Pro plan, and payment integration.

---

## What PaperLens Does

### Research Radar — Track the field in real time
Live feed of every new AI/ML paper, model release, and lab announcement. Scraped from arXiv (5 categories), HuggingFace, and RSS feeds from OpenAI, DeepMind, Anthropic, Meta AI, and Mistral — refreshing every 30 minutes. Over 1,100 real items already in the database.

Every item passes through an intelligence pipeline: topic classification, difficulty rating, attention scoring, and a signal label (High Signal / Worth Peeling / Community Pick / Trending). The feed re-ranks automatically by blending algorithmic scores with live community ratings.

### Paper Peeler — Multi-agent deep analysis
Paste an arXiv URL, DOI, title, or upload a PDF. Three specialized agents run in parallel:

- **Walkthrough Agent** — Plain-language teaching of the full paper: the problem, prior work, what was proposed, why it works, the results, and a verdict.
- **Architecture Agent** — Extracts the actual model architecture from the paper's own text and renders it as a live, animated, step-through diagram. Each node can be peeled open to reveal internal sub-components. Unique to PaperLens.
- **Math Agent** — Every method-defining equation, with each symbol explained, what it computes, and what breaks if you change it.

After the peel: a **grounded chat** interface, where every answer is grounded in the actual paper content with full conversation history.

---

## Key Design Decisions

**Global peel caching** — Peels are cached globally in the database. The first user to peel a paper pays the API cost. Every user after that gets it instantly: zero credits, zero API calls. Message shown: *"Served from cache — 0 credits used."* The platform gets cheaper and faster as it scales.

**Community ratings flywheel** — Every card has a 5-star global rating. All users see the same aggregate score. The feed blends algorithmic attention scores with community ratings. More users = better signal for everyone. It compounds.

**Provider-agnostic LLM system** — The multi-agent system reads available API keys at runtime and auto-selects. Currently running Groq (Llama 3.1 8B for Walkthrough, Llama 3.3 70B for Architecture + Math). Adding one OpenAI key upgrades everything to GPT-4o automatically — all three agents in parallel. No code change. Cerebras and OpenRouter wired as fallbacks.

**Smart scheduling** — arXiv only publishes weekdays ~6 AM UTC. The scraper scheduler knows this and doesn't waste API calls on weekends.

**Demo mode** — One-click access on the login page, no signup required. Loads a pre-analyzed copy of *Attention Is All You Need* so anyone can see the full system immediately.

**Transparency notices** — Yellow notice strips appear throughout the app wherever a feature is still in progress (AI summaries, daily brief). Honest markers, not excuses.

---

## Architecture

```
                    +------------------------------------------+
                    |              USER FRONTEND               |
                    |  Vanilla JS · CSS · Three.js · KaTeX     |
                    |  Deployed: Netlify                        |
                    +--------------------+---------------------+
                                         |
                                         | HTTP / SSE Streams
                                         v
                    +--------------------+---------------------+
                    |            FASTAPI BACKEND               |
                    |            Deployed: Render              |
                    +------+-------------+--------------+------+
                           |             |              |
         Radar Scheduler   |    Supabase |              | LLM APIs
                           v             v              v
              +-------------------+  +---------+  +-------------------+
              |   RESEARCH RADAR  |  | POSTGRES|  |  MULTI-AGENT      |
              | arXiv · HF · RSS  |  |  + AUTH |  |  PEELER SYSTEM    |
              +-------------------+  +---------+  | Groq / OpenAI /   |
                                                   | Cerebras /        |
                                                   | OpenRouter        |
                                                   +-------------------+
```

---

## Technology Stack

### Backend
| Component | Technology |
|---|---|
| API Framework | FastAPI (Python 3.12), async + SSE streaming |
| Database | Supabase (PostgreSQL) — peels, ratings, radar feed, auth |
| PDF Extraction | PyMuPDF + PyMuPDF4LLM |
| LLM Providers | Groq (primary), OpenAI, Cerebras, OpenRouter (fallbacks) |
| Scheduler | APScheduler — async background scraper jobs |
| Scrapers | arXiv API, HuggingFace daily papers, RSS (OpenAI / DeepMind / Anthropic / Meta / Mistral) |

### Frontend
| Component | Technology |
|---|---|
| Scripting | Vanilla JavaScript (no framework) |
| 3D Animations | Three.js (CDN) — globe splash, star field hero, lens shape |
| Math Rendering | KaTeX |
| Auth | Supabase JS SDK |
| Styling | CSS custom properties, glassmorphism, CSS perspective grid |
| Deployment | Netlify |

---

## Project Structure

```
PaperLens/
├── backend/
│   ├── main.py                     # FastAPI entrypoint & lifespan
│   ├── config.py                   # Environment config & validation
│   ├── core/
│   │   ├── peeler_service.py       # Multi-agent orchestration engine
│   │   ├── peeler_llm.py           # Agent prompts & structured outputs
│   │   ├── peeler_resolver.py      # Resolves arXiv IDs, DOIs, URLs, PDFs
│   │   ├── peeler_models.py        # Pydantic schemas for Peeler
│   │   ├── peeler_repository.py    # Supabase CRUD for peel cache
│   │   └── pdf_extractor.py        # PDF → Markdown via PyMuPDF
│   ├── radar/
│   │   ├── pipeline/
│   │   │   ├── scheduler.py        # Background scraper scheduler
│   │   │   ├── processor.py        # Feed parser, deduplicator, analyzer
│   │   │   └── summarizer.py       # Signal scoring & difficulty tagging
│   │   ├── scrapers/
│   │   │   ├── arxiv.py            # arXiv scraper
│   │   │   ├── huggingface.py      # HuggingFace daily papers
│   │   │   └── rss_blogs.py        # Lab blog RSS feeds
│   │   ├── routes/
│   │   │   ├── radar.py            # Feed & stats routes
│   │   │   ├── rating.py           # Community 5-star rating
│   │   │   └── saved.py            # Reading list bookmarks
│   │   └── models.py               # Radar Pydantic schemas
│   ├── routes/
│   │   ├── auth.py                 # Supabase session handlers
│   │   └── peeler.py               # SSE streaming routes
│   ├── supabase/
│   │   └── radar_schema.sql        # DB schema (tables, indexes, triggers)
│   └── tests/
├── frontend/
│   ├── index.html                  # Landing page (3D globe → star field)
│   ├── login.html                  # Login + demo mode
│   ├── signup.html                 # Registration
│   ├── dashboard.html              # Command center + stats
│   ├── peeler.html                 # Multi-agent Paper Peeler
│   ├── radar.html                  # Research Radar feed
│   ├── settings.html               # Profile & preferences
│   └── assets/peeler/
│       ├── app.js                  # Peeler state engine
│       ├── api.js                  # SSE streaming client
│       ├── config.js               # Environment config
│       └── peeler.css              # Glassmorphic styles
└── README.md
```

---

## Setup & Installation

### 1. Database
Run [`backend/supabase/radar_schema.sql`](backend/supabase/radar_schema.sql) in your Supabase SQL Editor to create all required tables, indexes, and triggers.

### 2. Backend
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip && pip install .
cp .env.example .env
```

Configure `.env`:
```env
SUPABASE_URL=your_supabase_project_url
SUPABASE_KEY=your_supabase_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key
GROQ_API_KEY=your_groq_api_key
OPENAI_API_KEY=your_openai_api_key   # optional — auto-upgrades agents when present
```

```bash
uvicorn main:app --reload --port 8000
```

### 3. Frontend
```bash
cd frontend
npx serve . -p 5173
```

Open `http://localhost:5173`. Use **Try a Demo** on the login page to explore without an account.

---

## What's Working vs. What's Coming

| Feature | Status |
|---|---|
| Research Radar — live scraping (arXiv, HF, RSS) | Live |
| Intelligence pipeline (classification, scoring, signal labels) | Live |
| Community 5-star ratings (global, re-ranking) | Live |
| Save to reading list | Live |
| Smart weekend scheduling | Live |
| Multi-agent Paper Peeler (3 parallel agents) | Live |
| Global peel caching (0-credit repeat loads) | Live |
| Architecture diagram (animated, step-through) | Live |
| Math equation breakdown | Live |
| Grounded chat | Live |
| Demo mode (no signup) | Live |
| AI summaries on Radar feed | V2 |
| AI-written daily brief | V2 |
| OpenAI production backend | V2 |
| Pro plan + payment integration | V2 |
| WhatsApp morning digest bot | V2 |

---

## Contributors

- **Vansh Gupta** — Lead Developer, BTech 2nd Year, IIIT Bhopal
  [![GitHub](https://img.shields.io/badge/GitHub-vansh7266-lightgrey?logo=github)](https://github.com/vansh7266)

- **Codex (OpenAI)** — AI Coding Companion & primary Codex workflow partner
  [![OpenAI](https://img.shields.io/badge/OpenAI-Codex-412991?logo=openai&logoColor=white)](https://openai.com/codex)

- **Claude (Anthropic)** — AI pair-programming partner throughout the build
  [![Anthropic](https://img.shields.io/badge/Anthropic-Claude-blueviolet)](https://anthropic.com)

- **Antigravity (Google DeepMind)** — AI Coding Companion
  [![DeepMind](https://img.shields.io/badge/Google-DeepMind-4285F4?logo=google&logoColor=white)](https://deepmind.google)

---

*Built for the AI Builders Hackathon. Track the field. Understand any paper. Every paper, peeled.*
