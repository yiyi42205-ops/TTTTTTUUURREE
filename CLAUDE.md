# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

疑騙真星 TrueRating is a tool that audits Google Maps restaurant reviews for authenticity. Restaurants in Taiwan commonly run "check-in for a free dish" / "5-star review for a drink" promotions that inflate their star rating with non-experience-driven reviews. Given a Google Maps store URL, the app scrapes recent reviews, runs a two-stage audit pipeline (local heuristics + LLM semantic review) to flag likely "washed" reviews, and produces a trust-weighted "Filtered Rating" alongside the official rating. See [`TRUE_RATING_LOGIC.md`](./TRUE_RATING_LOGIC.md) for the exact scoring math (Stage 1 rules, Stage 2 confidence formula, Trust Score / Filtered Rating aggregation) — don't re-derive it from code, it's spelled out there.

## Commands

- `npm i` — install frontend dependencies
- `npm run dev:scraper` — start the Flask backend (`review_scraper/server.py`, port 5001), which serves `/api/scrape`. Must be running for the frontend's scraper feature to work (Stage 2 LLM audit itself calls Gemini directly from the browser, not through this backend).
- `npm run dev` — start the Vite dev server. Vite proxies `/api/*` to `http://127.0.0.1:5001`, so `npm run dev:scraper` needs to be running alongside it (two terminals, or via `./run.sh`).
- `npm run build` — production build (`vite build`)
- `./run.sh` — interactive one-shot setup + run script (macOS-oriented): detects a compatible Python (3.9–3.13), creates `review_scraper/venv`, installs `review_scraper/requirements.txt`, installs the Playwright Chromium browser, optionally installs/pulls an Ollama model, then starts both `npm run dev:scraper` (backgrounded) and `npm run dev`. This is the recommended first-run path.
- Python offline evaluation scripts (not a test suite — see below), run with the venv Python, e.g. `review_scraper/venv/bin/python evaluate.py`:
  - `evaluate.py` — runs the Stage 1 rule engine over labeled CSVs in `restaurant_data/`, reports precision/recall/F1 against human labels
  - `evaluate_v2.py` — grid-searches the Stage 1 confidence threshold and produces Stage 2 LLM sampling input (writes `tune_results.json`, `llm_input.json`)
  - `sample_fp.py` — samples false-positive stores and writes ready-to-paste Gemini prompts into `gemini_prompts/*.txt`
  - `check_data.py` — checks CSV column consistency / `Time` field format across `restaurant_data/`

There is **no lint script, no automated test suite (JS or Python), and no `tsconfig.json`** in this repo. Don't go looking for a test runner or type-check command — none is configured.

## Architecture

### Frontend (`src/`)
A flat 3-page React app (not a component-library-driven one, despite ~20 `@radix-ui/*`/`@mui/*` packages listed in `package.json` — they're unused scaffolding from the original Figma Make template and can be ignored).

- `src/app/routes.ts` — react-router v7 `createBrowserRouter`: `/` (`Home.tsx`), `/analyzer` (`Analyzer.tsx`), `/results` (`Results.tsx`). Data is passed between pages via `navigate(path, { state })`, not URL params.
- `src/app/pages/Analyzer.tsx` — input form: either pick preset restaurants (matched against the bundled demo dataset) or paste Google Maps URLs (POSTed to `/api/scrape`). Also holds audit config (Gemini API key, sample count), persisted to `localStorage`. There is no local-model option anymore — Gemini is the only Stage 2 audit path.
- `src/app/pages/Results.tsx` — runs the actual audit: `handleGeminiAudit` calls the Gemini API directly from the browser (`https://generativelanguage.googleapis.com/.../gemini-2.5-flash:generateContent?key=<userSuppliedKey>`) for Stage 2. Final aggregation goes through `aggregateAuditedReviews` from `auditEngine.ts` (shared with the Stage-1-only pass) rather than reimplementing the weighting formula inline.
- `src/app/utils/auditEngine.ts` — `auditReview` (Stage 1 heuristics: incentive keyword/regex matching, Jaccard n-gram template-similarity duplicate detection via `getNGrams`/`calculateJaccardSimilarity`, and a neutral `'no_text'` category for star-only reviews with no written text), `computeShopStats` (Stage-1-only convenience wrapper), and `aggregateAuditedReviews` (the shared weighting/Trust Score/Filtered Rating aggregation, reused by both the Stage-1 pass and the post-Stage-2 merge in `Results.tsx`). Also exports `computeSpikeMonths`/`getReviewTemporalContext`, the shared review-volume-spike detection used both to flag no-text reviews and to build the Stage 2 LLM payload.
- `src/app/utils/csvParser.ts` + `src/app/data/restaurantsData.ts` — hand-rolled CSV parser that loads 18 CSVs from `restaurant_data/` via Vite's `?raw` import (enabled by `assetsInclude` in `vite.config.ts`) to build the built-in demo dataset.
- `vite.config.ts` — `@` alias → `src/`; a `figmaAssetResolver()` plugin (template leftover); dev-server proxy `/api` → `http://127.0.0.1:5001` (the Flask backend, so relative `fetch('/api/...')` calls in the frontend reach it without CORS issues).
- Styling is Tailwind v4 via `@tailwindcss/vite` — `postcss.config.mjs` is intentionally empty (v4 doesn't need manual PostCSS config).

### Backend (`review_scraper/`)
`review_scraper/server.py` is the single backend implementation: a Flask app (port 5001) with just `GET /` and `POST /api/scrape`, started via `npm run dev:scraper`. (There used to be a second implementation as a Vite dev-middleware — removed in favor of this one, plus a Vite proxy. There was also an `/api/audit-local` route that proxied to a local Ollama model — removed entirely; Gemini is now the only Stage 2 LLM path, called client-side directly from the browser with a user-supplied API key. No Python code calls any LLM API.)

Other backend files:
- `review_scraper/scraper.py` — Playwright + BeautifulSoup4 + `playwright-stealth`. Google Maps CSS selectors are hardcoded (`div.jftiEf` review card, `span.kvMYJc` rating, `span.rsqaWe` relative time, `span.wiI7pd` text) and fragile to Google Maps DOM changes. `parse_relative_time()` converts Chinese/English relative dates ("6 個月前", "a month ago") to absolute dates.
- `review_scraper/audit_prompt.txt` — the Stage 2 LLM prompt template (`{store_name}`, `{review_count}`, `{reviews_json}` placeholders), imported into the frontend via `?raw`.

### Data (`restaurant_data/`, `gemini_prompts/`)
- `restaurant_data/` holds 18 hand-labeled CSVs organized as `<類別>__<有洗|沒洗>/` (category, e.g. 拉麵/手搖/便當, crossed with washed/clean). These back both the frontend demo dataset and the offline `evaluate*.py` scripts.
- `gemini_prompts/*.txt` are pre-generated prompts (output of `sample_fp.py`) meant for manual copy-paste into the Gemini web UI — not something called programmatically.

### Known limitations (from README)
- The scraper needs a local Playwright browser, so it can't run on serverless platforms as-is; `vercel.json` only does SPA rewrite routing for the static frontend build, it doesn't run the Python backend.
- Each analysis samples roughly the most recent 100 reviews per store.
- Keyword rules and prompts are tuned for Traditional Chinese restaurant reviews.
- Scraper CSS selectors depend on Google Maps' current DOM structure and can break on redesigns.
