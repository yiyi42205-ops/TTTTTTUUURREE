# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

疑騙真星 TrueRating is a tool that audits Google Maps restaurant reviews for authenticity. Restaurants in Taiwan commonly run "check-in for a free dish" / "5-star review for a drink" promotions that inflate their star rating with non-experience-driven reviews. Given a Google Maps store URL, the app scrapes recent reviews, runs a two-stage audit pipeline (local heuristics + LLM semantic review) to flag likely "washed" reviews, and produces a trust-weighted "Filtered Rating" alongside the official rating. See [`docs/TRUE_RATING_LOGIC.md`](./docs/TRUE_RATING_LOGIC.md) for the exact scoring math (Stage 1 rules, Stage 2 confidence formula, Trust Score / Filtered Rating aggregation) — don't re-derive it from code, it's spelled out there.

## Deployment

- **Hosting**: Fly.io (`fly.toml`, app name `truerating`, region `nrt` Tokyo)
- **CI**: `.github/workflows/ci.yml` — runs `pytest tests/` and `npm test` (vitest) on every push/PR to `main`
- **CD**: `.github/workflows/deploy.yml` — on push to `main`, runs CI then `flyctl deploy --remote-only`
- **Container**: `Dockerfile` at repo root; production serves the Vite-built frontend as static files from Flask
- **Persistent storage**: Fly volume mounted at `/data`, `DB_PATH=/data/cache.db`

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
- `npm run dev:scraper` — start the Flask backend (`review_scraper/server.py`, port 5001), which serves `/api/scrape`, `/api/audit-rules`, `/api/audit`, `/api/store-summary`, `/api/summarize`, `/api/stats`. Must be running for all backend features (the frontend calls the backend for everything).
- `npm run dev` — start the Vite dev server. Vite proxies `/api/*` to `http://127.0.0.1:5001`, so `npm run dev:scraper` needs to be running alongside it (two terminals, or via `./run.sh`).
- `npm run build` — production build (`vite build`)
- `./run.sh` — interactive one-shot setup + run script (macOS-oriented): detects a compatible Python (3.9–3.13), creates `review_scraper/venv`, installs `review_scraper/requirements.txt`, installs the Playwright Chromium browser, prompts to set up `.env` (`GEMINI_API_KEY`, `APIFY_TOKEN`) if missing, then starts both `npm run dev:scraper` (backgrounded) and `npm run dev`. This is the recommended first-run path.
- `.env` (not committed) needs `GEMINI_API_KEY` (optional but recommended — used for DB store Stage 2 audits and background refresh audits; if missing, server starts in cache-only mode and Stage 2 falls back to requiring user-provided keys), `APIFY_TOKEN` (optional — falls back to Playwright only if `ENABLE_PLAYWRIGHT_FALLBACK=true`, see Architecture), and `DISCORD_WEBHOOK_URL` (optional — used by `_send_discord()` for category mismatch reports, abnormal IP alerts, and Apify token/quota alerts; if missing, events are still logged server-side but no notification is sent). See `.env.example`.
- Python offline evaluation scripts live in `eval/` (not a test suite — see below), run with the venv Python from the repo root, e.g. `review_scraper/venv/bin/python eval/evaluate.py restaurant_data`:
  - `eval/evaluate.py` — runs the Stage 1 rule engine over labeled CSVs in `restaurant_data/`, reports precision/recall/F1 against human labels
  - `eval/evaluate_v2.py` — parameter-sweep evaluator; `--window N` limits to newest N reviews (default 100), `--sweep-config file.json` for a custom combo list, `--holdout N` splits N stores into a holdout set (stratified by 有洗/沒洗, deterministic via `--holdout-seed`, or manually via `--holdout-stores`), `--llm-sample N` for the opt-in real-Gemini small-sample mode (costs real API quota — not run automatically)
  - `eval/sample_fp.py` — samples false-positive stores and writes ready-to-paste Gemini prompts into `gemini_prompts/*.txt`
  - `eval/check_data.py` — checks CSV column consistency / `Time` field format across `restaurant_data/`

