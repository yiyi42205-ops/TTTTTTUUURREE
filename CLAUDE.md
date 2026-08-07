# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

疑騙真星 TrueRating is a tool that audits Google Maps restaurant reviews for authenticity. Restaurants in Taiwan commonly run "check-in for a free dish" / "5-star review for a drink" promotions that inflate their star rating with non-experience-driven reviews. Given a Google Maps store URL, the app scrapes recent reviews, runs a two-stage audit pipeline (local heuristics + LLM semantic review) to flag likely "washed" reviews, and produces a trust-weighted "Filtered Rating" alongside the official rating. See [`docs/TRUE_RATING_LOGIC.md`](./docs/TRUE_RATING_LOGIC.md) for the exact scoring math (Stage 1 rules, Stage 2 confidence formula, Trust Score / Filtered Rating aggregation) — don't re-derive it from code, it's spelled out there.

## Workflow

This is a multi-contributor project. Push rules:
- **程式碼走 PR** — 所有程式碼變更必須開 PR，不可直接推 `main`。
- **文件可直接推** — `docs/`、`CLAUDE.md`、`README.md` 等純文件修改可直接推到 `main`，不需開 PR。
- **緊急修復事後補說明** — hotfix 可先合併，但事後必須在 PR 或 commit message 補上原因與影響範圍。

Standard PR flow:
1. Create a feature branch (`git checkout -b <branch-name>`).
2. Commit your work to the branch.
3. Push the branch and open a PR via `gh pr create`.
4. Merge only after review.

## Commands

- `npm i` — install frontend dependencies
- `npm run dev:scraper` — start the Flask backend (`review_scraper/server.py`, port 5001), which serves `/api/scrape` and `/api/audit`. Must be running for both scraping and Stage 2 Gemini audit to work (the frontend calls the backend for both).
- `npm run dev` — start the Vite dev server. Vite proxies `/api/*` to `http://127.0.0.1:5001`, so `npm run dev:scraper` needs to be running alongside it (two terminals, or via `./run.sh`).
- `npm run build` — production build (`vite build`)
- `./run.sh` — interactive one-shot setup + run script (macOS-oriented): detects a compatible Python (3.9–3.13), creates `review_scraper/venv`, installs `review_scraper/requirements.txt`, installs the Playwright Chromium browser, then starts both `npm run dev:scraper` (backgrounded) and `npm run dev`. This is the recommended first-run path.
- Python offline evaluation scripts live in `eval/` (not a test suite — see below), run with the venv Python from the repo root, e.g. `review_scraper/venv/bin/python eval/evaluate.py restaurant_data`:
  - `eval/evaluate.py` — runs the Stage 1 rule engine over labeled CSVs in `restaurant_data/`, reports precision/recall/F1 against human labels
  - `eval/evaluate_v2.py` — grid-searches the Stage 1 confidence threshold and produces Stage 2 LLM sampling input (writes `tune_results.json`, `llm_input.json`)
  - `eval/sample_fp.py` — samples false-positive stores and writes ready-to-paste Gemini prompts into `gemini_prompts/*.txt`
  - `eval/check_data.py` — checks CSV column consistency / `Time` field format across `restaurant_data/`

**Audit mode** (`VITE_AUDIT_MODE` env var): `production` (default) caps Stage 2 at 15 reviews with stratified sampling; `evaluate` removes the cap for full-coverage offline evaluation. Always use `evaluate` mode when running evaluation scripts against the frontend pipeline.

**Testing:**
- `npm test` — runs vitest (`src/app/utils/auditEngine.test.ts`): covers `aggregateAuditedReviews` weighting/Trust Score/Filtered Rating, `auditReview` Stage 1 heuristics, similarity signals, hot term signals, and nearby long review counts.
- `python -m pytest tests/` — Python backend tests (normalize, Apify scraper, Gemini client, prompt builder, audit API). Run from the repo root.
- There is **no lint script and no `tsconfig.json`** in this repo.

## Architecture

