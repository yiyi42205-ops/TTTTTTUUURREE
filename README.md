<div align="center">

🇺🇸 English | [🇹🇼 繁體中文](README.zh-TW.md)

# TrueRating

**Google Maps Restaurant Review Authenticity Analyzer**

Detect fake Google Maps restaurant reviews inflated by "check-in for a free dish" promotions in Taiwan.

[![CI](https://github.com/yiyi42205-ops/TTTTTTUUURREE/actions/workflows/ci.yml/badge.svg)](https://github.com/yiyi42205-ops/TTTTTTUUURREE/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Live Demo](https://img.shields.io/badge/demo-truerating.fly.dev-blue)](https://truerating.fly.dev)

[Live Demo](https://truerating.fly.dev) ｜ [Feedback](https://docs.google.com/forms/d/e/1FAIpQLScXeQd2L43eDuMU_iv9GHGOedSkj3kKM-IEieeW6ieokHfA7g/viewform)

</div>

---

## The Problem

Restaurants in Taiwan routinely run promotions like "check in on social media for a free side dish" or "leave a 5-star review for a free drink." These campaigns flood Google Maps with non-experience-driven five-star reviews, making star ratings unreliable for consumers.

## The Solution

Paste a Google Maps store link or name → get an instant credibility analysis, an AI-filtered "true" star rating, key negative review summaries, and recommended dishes.

**1,500+ restaurants near National Taiwan University are pre-indexed — no sign-up or API key required.**

![Report demo](docs/images/report-demo.png)

---

## Key Features

| Feature | Description |
|---------|-------------|
| **Review Authenticity Audit** | Two-stage pipeline: rule engine + AI semantic analysis detects incentivized, templated, and low-content reviews |
| **Filtered Rating** | Confidence-weighted star rating after removing suspected fake reviews |
| **Trust Score** | Quantifies how suspicious the overall review structure is (0–100) |
| **Per-Review Verdict** | Each review is tagged with type, confidence, and I/A/D semantic scores |
| **AI Red-Flag Summary** | Extracts recurring complaints from authentic reviews, with sources |
| **AI Q&A** | Answer questions like "What dish should I order?" based on genuine reviews |

---

## Quick Start

### One-Command Setup (macOS)

```bash
git clone https://github.com/yiyi42205-ops/TTTTTTUUURREE.git
cd TTTTTTUUURREE
./run.sh
```

Automatically creates a Python venv, installs dependencies, prompts for `.env` setup, then starts both frontend and backend.

### Manual Setup

```bash
# 1. Environment variables
cp .env.example .env
# Set GEMINI_API_KEY (optional — cache-only mode without it)
# Set APIFY_TOKEN (optional — only needed for live scraping)

# 2. Install
npm i
cd review_scraper && python -m venv venv && source venv/bin/activate && pip install -r requirements.txt && cd ..

# 3. Start (two terminals)
npm run dev:scraper   # Flask backend :5001
npm run dev           # Vite frontend (proxies /api → :5001)
```

### Tests

```bash
npm test                                           # vitest (frontend, 15 tests)
review_scraper/venv/bin/python -m pytest tests/    # pytest (backend, 165 tests)
```

---

## Architecture

```
User enters a Google Maps store link or name
        │
        ▼
┌──────────────────────────────┐
│  Data Layer                  │  SQLite cache (1,500+ pre-indexed stores)
│  Cache hit → instant result  │  Cache miss → Apify live scrape
└──────────────────────────────┘
        │
        ▼
┌──────────────────────────────┐
│  Stage 1: Rule Engine        │  Promo keywords, template similarity,
│  rule_engine.py              │  review spike detection, low-info flagging
└──────────────────────────────┘
        │ ambiguous reviews
        ▼
┌──────────────────────────────┐
│  Stage 2: LLM Semantic Audit │  Gemini 2.5 Flash Lite
│  I/A/D scoring (1–5)        │  Server-side, key never exposed to client
└──────────────────────────────┘
        │
        ▼
┌──────────────────────────────┐
│  Scoring Engine              │  confidence → weight
│  aggregateAuditedReviews     │  Filtered Rating / Trust Score
└──────────────────────────────┘
```

See [`docs/TRUE_RATING_LOGIC.md`](./docs/TRUE_RATING_LOGIC.md) for the full scoring math.

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | Vite + React 18 (TypeScript), Tailwind v4 |
| Backend | Flask (Python), gunicorn |
| Scraper | Apify (primary); Playwright + stealth (optional fallback) |
| AI Engine | Gemini 2.5 Flash Lite (default), DeepSeek, OpenAI-compatible |
| Database | SQLite (persistent volume) |
| Deployment | Fly.io (CI/CD via GitHub Actions) |

---

## Project Structure

```
├── src/                    Frontend (React + TypeScript)
│   ├── app/pages/          Analyzer, Results, History, Settings, Home
│   ├── app/components/     TutorialModal, ReviewInspector, StoreVerdict
│   └── app/utils/          auditEngine.ts (types + Stage 2 functions)
├── review_scraper/         Backend (Flask)
│   ├── server.py           API endpoints
│   ├── rule_engine.py      Stage 1 rule engine (single implementation)
│   ├── llm_client.py       LLM batching + validation + typo recovery
│   ├── stage2_rules.py     Stage 2 post-LLM verdict logic
│   ├── cache_store.py      SQLite cache layer
│   ├── apify_scraper.py    Apify actor wrapper
│   └── normalize.py        Review format normalization
├── scripts/                Batch prerun scripts
├── eval/                   Offline evaluation (not a test suite)
├── restaurant_data/        Hand-labeled CSVs (18 stores, 6,000+ reviews)
├── tests/                  pytest (165) + vitest (15)
└── docs/                   Design docs & scoring formulas
```

---

## Scope & Limitations

- **Region**: Taiwan (rules and prompts are designed for Traditional Chinese restaurant reviews)
- **Language**: Traditional Chinese only
- **Database**: 1,500+ stores near NTU pre-indexed; other areas require a free Apify Token for live scraping
- **Sample size**: ~100–500 most recent reviews per analysis
- **Edge cases**: Short genuine reviews and low-effort fake reviews share similar textual features — false positives are possible

---

## Contributing

Issues and PRs are welcome. All changes (including docs) should go through the PR workflow.

---

## License

[MIT](LICENSE)

---

## Disclaimer

This is an academic research project. Analysis results are for consumer reference only and do not constitute an evaluation of any specific business. Review auditing is based on statistical models and AI semantic analysis, and may produce inaccurate results. We make no guarantees regarding the accuracy or completeness of the analysis.