**Audit mode** (`VITE_AUDIT_MODE` env var): `production` (default) caps Stage 2 at 15 reviews with stratified sampling; `evaluate` removes the cap for full-coverage offline evaluation. Always use `evaluate` mode when running evaluation scripts against the frontend pipeline.

**Testing:**
- `npm test` — runs vitest (`src/app/utils/auditEngine.test.ts`): covers `aggregateAuditedReviews` weighting/Trust Score/Filtered Rating (including unaudited weight path), `mergeStage2Results`, and `computeStage2Confidence` (structural vs. content routing).
- `review_scraper/venv/bin/python -m pytest tests/` — pytest suite covering `/api/audit-rules`, `/api/audit`, `/api/scrape`, `/api/store-summary`, `/api/summarize`, `normalize_review`, `prompt_builder`, `llm_client` batching, `rule_engine` unit tests, `stage2_rules`, and the cross-language signal fixture.
- CI runs both test suites automatically on push/PR to `main` (`.github/workflows/ci.yml`).

## Architecture

### (1) Scraper: Apify primary, Playwright fallback, SQLite cache
`POST /api/scrape` in `review_scraper/server.py`:
1. Checks the SQLite cache first (`review_scraper/cache_store.py`, `cache.db` at repo root, gitignored) — keyed by `place_id`, no TTL (permanent until overwritten). A hit returns immediately with `source: "cache"`. `?force=true` bypasses the lookup (but still refreshes the cache afterward). URLs previously rejected as non-restaurant are cached in `search_query_map` with a `REJECTED:NOT_RESTAURANT` value and short-circuit to 400 immediately, avoiding repeated Apify calls.
2. On a miss, tries `apify_scraper.scrape_via_apify()` (actor `compass/Google-Maps-Reviews-Scraper`, `reviewsSort: "newest"`, `language: "zh-TW"`) — this is the primary path. Returns `source: "apify"`.
3. Only if that raises, and **only if `ENABLE_PLAYWRIGHT_FALLBACK=true`** (default is disabled — an Apify failure returns its error as a 500 by default, Playwright is never silently invoked), falls back to `scraper.py`'s Playwright scraper. Returns `source: "playwright_fallback"`.
4. Both scraper paths normalize their raw output through `normalize.py`'s `normalize_review()` before returning, so the frontend always gets the same shape (`username/stars/time/text/images/hasText/imageCount`) regardless of source.

Known gotcha already hit once: `apify_client`'s `ApifyClient.actor(...).call(...)` returns a `Run` object (a Pydantic model — attribute access: `run.status`, `run.default_dataset_id`), **not a dict**. Using `.get(...)` on it raises `AttributeError` even when the Apify run succeeded (see the regression test in `tests/test_apify_scraper.py` that deliberately uses a `.get()`-less fake to catch this).

### (2) Audit: two-tier key strategy
`POST /api/audit` in `server.py` is the only Stage 2 path. It uses a two-tier key strategy based on whether the store is already in the database:
- **DB stores** (`scrapeSource: "cache"`): uses the server-side `GEMINI_API_KEY` — users see full Stage 2 results without providing any key. Background refresh (`_background_refresh`) probes Google for the current `reviewsCount`, compares with DB metadata, and only fetches when the delta ≥ 20 (`REFRESH_MIN_NEW_REVIEWS`). It fetches exactly the delta, dedup-merges (cap 500), then triggers `_background_audit()` which re-runs Stage 1 + Stage 2 on merged reviews using the server key, so the next user query gets a full cache hit. Cooldown is 7 days (`REFRESH_COOLDOWN_SECONDS`).
- **New stores** (`scrapeSource` is not `"cache"`): requires the user's own API key (Gemini / DeepSeek / OpenAI-compatible via header). Results are saved to `stage2_scores`, so subsequent queries for the same store use the server key path.

`GEMINI_API_KEY` is read from `.env` at startup; if missing, the server still starts (cache-only mode) but Stage 2 for DB stores falls back to requiring user keys. Reviews are batched (`llm_client.make_batches`, ~40/batch, sorted by `daysElapsed`) and sent up to 5 batches concurrently via `ThreadPoolExecutor`. `prompt_builder.py` builds the prompt from `review_scraper/audit_prompt.txt`.

