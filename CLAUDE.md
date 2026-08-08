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
- `npm run dev:scraper` — start the Flask backend (`review_scraper/server.py`, port 5001), which serves `/api/scrape`, `/api/audit-rules`, and `/api/audit`. Must be running for Stage 1 heuristic audit, scraping, and Stage 2 Gemini audit to work (the frontend calls the backend for all three).
- `npm run dev` — start the Vite dev server. Vite proxies `/api/*` to `http://127.0.0.1:5001`, so `npm run dev:scraper` needs to be running alongside it (two terminals, or via `./run.sh`).
- `npm run build` — production build (`vite build`)
- `./run.sh` — interactive one-shot setup + run script (macOS-oriented): detects a compatible Python (3.9–3.13), creates `review_scraper/venv`, installs `review_scraper/requirements.txt`, installs the Playwright Chromium browser, prompts to set up `.env` (`GEMINI_API_KEY`, `APIFY_TOKEN`) if missing, then starts both `npm run dev:scraper` (backgrounded) and `npm run dev`. This is the recommended first-run path. (No longer mentions Ollama — that path was removed entirely.)
- `.env` (not committed) needs `GEMINI_API_KEY` (required — server.py refuses to start without it) and `APIFY_TOKEN` (optional — falls back to Playwright only if `ENABLE_PLAYWRIGHT_FALLBACK=true`, see Architecture). See `.env.example`.
- Python offline evaluation scripts live in `eval/` (not a test suite — see below), run with the venv Python from the repo root, e.g. `review_scraper/venv/bin/python eval/evaluate.py restaurant_data`:
  - `eval/evaluate.py` — runs the Stage 1 rule engine over labeled CSVs in `restaurant_data/`, reports precision/recall/F1 against human labels
  - `eval/evaluate_v2.py` — parameter-sweep evaluator; `--window N` limits to newest N reviews (default 100), `--sweep-config file.json` for a custom combo list, `--holdout N` splits N stores into a holdout set (stratified by 有洗/沒洗, deterministic via `--holdout-seed`, or manually via `--holdout-stores`), `--llm-sample N` for the opt-in real-Gemini small-sample mode (costs real API quota — not run automatically)
  - `eval/sample_fp.py` — samples false-positive stores and writes ready-to-paste Gemini prompts into `gemini_prompts/*.txt`
  - `eval/check_data.py` — checks CSV column consistency / `Time` field format across `restaurant_data/`

**Audit mode** (`VITE_AUDIT_MODE` env var): `production` (default) caps Stage 2 at 15 reviews with stratified sampling; `evaluate` removes the cap for full-coverage offline evaluation. Always use `evaluate` mode when running evaluation scripts against the frontend pipeline.

**Testing:**
- `npm test` — runs vitest (`src/app/utils/auditEngine.test.ts`): covers `aggregateAuditedReviews` weighting/Trust Score/Filtered Rating, `mergeStage2Results`, and `computeStage2Confidence` (structural vs. content routing).
- `review_scraper/venv/bin/python -m pytest tests/` — pytest suite covering `/api/audit-rules` (Stage 1 rule engine endpoint), `/api/audit`, `/api/scrape` (Apify/Playwright/cache), `normalize_review`, `prompt_builder`, `gemini_client` batching, `rule_engine` unit tests (`audit_review`, `run_stage1_audit`, signal detection), and the cross-language signal fixture.
- There is **no lint script and no `tsconfig.json`** in this repo, but there **is** a test suite (Vitest + pytest, see above) — don't assume untested just because there's no CI config visible.

## Architecture

