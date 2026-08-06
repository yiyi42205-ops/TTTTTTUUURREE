# [Phase 1] Issue #1: Semantic Offloading & Length-Weighted Sampling

## 1. Executive Summary

This task resolves the inconsistent `low_info` classification within the Stage 1 Heuristic Engine (`src/app/utils/auditEngine.ts`). 

Attempting to evaluate semantic granularity (e.g., distinguishing "好吃" from "蛤蜊好吃") using heuristics in Stage 1 was identified as an **architectural anti-pattern**. It leaked NLP responsibilities into the deterministic rule engine, creating endless dictionary maintenance debt (`user_dict` slang explosion).

**The Final Decision**: 
We strictly purified Stage 1 to handle ONLY 100% deterministic physical signals (Explicit Bribes, Empty Strings, Template Duplicates). We completely abolished the `low_info` heuristic from Stage 1. Instead, we protect the Stage 2 (Gemini) API budget by implementing a **Length-Weighted Stratified Sampling Router** in the frontend before calling the LLM, offloading all semantic granularity judgment to Gemini's native `descriptionGranularity` dimension.

---

## 2. Technical Architecture & Implemented Solution

### A. Stage 1 Purification (Removed `low_info` Heuristic)
- **File**: `src/app/utils/auditEngine.ts`
- **Action**: Deleted `EMPTY_WORDS` and the entire `low_info` logic block.
- **Result**: Stage 1 now only flags `no_text`, explicit incentive keywords, and Jaccard similarity `template` matches. All other reviews (including 2-char short reviews) bypass Stage 1 and enter the "Pending Stage 2" pool.

### B. Length-Weighted Stratified Sampling Router
- **File**: `src/app/pages/Results.tsx`
- **Action**: Modified the logic that selects the maximum 15 reviews for Stage 2 Gemini auditing (`VITE_AUDIT_MODE="production"`).
- **New Sampling Algorithm**:
  Grouped the "Pending Stage 2" reviews into Length Buckets:
  1. **Long (High Value)**: $> 30$ chars. 
  2. **Medium**: $10 - 30$ chars. 
  3. **Short (Noise Prone)**: $< 10$ chars. Hard capped at 2 slots out of 15.
- Remaining slots are distributed proportionally between Long and Medium reviews.

### C. Unsampled Fallback & Gemini Semantic Evaluation
- **Action**: Short reviews ( $< 10$ chars ) that are not sampled for LLM evaluation are naturally given a fallback audit verdict of `low_info` with a confidence score of 55, retaining the original weight logic.
- **Result**: Gemini natively evaluates the sampled short reviews, scoring "好吃" with `descriptionGranularity = 1` and "蛤蜊好吃" with `descriptionGranularity = 2`. The math pipeline naturally suppresses the weight of low-granularity reviews without requiring manual noun dictionaries.

---

## 3. Scope & Affected Files

- **Core Heuristics**: `src/app/utils/auditEngine.ts` (Removed `low_info` heuristic and `EMPTY_WORDS`)
- **Unit Suite**: `src/app/utils/auditEngine.test.ts` (Removed tests asserting `low_info` escalations)
- **Sampling Logic**: `src/app/pages/Results.tsx` (Implemented Length-Weighted sampling)
- **Offline Evaluation**: `evaluate.py` (Confirmed Stage 1 metrics)

---

## 4. Definition of Done (DoD) & Acceptance Criteria

- [x] **Functional Determinism**: Stage 1 no longer uses fragile string sets.
- [x] **Unit Test Suite**: `auditEngine.test.ts` updated and passing.
- [x] **Regression Benchmark**: F1 scores in `evaluate.py` verified as unchanged (0.364).
- [x] **LLM Efficiency**: Short reviews (<10 chars) are capped at 2 LLM slots, preserving quota for complex long reviews.

---

## 5. Future Enhancement: Context-Aware Review Verdict Caching (Pre-Analysis)

To further reduce API costs and network latency for high-traffic environments, we propose implementing a **Pre-Analysis Verdict Cache** in the Python backend.

### A. Core Architecture
- **Storage**: SQLite-backed `review_audit_cache` table in `cache.db`.
- **Compound Cache Key**: Since LLM evaluations are context-dependent (e.g., a review is more suspicious if posted during a temporal spike or matches a high-frequency template cluster), the cache key must be a SHA-256 hash of the review text combined with its contextual signals:
  `CacheKey = SHA256(text + stars + storeName + isSpikePeriod + similarCount + hotTermCount)`
- **Workflow**:
  1. Before making the batch API call to Gemini, compute the compound hash for each of the 15 sampled reviews.
  2. Query `review_audit_cache` for existing keys.
  3. Bypass the LLM call for cache hits; send only cache misses to Gemini.
  4. Write new Gemini results back to the cache.

