# 🔬 PaperLens

### **Research Intelligence Workspace — Open a paper. Watch it turn into context.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Hackathon](https://img.shields.io/badge/AI--Builders-Hackathon%20MVP-orange)](https://github.com/vansh7266/PaperLens-MVP)
[![Python Version](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.135%2B-green.svg)](https://fastapi.tiangolo.com/)

---

PaperLens is a high-performance **Research Intelligence Platform** designed to solve a major problem for AI researchers and builders: the cognitive overload of reading and tracking modern research papers. 

Instead of reading static, dense PDFs, PaperLens transforms any research paper (via arXiv ID, URL, DOI, or raw PDF upload) into an **interactive, structured 5-stage deep learning experience**, coupled with a **real-time Research Radar** that automatically aggregates, filters, and summarizes daily publications in your areas of interest.

> [!NOTE]  
> Built for the **AI Builders Hackathon (Phase 1 MVP)** by **Vansh Gupta** (BTech 2nd Year, IIIT Bhopal) in pair-programming partnership with **Antigravity** (Google DeepMind).

---

## 🧭 System Architecture Overview

```
                      +------------------------------------------+
                      |               USER FRONTEND              |
                      |   (HTML5, Vanilla JS, KaTeX, Supabase)   |
                      +--------------------+---------------------+
                                           |
                                           | HTTP Requests & SSE Streams
                                           v
                      +--------------------+---------------------+
                      |             FASTAPI BACKEND              |
                      +------+-------------+--------------+------+
                             |             |              |
           Scraper Scheduler |             | Supabase     | LLM APIs
                             v             v              v
+------------------------------+     +-------------+    +---------------+
|        RESEARCH RADAR        |     |  POSTGRES   |    |  OPENAI GPT / |
|   (arXiv, HF, RSS scrapers)  |     |  & AUTH DB  |    |  GROQ LLAMA 3 |
+------------------------------+     +-------------+    +---------------+
```

---

## ⚡ Core Pillars & Key Features

### 1. 🔬 The Paper Peeler (Deep-Dive Analysis)
Deconstructs complex research papers into five bite-sized, interactive pillars:
* **Stage 1: Structured Walkthrough** — Streams 13 sequential learning chapters (Introduction, Core Concept, Methods, Results, Limitations, etc.) with automated confidence/evidence check badges (`High` or `Medium`).
* **Stage 2: SVG Network Architecture Blueprint** — Renders an interactive, programmatically-generated SVG block diagram of the model. Users can click any block to "peel it open" and reveal internal sub-blueprints (e.g., standard Transformer block -> self-attention + MLP).
* **Stage 3: Math Peel** — Automatically extracts key formulas, formats them beautifully using KaTeX, and displays a step-by-step breakdown of every symbol's name, role in the architecture, and theoretical behavior if changed.
* **Stage 4: Grounded Chat** — A fully vector-grounded Q&A chatbot that answers questions using direct citations from the paper's own text.
* **Smart DB Caching** — Every paper is peeled once and cached forever in the PostgreSQL database. Subsequent loads for any user globally are instant and consume zero API credits.

### 2. 📡 The Research Radar (Smart Aggregation Feed)
A comprehensive daily feed that acts as a custom newsletter for AI research:
* **Automated Scrapers** — Periodic background scheduler scraping new papers from arXiv, Hugging Face, and top AI blog feeds.
* **Signal Labeling** — Intelligent LLM labeling categorizing papers into high-impact tags: `High Signal`, `Worth Peeling`, `Worth Watching`, or `Quick Skim`.
* **Personalized Topics** — Customize your dashboard feed by selecting topics like *Deep Learning Architecture*, *NLP*, *Computer Vision*, *LLM Agents*, and *Optimization*.
* **Dynamic Daily Email Digests** — Set up fully customized digest schedules (e.g., daily at 8:00 AM) sent straight to your email via a secure, passwordless OTP verification system.
* **Saved Items & Star Ratings** — Rate papers on a 5-star scale to help rank trending content, and save critical papers to your personal reading list.

---

## 🛠️ The Technology Stack

### Backend Services
* **FastAPI (Python 3.12)** — Fast, asynchronous routing and Server-Sent Events (SSE) streaming.
* **Supabase & PostgreSQL** — Core database for caching peeled paper JSONs, storing scraped feeds, persistent user reading lists, ratings, and auth session tables.
* **PyMuPDF & PyMuPDF4LLM** — For high-fidelity text extraction, page parsing, and Markdown cleaning of research paper PDFs.
* **Groq API & OpenAI API** — Powering rapid fallback LLM inference (using Llama 3.3 70B & GPT-4o models).
* **APScheduler** — Asynchronous scheduler driving the background Research Radar scrapers.

### Frontend Interface
* **Vanilla JavaScript (IIFE Pattern)** — Lightweight, standard-compliant scripting with no runtime framework overhead.
* **Supabase Client JS SDK** — Client-side user onboarding, authentication, and secure session management.
* **KaTeX** — Lightning-fast, serverless LaTeX math rendering.
* **CSS Custom Properties (`@property`) & Vanilla CSS** — Premium, responsive dark-themed dashboard, sleek frosted glass layouts, and sweep ink-draw animations.

---

## 📂 Project Structure

```
PaperLens/
├── backend/
│   ├── main.py                     # FastAPI app entrypoint & lifespan managers
│   ├── config.py                   # System configuration & environment validations
│   ├── core/
│   │   ├── peeler_service.py       # Manages the 5-stage paper analysis engine
│   │   ├── peeler_llm.py           # Core prompts and structured outputs for Peeler
│   │   ├── peeler_resolver.py      # Resolves arXiv IDs, DOIs, web URLs, & raw uploads
│   │   ├── peeler_models.py        # Pydantic schemas for the Peeler endpoints
│   │   ├── peeler_repository.py    # Supabase CRUD operations for Peeler cache
│   │   └── pdf_extractor.py        # PDF-to-Markdown text extractor using PyMuPDF
│   ├── radar/                      # Automated Content Radar module
│   │   ├── core/
│   │   │   └── database.py         # Async Supabase DB connections for Scrapers
│   │   ├── pipeline/
│   │   │   ├── scheduler.py        # Asynchronous background scraper scheduler
│   │   │   ├── processor.py        # Feeds parser, deduplicator & analyzer
│   │   │   └── summarizer.py       # Signal scoring, item difficulty, & key highlights
│   │   ├── scrapers/
│   │   │   ├── base.py             # Scraper abstract class
│   │   │   ├── arxiv.py            # Custom arXiv search & scraper
│   │   │   ├── huggingface.py      # HuggingFace daily paper list fetcher
│   │   │   └── rss_blogs.py        # OpenAI, Anthropic, & DeepMind RSS Scraper
│   │   ├── routes/
│   │   │   ├── radar.py            # Feeds, preferences & stats routes
│   │   │   ├── email.py            # OTP generation, verification & daily digests
│   │   │   ├── rating.py           # 5-star community ranking router
│   │   │   └── saved.py            # Reading list bookmarking routes
│   │   └── models.py               # Radar feed and digest Pydantic schemas
│   ├── routes/
│   │   ├── auth.py                 # Supabase session handlers & auth helpers
│   │   └── peeler.py               # Main paper parsing SSE streaming routes
│   ├── supabase/
│   │   └── radar_schema.sql        # Supabase database SQL schema
│   └── tests/                      # Automated PyTest suites for Peeler & Radar
├── frontend/
│   ├── index.html                  # Landing Page
│   ├── login.html                  # Onboarding Authentication
│   ├── signup.html                 # Registration
│   ├── onboarding.html             # Profile creation & interest select
│   ├── dashboard.html              # Main feed shell
│   ├── peeler.html                 # Interactive 5-stage Paper Peeler
│   ├── radar.html                  # Custom feeds, ratings, and reading list
│   ├── settings.html               # Digest preferences, email OTP verification, & profile
│   └── assets/peeler/
│       ├── app.js                  # Peeler workspace state engine (~3000 lines)
│       ├── api.js                  # Streams API client utilizing EventSource
│       ├── config.js               # Environment URL and Supabase credentials
│       └── peeler.css              # Premium responsive glassmorphic stylesheets
└── README.md
```

---

## 🚀 Setup & Installation

### Prerequisite DB Configuration
Execute the queries in [radar_schema.sql](file:///Users/vanshgupta/Desktop/PaperLens/backend/supabase/radar_schema.sql) in your **Supabase SQL Editor** to establish the required tables, indexes, functions, and trigger security hooks for Paper Radar.

### 1. Run Backend Services
```bash
cd backend

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate

# Install package dependencies
pip install --upgrade pip
pip install .

# Copy environment template & configure secrets
cp .env.example .env
```

Configure your `.env` keys:
```env
SUPABASE_URL=your_supabase_project_url
SUPABASE_KEY=your_supabase_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key
GROQ_API_KEY=your_groq_api_key
OPENAI_API_KEY=your_openai_api_key
```

Start the asynchronous API & Scheduler:
```bash
uvicorn main:app --reload --port 8000
```

---

### 2. Run Frontend
Serve the `frontend/` directory using any static file server. Since the API includes CORS headers matching local environments, you can run a simple server:
```bash
cd frontend
npx serve . -p 5173
```
Now navigate to `http://localhost:5173` to explore the workspace!

---

## 👥 Contributors

This MVP was created during pair-programming sessions by:

* **Vansh Gupta** (Lead Developer) — *BTech 2nd Year, IIIT Bhopal*
  * [![GitHub](https://img.shields.io/badge/GitHub-vansh7266-lightgrey?logo=github)](https://github.com/vansh7266)
* **Antigravity** (AI Coding Companion) — *Designed by Google DeepMind*
  * [![DeepMind](https://img.shields.io/badge/DeepMind-Google-blue)](https://deepmind.google/)

---
*Developed for the AI Builders Hackathon. Open a paper, let us turn it into context.*