### (1) Scraper: Apify primary, Playwright fallback, SQLite cache
`POST /api/scrape` in `review_scraper/server.py`:
1. Checks the SQLite cache first (`review_scraper/cache_store.py`, `cache.db` at repo root, gitignored) — keyed by URL, 7-day TTL (`CACHE_TTL_SECONDS`). A hit returns immediately with `source: "cache"`. `?force=true` bypasses the lookup (but still refreshes the cache afterward).
2. On a miss, tries `apify_scraper.scrape_via_apify()` (actor `compass/Google-Maps-Reviews-Scraper`, `reviewsSort: "newest"`, `language: "zh-TW"`) — this is the primary path. Returns `source: "apify"`.
3. Only if that raises, and **only if `ENABLE_PLAYWRIGHT_FALLBACK=true`** (default is disabled — an Apify failure returns its error as a 500 by default, Playwright is never silently invoked), falls back to `scraper.py`'s Playwright scraper. Returns `source: "playwright_fallback"`.
4. Both scraper paths normalize their raw output through `normalize.py`'s `normalize_review()` before returning, so the frontend always gets the same shape (`username/stars/time/text/images/hasText/imageCount`) regardless of source.

Known gotcha already hit once: `apify_client`'s `ApifyClient.actor(...).call(...)` returns a `Run` object (a Pydantic model — attribute access: `run.status`, `run.default_dataset_id`), **not a dict**. Using `.get(...)` on it raises `AttributeError` even when the Apify run succeeded (see the regression test in `tests/test_apify_scraper.py` that deliberately uses a `.get()`-less fake to catch this).

### (2) Audit: Gemini only, key server-side
`POST /api/audit` in `server.py` is the only Stage 2 path — there is no local/Ollama option anymore (removed entirely) and Gemini is never called from the browser (moved server-side so the API key never reaches the client). `GEMINI_API_KEY` is read from `.env` at startup; missing it raises `RuntimeError` immediately (fail fast, not a silent no-op). Reviews are batched (`gemini_client.make_batches`, ~40/batch, sorted by `daysElapsed` first so temporally-close reviews land in the same prompt) and sent up to 5 batches concurrently via `ThreadPoolExecutor`. `prompt_builder.py` builds the prompt from `review_scraper/audit_prompt.txt`.

### (3) Stage 2 confidence: content vs. structural, routed by `verdictBasis`
`auditEngine.ts`'s `computeStage2Confidence(item, context)` branches on what actually triggered the verdict:
- **`verdictBasis: "structural"`** (only meaningful when `isWashed: true` and `issueType: "template"`) — the verdict came from cross-review evidence (`similarCount`, `hotTermMaxRatio`, `nearbyLongReviewCount`), not from this review's own content. Confidence is a weighted composite of those three signals, mapped to **60–95**. This exists because scoring these via the I/A/D dimensions produced ~2% confidence for well-written ghost-written reviews (the content "disagrees" with its own washed verdict) — i.e. detected but with a weight of ~0.98, no real filtering effect.
- **`verdictBasis: "content"`** (everything else: incentive keyword matches, content-driven empty templates, genuine clean verdicts) — unchanged `agreement^1.5` formula over `incentiveIntensity`/`sentimentAuthenticity`/`descriptionGranularity`.