**LLM model**: `gemini-2.5-flash-lite` (also supports DeepSeek and OpenAI-compatible providers via `provider` parameter).

**LLM-only-scores architecture**: The LLM only outputs I/A/D scores (1–5) + a short reasoning per review. `isWashed`, `issueType`, `reason`, and `confidenceScore` are all determined by `stage2_rules.py` on the server. The prompt sends `{id, stars, text}` per review (stars included so LLM can detect star-text contradictions). This means changing thresholds only requires re-running the rule function against cached scores, no API calls needed.

**LLM typo recovery**: `llm_client.py`'s `_validate_score_item()` has an extensive `_TYPO_MAP` that corrects common Gemini misspellings of field names (e.g. `descriptionGranarity` → `descriptionGranularity`, `incentiveIntegration` → `incentiveIntensity`). Also recovers missing `id` fields when all items lack `id` but count matches batch size (positional assignment).

I/A/D scores are cached in `stage2_scores` SQLite table (PK: `review_id, model, prompt_version`), where `review_id = "{place_id}:{username}"` and `prompt_version` is the sha256 prefix of the **scoring criteria section** of `audit_prompt.txt` (everything before `# 輸出格式`). This way, changing output format instructions doesn't invalidate the score cache. Stale scores from older prompts are never mixed with newer ones.

### (3) Stage 2 confidence: content vs. structural, routed by `verdictBasis`
`auditEngine.ts`'s `computeStage2Confidence(item, context)` branches on what actually triggered the verdict:
- **`verdictBasis: "structural"`** (Stage 1 rule 2.6 only — structural template detection now happens entirely in Stage 1, not via LLM) — confidence is a weighted composite of `similarCount`, `hotTermMaxRatio`, `nearbyLongReviewCount`, mapped to **60–95**.
- **`verdictBasis: "content"`** (all Stage 2 LLM results, plus Stage 1 incentive/content verdicts) — `agreement^1.5` formula. For Stage 2, confidence is now computed server-side in `stage2_rules.py` and returned in the API response; the frontend no longer calls `computeStage2Confidence` for Stage 2 items. The function is still used for Stage 1 structural routing in tests.

### (4) Stage 1 `issueType` categories, including `low_info` and `unaudited`
`audit_review(review, context)` in `review_scraper/rule_engine.py` returns one of: `'incentive'` (explicit keyword match, including contextual "送" check), `'template'` (exact-duplicate 2-gram/75%, or an escalated short review), `'no_text'` (star-only reviews), `'low_info'`, or `null` (genuinely ambiguous — the only case sent to Stage 2).

After Stage 2 merge, `mergeStage2Results()` in `auditEngine.ts` marks any `issueType: null` review that Stage 2 didn't cover as `'unaudited'`. Unaudited reviews get a fixed weight of 0.65 in `aggregateAuditedReviews()`, decoupled from the confidence system (not derived from `confidenceScore`).

`low_info`: a short/generic review (e.g. "好吃") defaults to `isWashed: false`, confidence 55 (weight 0.55) — short text alone is not washing evidence. It only escalates to a washed `'template'` verdict when *also* co-occurring with a review-volume spike period (`isSpikePeriod`) or a high cross-review `similarCount` (≥2) — i.e. only when there's a second, independent signal pointing at deliberate templating. `context: { isSpikePeriod?, similarCount? }` is threaded in by `run_stage1_audit`, which has the whole-store review list needed to derive them; `audit_review` can't determine either from a single review.

Reviews with any non-null `issueType` are Stage-1-final and excluded from the Stage 2 pool (`Results.tsx` filters on `r.audit.issueType === null`) — this was a real bug fixed earlier: Stage 1-confident reviews (including `low_info`) were being re-sent to Gemini and could get silently overwritten by a worse LLM guess (see `mergeStage2Results` and its regression tests).

### (5) Rule engine: single Python implementation
The Stage 1 rule engine lives in one place: `review_scraper/rule_engine.py`. Both the live backend endpoint (`POST /api/audit-rules`) and the offline evaluation script (`eval/evaluate_v2.py`) import from it directly — no mirroring, no cross-language sync needed.

