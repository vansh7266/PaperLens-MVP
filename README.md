# PaperLens

**Research Intelligence Workspace — Open a paper. Watch it turn into context.**

> AI Builders Hackathon · Phase 1 MVP · Built by Vansh Gupta (BTech 2nd Year, IIIT Bhopal)

---

## What is PaperLens?

PaperLens takes any AI/ML research paper (arXiv ID, URL, DOI, or uploaded PDF) and turns it into a structured 5-stage learning experience:

| Stage | What it does |
|-------|-------------|
| **01 Paper Walkthrough** | Streams 13 teaching chapters grounded in the paper's own text — with HIGH / MEDIUM confidence badges |
| **02 Architecture** | Draws a live interactive SVG blueprint of the paper's architecture. Peel open any block to see what's inside |
| **03 Math Peel** | Extracts key equations, renders them in KaTeX, and explains every symbol + its role |
| **04 Ask Anything** | Grounded AI chat — every answer is sourced from the paper itself |

---

## Features

- Auto-detect input type (arXiv / DOI / URL / Title keywords / PDF upload)
- **Smart caching**: a paper is peeled once, cached forever in DB — subsequent loads are instant and consume zero credits
- Streaming walkthrough with 13 chapter types and confidence badges
- Live SVG architecture canvas (supports Transformer, CNN, and more)
- Peel-open any architecture node → deep-dive sub-blueprint + back-to-overview button
- BFS node stepping (navigate 1/N through the full graph)
- Inspector panel + data flow story sidebar
- KaTeX math rendering with custom LaTeX normalisation (fixes LLM-generated nesting bugs)
- Symbol-by-symbol equation breakdown (Plain meaning / Role in architecture / Behavior if changed)
- Streaming grounded AI chat — answers cite the paper's own text
- Section pill navigation (Walk / Arch / Math / Chat)
- Usage metering (Peel credits + Chat credits displayed in topbar)
- Replay button to re-experience the full peel
- Supabase auth (session tokens, thread persistence)
- Dark space-themed UI with CSS `@property` ink-draw animations

---

## Tech Stack

**AI / LLM**
- **Primary**: OpenAI API (GPT models) — used for all production inference
- **Fallback**: Groq API (Llama 3.3 70B) — fallback if OpenAI is unavailable; currently used in development/testing

**Backend**
- Python 3.11 + FastAPI
- Supabase (PostgreSQL + Auth)
- PyMuPDF for PDF text extraction
- arXiv / Semantic Scholar APIs for paper metadata
- SSE streaming for real-time token delivery to the frontend

**Frontend**
- Vanilla JS (IIFE pattern, zero framework dependency)
- KaTeX for math rendering
- SVG canvas drawn programmatically from LLM-generated graph data
- CSS `@property` custom property animations (ink sweep on math equations)
- Supabase JS SDK for client-side auth

---

## Project Structure

```
PaperLens/
├── backend/
│   ├── main.py                    # FastAPI app entry point
│   ├── config.py                  # Env-var config (OpenAI + Groq + Supabase)
│   └── core/
│       ├── peeler_service.py      # Orchestrates the 5-stage peel
│       ├── peeler_llm.py          # LLM prompts for each stage
│       ├── peeler_resolver.py     # arXiv / DOI / PDF resolver
│       ├── peeler_repository.py   # Supabase CRUD (threads, jobs, cache)
│       └── pdf_extractor.py       # PDF text extraction (PyMuPDF)
├── frontend/
│   ├── peeler.html                # Main Paper Peeler app
│   ├── dashboard.html             # Feed + navigation shell
│   └── assets/peeler/
│       ├── app.js                 # All client logic (~3000 lines)
│       ├── api.js                 # API + SSE streaming client
│       └── peeler.css             # All styles + animations
└── README.md
```

---

## Setup & Run

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create `backend/.env`:
```env
OPENAI_API_KEY=your_openai_key_here
GROQ_API_KEY=your_groq_key_here          # fallback
SUPABASE_URL=your_supabase_url
SUPABASE_ANON_KEY=your_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
```

```bash
uvicorn main:app --reload --port 8000
```

### Frontend

Serve `frontend/` as static files — simplest is to mount it in FastAPI (same domain, no CORS):

```python
from fastapi.staticfiles import StaticFiles
app.mount("/", StaticFiles(directory="../frontend", html=True), name="static")
```

Or during development:
```bash
cd frontend && npx serve . -p 5173
```

---

## Deployment

- **Backend**: Railway or Render — `uvicorn main:app --port 8000`
- **Frontend**: Mounted as static files on the same FastAPI server
- **Env vars**: Set in host dashboard — never commit `.env`

---

## Author

**Vansh Gupta**
BTech 2nd Year · IIIT Bhopal

GitHub: [github.com/vansh7266/PaperLens-MVP](https://github.com/vansh7266/PaperLens-MVP)