Gemini itself decides and outputs `verdictBasis` (documented in `audit_prompt.txt`'s output schema with an explicit self-check: "if I mask this review's text and only look at its cross-review structural relationships, can I still reach the same verdict?" → structural if yes).

The rule-4 prompt clause that produces structural `template` verdicts (same-store review homogeneity — matching opening structure, signature-dish combo, closing line) is **explicitly time-independent**: it must not require `isSpikePeriod` or close `daysElapsed` as a gating condition, since scheduled ghostwriting deliberately staggers posting times to dodge time-clustering checks. `isSpikePeriod`/`nearbyLongReviewCount` are aggravating (confidence-boosting) signals only, never triggers. See `audit_prompt.txt`'s 範例 F for the canonical "structurally identical, posted 20 days apart" example, and `auditEngine.test.ts`'s `computeStage2Confidence` describe block for the regression test (asserts the old content-formula-only behavior would have scored ~2%, the fix scores ≥60%).

### (4) Stage 1 `issueType` categories, including `low_info`
`audit_review(review, context)` in `review_scraper/rule_engine.py` returns one of: `'incentive'` (explicit keyword match, including contextual "送" check), `'template'` (exact-duplicate 2-gram/75%, or an escalated short review, or Gemini's structural verdict), `'discrepancy'` (Gemini-only, semantic mismatch), `'no_text'` (star-only reviews), `'low_info'`, or `null` (genuinely ambiguous — the only case sent to Stage 2).

`low_info`: a short/generic review (e.g. "好吃") defaults to `isWashed: false`, confidence 55 (weight 0.55) — short text alone is not washing evidence. It only escalates to a washed `'template'` verdict when *also* co-occurring with a review-volume spike period (`isSpikePeriod`) or a high cross-review `similarCount` (≥2) — i.e. only when there's a second, independent signal pointing at deliberate templating. `context: { isSpikePeriod?, similarCount? }` is threaded in by `run_stage1_audit`, which has the whole-store review list needed to derive them; `audit_review` can't determine either from a single review.

Reviews with any non-null `issueType` are Stage-1-final and excluded from the Stage 2 pool (`Results.tsx` filters on `r.audit.issueType === null`) — this was a real bug fixed earlier: Stage 1-confident reviews (including `low_info`) were being re-sent to Gemini and could get silently overwritten by a worse LLM guess (see `mergeStage2Results` and its regression tests).

### (5) Rule engine: single Python implementation
The Stage 1 rule engine lives in one place: `review_scraper/rule_engine.py`. Both the live backend endpoint (`POST /api/audit-rules`) and the offline evaluation script (`eval/evaluate_v2.py`) import from it directly — no mirroring, no cross-language sync needed.

- `rule_engine.py` contains: `RuleConfig` dataclass (all thresholds), `audit_review()` (per-review heuristic), `run_stage1_audit()` (store-level orchestrator returning `auditedReviews` + `signals`), and all signal detection functions (`detect_templates`, `detect_similarity_signals`, `detect_hot_term_signals`, `detect_nearby_long_review_counts`, `detect_spike_months`, `detect_low_info_and_escalated`).
- `evaluate_v2.py` imports `RuleConfig` and `run_stage1_audit` from `rule_engine`, calling the same orchestrator that powers `POST /api/audit-rules`. CSV PascalCase rows are converted to lowercase keys via `_normalize_csv_row()`. Evaluation-specific code (`confusion_matrix`, `run_param_sweep`, `sample_for_llm`, `run_llm_sample_mode`, `DEFAULT_SWEEP`) stays in evaluate_v2.
- `auditEngine.ts` retains only types/interfaces (`AuditResult`, `ShopStats`, `SimilaritySignal`, `HotTermSignal`, `Stage2Item`, `Stage2SignalContext`) and Stage 2 functions (`computeStage2Confidence`, `mergeStage2Results`, `aggregateAuditedReviews`).
- Cross-language golden fixture: `tests/test_evaluate_v2_signal_mirrors.py` and `auditEngine.test.ts` still assert the same hardcoded expected values for `detect_hot_term_signals` / `computeNearbyLongReviewCounts`, but now the Python side is the single source and the TS side only validates the values that the frontend receives from the backend.

### Frontend (`src/`)
A flat 3-page React app (not a component-library-driven one, despite ~20 `@radix-ui/*`/`@mui/*` packages listed in `package.json` — they're unused scaffolding from the original Figma Make template and can be ignored).

- `src/app/routes.ts` — react-router v7 `createBrowserRouter`: `/` (`Home.tsx`), `/analyzer` (`Analyzer.tsx`), `/results` (`Results.tsx`). Data is passed between pages via `navigate(path, { state })`, not URL params.
- `src/app/pages/Analyzer.tsx` — input form: preset restaurants (bundled demo dataset) or paste Google Maps URLs (POSTed to `/api/scrape`). No API key input anywhere — the Gemini key lives server-side in `.env`.
- `src/app/pages/Results.tsx` — Stage 1: calls `POST /api/audit-rules` to get audited reviews and precomputed signals from the backend, then `aggregateAuditedReviews()` to produce `ShopStats`. Stage 2: uses the backend signals (`similarity`, `hotTerm`, `nearbyLongReviewCounts`, `spikeMonths`) to build the Gemini payload for ambiguous reviews, routes each response through `computeStage2Confidence`, merges via `mergeStage2Results`, re-aggregates via `aggregateAuditedReviews`. UI: `low_info` reviews get a neutral gray badge (not the red "washed" style); a washed verdict below 50% confidence shows "疑似洗評" in muted amber instead of "判定：灌水洗評", and suppresses the "二階 AI 攔截" certainty chip.
- `src/app/utils/auditEngine.ts` — types/interfaces (`AuditResult`, `ShopStats`, `SimilaritySignal`, `HotTermSignal`) and Stage 2 functions only (`computeStage2Confidence`, `mergeStage2Results`, `aggregateAuditedReviews`). All Stage 1 rule logic has been migrated to `review_scraper/rule_engine.py`.
- `src/app/utils/csvParser.ts` + `src/app/data/restaurantsData.ts` — hand-rolled CSV parser that loads 18 CSVs from `restaurant_data/` via Vite's `?raw` import (enabled by `assetsInclude` in `vite.config.ts`) to build the built-in demo dataset.
- `vite.config.ts` — `@` alias → `src/`; a `figmaAssetResolver()` plugin (template leftover); dev-server proxy `/api` → `http://127.0.0.1:5001`.
- Styling is Tailwind v4 via `@tailwindcss/vite` — `postcss.config.mjs` is intentionally empty (v4 doesn't need manual PostCSS config).

### Backend (`review_scraper/`)
- `server.py` — Flask app (port 5001), `GET /`, `POST /api/scrape`, `POST /api/audit-rules`, `POST /api/audit`. See (1), (2), and (5) above.
- `rule_engine.py` — the canonical Stage 1 rule engine. See (4) and (5) above.
- `apify_scraper.py` — primary scraper, calls the Apify actor.
- `scraper.py` — Playwright + BeautifulSoup4 + `playwright-stealth` fallback. Hardcoded Google Maps CSS selectors (`div.jftiEf`, `span.kvMYJc`, `span.rsqaWe`, `span.wiI7pd`), fragile to DOM changes. `parse_relative_time()` converts relative dates to absolute.
- `cache_store.py` — SQLite scrape cache, see (1).
- `normalize.py` — `normalize_review()`, unifies Playwright's PascalCase fields and the (future/current) Apify actor's lowercase `text`/`textTranslated` fields into one shape.
- `prompt_builder.py` — builds the Stage 2 prompt from `audit_prompt.txt` + the review/signal payload.
- `gemini_client.py` — batching (time-sorted) + Gemini response JSON parsing/repair.
- `audit_prompt.txt` — the Stage 2 prompt template. See (2)/(3) above for the `verdictBasis` output field and the time-independent structural-template rule.

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
- `src/app/utils/auditEngine.test.ts` (Vitest) — `aggregateAuditedReviews` weighting/Trust Score/Filtered Rating, `mergeStage2Results` (Stage 1 verdict preservation), `computeStage2Confidence` (structural vs. content routing regression).
- `tests/` (pytest, run with the `review_scraper/venv` Python):
  - `test_rule_engine.py` — `audit_review` unit tests (keyword, "送" context, no_text, low_info, escalation), `run_stage1_audit` integration tests (duplicates, signals structure), `/api/audit-rules` endpoint tests (happy path, validation, incentive/duplicate detection).
  - `test_evaluate_v2_signal_mirrors.py` — cross-language golden fixture for `detect_hot_term_signals` / `detect_nearby_long_review_counts` (now imports directly from `rule_engine`).
  - `test_normalize.py`, `test_audit_api.py`, `test_apify_scraper.py` (incl. the `Run`-object regression test), `test_gemini_client.py`, `test_prompt_builder.py`.
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
- **No CI configuration** — `npm run test` / `pytest tests/` exist and pass locally but nothing runs them automatically on push/PR.