### Frontend (`src/`)
A flat 3-page React app (not a component-library-driven one, despite ~20 `@radix-ui/*`/`@mui/*` packages listed in `package.json` — they're unused scaffolding from the original Figma Make template and can be ignored).

- `src/app/routes.ts` — react-router v7 `createBrowserRouter`: `/` (`Home.tsx`), `/analyzer` (`Analyzer.tsx`), `/results` (`Results.tsx`). Data is passed between pages via `navigate(path, { state })`, not URL params.
- `src/app/pages/Analyzer.tsx` — input form: either pick preset restaurants (matched against the bundled demo dataset) or paste Google Maps URLs (POSTed to `/api/scrape`). Also holds audit config persisted to `localStorage`. Gemini is the only Stage 2 audit path.
- `src/app/pages/Results.tsx` — runs the actual audit: Stage 1 heuristics run locally, then ambiguous reviews are sent to the backend `POST /api/audit` for Stage 2 Gemini semantic review. Gemini returns three-dimension scores (`incentiveIntensity`, `sentimentAuthenticity`, `descriptionGranularity`) and a `reasoningPath` (CoT). The frontend computes a confidence score from these dimensions using a power-curve formula (`agreement^1.5 * 100`, range 0–100%; see `docs/TRUE_RATING_LOGIC.md` §4.3) and feeds it into `aggregateAuditedReviews` from `auditEngine.ts` for final Trust Score / Filtered Rating aggregation.
- `src/app/utils/auditEngine.ts` — `auditReview` (Stage 1 heuristics: incentive keyword/regex matching, Jaccard n-gram template-similarity duplicate detection via `getNGrams`/`calculateJaccardSimilarity`, and a neutral `'no_text'` category for star-only reviews with no written text), `computeShopStats` (Stage-1-only convenience wrapper), and `aggregateAuditedReviews` (the shared weighting/Trust Score/Filtered Rating aggregation, reused by both the Stage-1 pass and the post-Stage-2 merge in `Results.tsx`). Also exports `computeSpikeMonths`/`getReviewTemporalContext`, the shared review-volume-spike detection used both to flag no-text reviews and to build the Stage 2 LLM payload.
- `src/app/utils/csvParser.ts` + `src/app/data/restaurantsData.ts` — hand-rolled CSV parser that loads 18 CSVs from `restaurant_data/` via Vite's `?raw` import (enabled by `assetsInclude` in `vite.config.ts`) to build the built-in demo dataset.
- `vite.config.ts` — `@` alias → `src/`; a `figmaAssetResolver()` plugin (template leftover); dev-server proxy `/api` → `http://127.0.0.1:5001` (the Flask backend, so relative `fetch('/api/...')` calls in the frontend reach it without CORS issues).
- Styling is Tailwind v4 via `@tailwindcss/vite` — `postcss.config.mjs` is intentionally empty (v4 doesn't need manual PostCSS config).

### Backend (`review_scraper/`)
`review_scraper/server.py` is the single backend implementation: a Flask app (port 5001) with `GET /`, `POST /api/scrape`, and `POST /api/audit`, started via `npm run dev:scraper`. The `/api/audit` route receives ambiguous reviews from the frontend, calls Gemini via `gemini_client.py` (using `google.genai` SDK with a server-side `GEMINI_API_KEY`), and returns per-review audit results.

Other backend files:
- `review_scraper/apify_scraper.py` — primary scraping path using the Apify `compass/Google-Maps-Reviews-Scraper` actor. Requires `APIFY_TOKEN` env var. Falls back to Playwright on failure.
- `review_scraper/scraper.py` — Playwright + BeautifulSoup4 + `playwright-stealth` fallback scraper (opt-in via `ENABLE_PLAYWRIGHT_FALLBACK=true`). Google Maps CSS selectors are hardcoded and fragile to DOM changes. `parse_relative_time()` converts Chinese/English relative dates to absolute dates.
- `review_scraper/gemini_client.py` — batches reviews (~40 per batch) and calls Gemini 2.5 Flash via `google.genai` SDK for Stage 2 semantic audit. Parses JSON responses with markdown-fence stripping.
- `review_scraper/prompt_builder.py` — builds the Stage 2 prompt payload, injecting `daysElapsed` and `isSpikePeriod` as temporal context for Gemini.
- `review_scraper/audit_prompt.txt` — the Stage 2 LLM prompt template requiring three-dimension scores (1-5) and `reasoningPath` (CoT) per review.
- `review_scraper/normalize.py` — normalizes review fields from different scraper sources (Apify / Playwright) into a unified format.
- `review_scraper/cache_store.py` — caches scraped reviews to avoid redundant Apify calls; bypass with `?force=true`.

### Data (`restaurant_data/`, `gemini_prompts/`)
- `restaurant_data/` holds 18 hand-labeled CSVs organized as `<類別>__<有洗|沒洗>/` (category, e.g. 拉麵/手搖/便當, crossed with washed/clean). These back both the frontend demo dataset and the offline `eval/*.py` scripts.
- `gemini_prompts/*.txt` are pre-generated prompts (output of `eval/sample_fp.py`) meant for manual copy-paste into the Gemini web UI — not something called programmatically.

### Docs (`docs/`)
- `docs/TRUE_RATING_LOGIC.md` — the authoritative reference for Stage 1 rules, Stage 2 confidence formula, Trust Score / Filtered Rating aggregation math.
- `docs/HANDOFF.md` — changelog from the semester version to current.
- `docs/TrueRating_發布前大方向.md` — pre-launch roadmap and architectural decisions.

### Evaluation (`eval/`)
Offline evaluation scripts (not part of the test suite). Run from the repo root with the venv Python, e.g. `review_scraper/venv/bin/python eval/evaluate.py restaurant_data`. Generated output files (`results.json`, `report.md`, `tune_results.json`, `llm_input.json`) are gitignored.

### Known limitations (from README)
- The Python backend (Flask + Apify/Playwright) can't run on serverless platforms; `vercel.json` only does SPA rewrite routing for the static frontend build.
- Each analysis samples roughly the most recent 100 reviews per store.
- Keyword rules and prompts are tuned for Traditional Chinese restaurant reviews.
- Playwright fallback scraper's CSS selectors depend on Google Maps' current DOM structure and can break on redesigns.