- `rule_engine.py` contains: `RuleConfig` dataclass (all thresholds), `audit_review()` (per-review heuristic), `run_stage1_audit()` (store-level orchestrator returning `auditedReviews` + `signals`), and all signal detection functions (`detect_templates`, `detect_similarity_signals`, `detect_hot_term_signals`, `detect_nearby_long_review_counts`, `detect_spike_months`, `detect_low_info_and_escalated`).
- `evaluate_v2.py` imports `RuleConfig` and `run_stage1_audit` from `rule_engine`, calling the same orchestrator that powers `POST /api/audit-rules`. CSV PascalCase rows are converted to lowercase keys via `_normalize_csv_row()`. Evaluation-specific code (`confusion_matrix`, `run_param_sweep`, `sample_for_llm`, `run_llm_sample_mode`, `DEFAULT_SWEEP`) stays in evaluate_v2.
- `auditEngine.ts` retains only types/interfaces (`AuditResult`, `ShopStats`, `SimilaritySignal`, `HotTermSignal`, `Stage2Item`, `Stage2SignalContext`) and Stage 2 functions (`computeStage2Confidence`, `mergeStage2Results`, `aggregateAuditedReviews`). All Stage 1 rule logic has been migrated to `review_scraper/rule_engine.py`.
- Cross-language golden fixture: `tests/test_evaluate_v2_signal_mirrors.py` and `auditEngine.test.ts` still assert the same hardcoded expected values for `detect_hot_term_signals` / `computeNearbyLongReviewCounts`, but now the Python side is the single source and the TS side only validates the values that the frontend receives from the backend.

### (6) Store summary & QA
- `POST /api/store-summary` — generates warnings + recommendations from non-washed reviews using `call_llm_summary()`. Caches results in `summary_cache` table. Filters out washed and empty reviews, caps at 150 sorted by text length. The summary prompt also detects `promotionGap` — a discrepancy between influencer/social media hype and actual dining experience reported in reviews. When detected, the summary JSON includes a `promotionGap` string field shown in the Results UI with a Megaphone icon.
- `POST /api/summarize` — QA endpoint: answers user questions about a store's reviews using `call_llm_qa()`. Anonymizes usernames before sending to LLM, restores them in response. Cached in `qa_cache` table. Rate-limited per IP per store (`qa_rate_limit` table).

### (7) Food category gate & user report
`POST /api/scrape` rejects non-restaurant venues before performing a full scrape. Detection uses a two-tier approach:
1. **Category keywords** (`_is_food_category`): ~60+ keywords covering Chinese/English food venue types (餐廳, 咖啡廳, 快餐店, bakery, bar, etc.).
2. **Store name fallback** (`_name_looks_like_food`): catches misclassified venues (e.g. a café listed as "時裝店" on Google Maps) by checking the store name for food-related keywords (咖啡, cafe, 麵, 串燒, pizza, kitchen, etc.).

If both checks fail, the endpoint returns `400` with `code: "NOT_RESTAURANT"` and includes `categoryName`, `storeName`, `placeId` in the response. The frontend (`Analyzer.tsx`) shows a report button — clicking it POSTs to `POST /api/report-category` (rate-limited 5/hr), which saves to the `category_reports` SQLite table and sends a Discord webhook notification (via `DISCORD_WEBHOOK_URL` env var / Fly.io secret).

