# Daily Link Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make daily-report links correct, curated, enriched with cached page metadata, and observable without adding LLM token usage.

**Architecture:** Keep URL extraction in `summary.py`, URL normalization/selection/rendering in `daily_report.py`, and network metadata fetching in a small standard-library helper. The report only enriches already-selected links and always falls back to local context. LLM usage is recorded at the existing API boundary without changing the target-image gate.

**Tech Stack:** Python standard library, SQLite, pytest, existing OneBot text messages.

---

### Task 1: Lock URL extraction and normalization behavior

**Files:**
- Modify: `qq_onebot_whitelist/summary.py`
- Modify: `qq_onebot_whitelist/daily_report.py`
- Test: `tests/test_store_summary.py`
- Test: `tests/test_daily_report.py`
- Test: `tests/test_daily_report_curated.py`

- [ ] **Step 1: Write failing tests**

Add cases for a trailing Chinese word, a URL with a fragment, a semantic query parameter, a known tracker, and two `song?id=` URLs that must remain distinct.

- [ ] **Step 2: Run focused tests**

Run: `uv run pytest -q tests/test_store_summary.py tests/test_daily_report.py tests/test_daily_report_curated.py`

Expected: failures showing the current extractor consumes Chinese text and the current dedupe key collapses query URLs.

- [ ] **Step 3: Implement the minimal URL rules**

Use an ASCII URL character class in `summary.py`; in `daily_report.py`, centralize known tracking keys, preserve non-tracking query pairs and fragments, and make `dedupe_url_key` return the normalized URL.

- [ ] **Step 4: Run focused tests again**

Run the same command and require all focused tests to pass.

### Task 2: Curate and format the daily report

**Files:**
- Modify: `qq_onebot_whitelist/daily_report.py`
- Modify: `qq_onebot_whitelist/content_utils.py`
- Test: `tests/test_daily_report_curated.py`
- Test: `tests/test_resource_link_report.py`

- [ ] **Step 1: Write failing tests**

Assert high-value links appear first, unknown links are capped after them, repeated links keep the best context, and context does not repeat the same URL or exceed the compact limit.

- [ ] **Step 2: Run tests and confirm red**

Run: `uv run pytest -q tests/test_daily_report_curated.py tests/test_resource_link_report.py`

- [ ] **Step 3: Implement selection and rendering**

Use the existing score/purpose helpers, apply a deterministic score/domain/time ordering, cap rendered links, and keep raw URLs visible for QQ clickability.

- [ ] **Step 4: Run tests and confirm green**

Run the same focused command.

### Task 3: Add safe cached HTML metadata enrichment

**Files:**
- Create: `qq_onebot_whitelist/link_metadata.py`
- Modify: `qq_onebot_whitelist/daily_report.py`
- Modify: `qq_onebot_whitelist/store.py`
- Test: `tests/test_link_metadata.py`
- Test: `tests/test_daily_report_curated.py`

- [ ] **Step 1: Write failing tests**

Test title/description parsing, timeout/error fallback, rejection of loopback/private hosts, and cache reuse without a second fetch.

- [ ] **Step 2: Run the new tests to confirm red**

Run: `uv run pytest -q tests/test_link_metadata.py`

- [ ] **Step 3: Implement the bounded fetcher and SQLite cache**

Use `urllib.request`, a 3-second timeout, a 256 KiB read limit, HTML content-type checks, `html.parser`, and a cache keyed by normalized URL. Catch all fetch/parser failures and return no metadata.

- [ ] **Step 4: Enrich only selected report links**

Call the fetcher for the report cap, prefer page title/description over duplicated chat context, and leave the existing context fallback unchanged.

- [ ] **Step 5: Run metadata and report tests**

Run: `uv run pytest -q tests/test_link_metadata.py tests/test_daily_report.py tests/test_daily_report_curated.py`

### Task 4: Record LLM usage and safe retry state

**Files:**
- Modify: `qq_onebot_whitelist/llm_summary.py`
- Modify: `qq_onebot_whitelist/ai_context_analyze.py`
- Modify: `qq_onebot_whitelist/store.py`
- Test: `tests/test_llm_summary.py`
- Test: `tests/test_ai_context_batches.py`

- [ ] **Step 1: Write failing tests**

Assert a mocked successful response exposes all three usage counters, and a failed request does not advance the analysis cursor or create a completed batch.

- [ ] **Step 2: Run focused tests and confirm red**

Run: `uv run pytest -q tests/test_llm_summary.py tests/test_ai_context_batches.py`

- [ ] **Step 3: Implement usage capture and retry metadata**

Return the normalized summary together with optional usage, persist usage in the batch JSON, classify transient versus permanent errors, and keep the existing no-target-image fast path.

- [ ] **Step 4: Run focused LLM tests**

Run the same command and require all tests to pass.

### Task 5: Full verification and working-tree review

**Files:**
- No additional production files.

- [ ] **Step 1: Run the complete suite**

Run: `uv run pytest -q`

- [ ] **Step 2: Inspect the diff**

Run: `git diff --check` and `git status --short`; confirm only link/report/metadata/usage files and their tests changed beyond the pre-existing dirty worktree.

- [ ] **Step 3: Generate a local report preview**

Build a report from the existing database without sending it to QQ, verify semantic query parameters remain, trackers are removed, and no secret or private-network fetch occurs.