### Frontend (`src/`)
A 5-page React app (not a component-library-driven one, despite ~20 `@radix-ui/*`/`@mui/*` packages listed in `package.json` — they're unused scaffolding from the original Figma Make template and can be ignored).

- `src/app/routes.ts` — react-router v7 `createBrowserRouter`: `/` (`Home.tsx`), `/analyzer` (`Analyzer.tsx`), `/results` (`Results.tsx`), `/history` (`History.tsx`), `/settings` (`Settings.tsx`). Data is passed between pages via `navigate(path, { state })`, not URL params.
- `src/app/pages/Analyzer.tsx` — input form: preset restaurants (bundled demo dataset) or paste Google Maps URLs (POSTed to `/api/scrape`). Passes `scrapeSource` (from `/api/scrape` response `source` field) through to Results for the two-tier key strategy. Handles `NOT_RESTAURANT` error with an in-line report button (see (7) above).
- `src/app/pages/Results.tsx` — Stage 1: calls `POST /api/audit-rules` to get audited reviews and precomputed signals from the backend, then `aggregateAuditedReviews()` to produce `ShopStats`. Stage 2: uses the backend signals (`similarity`, `hotTerm`, `nearbyLongReviewCounts`, `spikeMonths`) to build the Gemini payload for ambiguous reviews, merges via `mergeStage2Results`, re-aggregates via `aggregateAuditedReviews`. UI: `low_info` reviews get a neutral gray badge; `unaudited` reviews get a gray "未複審" badge without confidence display; a washed verdict below 50% confidence shows "疑似洗評" in muted amber. `StoreVerdict` shows a 5-category composition bar: 促銷型, 模板型, 語意矛盾, 低內容 (merged noText+lowInfo), 自然評論 (unaudited is hidden from the bar). `reviewAvgRating` displays the recent average star rating vs. Google official rating when the difference is notable. `promotionGap` (from store summary) is shown with a Megaphone icon when detected.
- `src/app/pages/History.tsx` — browsing history of previously analyzed stores.
- `src/app/pages/Settings.tsx` — user settings (API keys, preferences).
- `src/app/utils/auditEngine.ts` — types/interfaces (`AuditResult`, `ShopStats`, `SimilaritySignal`, `HotTermSignal`) and Stage 2 functions only (`computeStage2Confidence`, `mergeStage2Results`, `aggregateAuditedReviews`). `AuditResult.issueType` includes `'unaudited'` for reviews not covered by Stage 2. `ShopStats.issues` tracks per-category counts: `{ incentive, template, noText, lowInfo, unaudited }`. `ShopStats.reviewAvgRating` stores the average star rating of recent reviews for comparison with the Google official rating.
- `src/app/components/TutorialModal.tsx` — branching onboarding tutorial: "near NTU" path (no keys needed for full report, AI QA is optional) vs. "other area" path (needs Apify Token + AI API Key for first-time audit; stores are saved to DB so subsequent visits need no keys).
- `src/app/components/results/ReviewInspector.tsx` — expandable review list with search and filter tabs (all, washed, Stage 1, Stage 2, clean, unaudited).
- `src/app/utils/csvParser.ts` + `src/app/data/restaurantsData.ts` — hand-rolled CSV parser that loads 18 CSVs from `restaurant_data/` via Vite's `?raw` import (enabled by `assetsInclude` in `vite.config.ts`) to build the built-in demo dataset.
- `vite.config.ts` — `@` alias → `src/`; a `figmaAssetResolver()` plugin (template leftover); dev-server proxy `/api` → `http://127.0.0.1:5001`.
- Styling is Tailwind v4 via `@tailwindcss/vite` — `postcss.config.mjs` is intentionally empty (v4 doesn't need manual PostCSS config).

### Backend (`review_scraper/`)
- `server.py` — Flask app (port 5001), `GET /`, `POST /api/scrape`, `POST /api/audit-rules`, `POST /api/audit`, `POST /api/store-summary`, `POST /api/summarize`, `POST /api/report-category`, `GET /api/stats`. See (1), (2), (5), (6), and (7) above. `_send_discord()` helper centralizes Discord webhook delivery (category mismatch, abnormal IP, Apify token/quota alerts). Per-IP Apify scrape rate limiting (3 new-store scrapes/hour, in-memory tracker) prevents abuse. Each scrape request is logged to `query_log` via `log_query()`; IPs exceeding 10 queries/hour trigger a Discord alert.
- `rule_engine.py` — the canonical Stage 1 rule engine. See (4) and (5) above.
- `apify_scraper.py` — primary scraper, calls the Apify actor.
- `scraper.py` — Playwright + BeautifulSoup4 + `playwright-stealth` fallback. Hardcoded Google Maps CSS selectors (`div.jftiEf`, `span.kvMYJc`, `span.rsqaWe`, `span.wiI7pd`), fragile to DOM changes. `parse_relative_time()` converts relative dates to absolute.
- `cache_store.py` — SQLite cache layer (`cache.db`, gitignored). Ten tables: `scrape_cache` (scraped reviews by place_id), `search_query_map` (URL/query → place_id; also stores `REJECTED:NOT_RESTAURANT` values for rejected non-restaurant URLs to avoid re-scraping), `audit_cache` (Stage 1 results by place_id, no TTL), `stage2_scores` (I/A/D scores by review_id+model+prompt_version), `summary_cache` (store summary), `qa_cache` (QA answers), `qa_rate_limit` (per-IP rate limiting), `visitor_log` (analytics), `category_reports` (user-submitted category mismatch reports), `query_log` (per-request logging: ip, place_id, store_name, source, created_at; indexed on `(ip, created_at)` for anomaly detection). When `set_cached_reviews` updates a store's reviews, it invalidates `audit_cache` and `qa_cache` for that store but **preserves `summary_cache`** (expensive LLM output); summaries are regenerated by `_background_summary()` after background audit completes.
- `batch_crawl.py` — local Playwright batch pre-crawl script (Issue #15). Supports `--resume`, `--split N`, `--merge-cache`, checkpoint-based progress.
- `batch_audit.py` — batch Stage 1 audit script (Issue #16). Reads all entries from `scrape_cache`, runs `run_stage1_audit()`, writes results to `audit_cache`. Supports `--dry-run` and `--force`.
- `normalize.py` — `normalize_review()`, unifies Playwright's PascalCase fields and the Apify actor's lowercase `text`/`textTranslated` fields into one shape.
- `prompt_builder.py` — builds the Stage 2 prompt from `audit_prompt.txt`. Each review is sent as `{id, stars, text}`. Exposes `get_prompt_version()` — hashes only the scoring criteria section (before `# 輸出格式`) for cache keying.
- `llm_client.py` — batching (time-sorted) + Gemini/DeepSeek/OpenAI-compatible response JSON parsing/repair + per-item validation (5 required fields: `id`, `reasoning`, `incentiveIntensity`, `sentimentAuthenticity`, `descriptionGranularity`; id range, score range 1–5) + typo map for common LLM field name misspellings + missing-id positional recovery.
- `stage2_rules.py` — post-LLM rule engine: `judge_from_scores(I, A, D, is_spike)` determines `(isWashed, issueType)`, `compute_content_confidence()` calculates confidence, `build_stage2_result()` composes the full result object.
- `audit_prompt.txt` — the Stage 2 prompt template. LLM outputs only `{id, reasoning, I, A, D}` — no verdict, no issueType, no verdictBasis. Security directive wraps review data in randomized XML tags (Issue #22).

### Scripts (`scripts/`)
- `prerun_stage2.py` — batch Stage 2 prerun for all stores in scrape_cache. Runs Stage 1, identifies ambiguous reviews, sends uncached ones to Gemini, saves I/A/D scores. Supports `--dry-run`, `--force`, `--limit`, `--test`, `--batch-size`, `--delay`. Fail-fast on 3 consecutive store failures (to avoid burning API quota on outages). Summary distinguishes "完成" vs "中斷" on early termination.
- `prerun_summary.py` — batch store summary prerun.
- `validate_stage2_iad.py` — validation script for Stage 2 I/A/D scores.
- `validate_structural_rule.py` — validation script for structural template rules.

### Data (`restaurant_data/`, `gemini_prompts/`)
- `restaurant_data/` holds hand-labeled CSVs organized as `<類別>__<有洗|沒洗>/` (category, e.g. 餐廳/飲料店/觀光店/連鎖店, crossed with washed/clean). These back both the frontend demo dataset and the offline `eval/*.py` scripts.
- `gemini_prompts/*.txt` — pre-generated prompts (output of `eval/sample_fp.py`) for manual copy-paste into the Gemini web UI, not called programmatically.

### Docs (`docs/`)
- `docs/TRUE_RATING_LOGIC.md` — the authoritative reference for Stage 1 rules, Stage 2 confidence formula, Trust Score / Filtered Rating aggregation math.
- `docs/HANDOFF.md` — changelog from the semester version to current.
- `docs/TrueRating_發布前大方向.md` — pre-launch roadmap and architectural decisions.

### Evaluation (`eval/`)
Offline evaluation scripts (not part of the test suite). Run from the repo root with the venv Python, e.g. `review_scraper/venv/bin/python eval/evaluate.py restaurant_data`. Generated output files (`results.json`, `report.md`, `tune_results.json`, `llm_input.json`) are gitignored.

### Tests
- `src/app/utils/auditEngine.test.ts` (Vitest) — `aggregateAuditedReviews` weighting/Trust Score/Filtered Rating (including unaudited fixed-weight path), `mergeStage2Results` (Stage 1 verdict preservation, unaudited marking), `computeStage2Confidence` (structural vs. content routing regression).
- `tests/` (pytest, run with the `review_scraper/venv` Python):
  - `test_rule_engine.py` — `audit_review` unit tests (keyword, "送" context, no_text, low_info, escalation), `run_stage1_audit` integration tests (duplicates, signals structure), `/api/audit-rules` endpoint tests (happy path, validation, incentive/duplicate detection).
  - `test_evaluate_v2_signal_mirrors.py` — cross-language golden fixture for `detect_hot_term_signals` / `detect_nearby_long_review_counts` (now imports directly from `rule_engine`).
  - `test_normalize.py`, `test_audit_api.py`, `test_apify_scraper.py` (incl. the `Run`-object regression test, food category gate, name fallback, category report endpoint), `test_gemini_client.py`, `test_prompt_builder.py`.
  - `test_stage2_rules.py` — `judge_from_scores`, `compute_content_confidence`, `build_stage2_result` unit tests.
  - `test_summarize_api.py` — `/api/store-summary` endpoint tests (golden case, cache hit, validation, LLM failure, washed review filtering).
  - `test_qa_api.py` — `/api/summarize` endpoint tests (success, validation, rate limiting, cache hit).
  - `tests/conftest.py` puts both `review_scraper/` and the repo root on `sys.path` and stubs `GEMINI_API_KEY` so importing `server` doesn't require a real key.

### Known limitations
- Apify is a paid third-party service — `APIFY_TOKEN` quota/cost applies to the primary scrape path. Playwright fallback needs a local browser and is opt-in only (`ENABLE_PLAYWRIGHT_FALLBACK=true`); with it off (the default), an Apify outage means scraping just fails rather than silently falling back.
- Each analysis samples roughly the most recent 100 reviews per store.
- Keyword rules and prompts are tuned for Traditional Chinese restaurant reviews.
- Scraper CSS selectors (Playwright fallback path) depend on Google Maps' current DOM structure and can break on redesigns — Apify's actor absorbs this risk on the primary path instead.
- `nearbyLongReviewCount` needs minute-level timestamp precision to be meaningful; the Playwright fallback's day-level dates make same-day reviews trivially "nearby" (documented in `rule_engine.py`).

## Known TODOs / known issues
- **`run_llm_sample_mode()` in `eval/evaluate_v2.py` has not been executed against the real Gemini API** in any session so far — only its error path (missing `GEMINI_API_KEY`) and import chain have been verified. Running it for real costs API quota.
- **`README.md`** still describes the pre-Apify/pre-backend-audit architecture in places (quick-start, tech stack table) — should be re-checked against (2)/(3)/(4) above.
- **No dish-name dictionary** — `computeHotTermSignals`' "hot term" detection is a pure n-gram frequency heuristic, not real NLP/NER.
- **`nearbyLongReviewCount` fidelity gap** — see Known limitations above.
- **`similarCount >= 1` threshold in the structural-template rule** (`audit_prompt.txt` rule 4a) is intentionally permissive — not yet validated against a large enough labeled dataset.
- **Unaudited weight is provisional** — the 0.65 fixed weight for unaudited reviews (`aggregateAuditedReviews`) is a placeholder pending parameter sweep with review-level ground truth (#67).
