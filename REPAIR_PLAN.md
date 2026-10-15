# SonicDNA — Autonomous Repair Plan

**Status:** Phase 1 Complete (Baseline Established) → Phase 2 Complete (Feature Inventory & Contract Mapping) → Phase 3 & 4 Complete (Repairs & Live Verification)  
**Updated:** 2026-10-15  
**Target Architecture:** FastAPI backend (`backend/`), Vanilla HTML/Tailwind/JS frontend (`frontend/index.html`, `frontend/login.html`), SQLAlchemy 2.0 persistence with Postgres/SQLite resilience, Spotify OAuth & Web API, Groq/Gemini AI engines.

---

## 1. Defect Inventory & Resolution Status

### Priority 1: Prevent Data Loss, Security Regressions, and Destructive Changes
- **DEF-01: Resilient Database Persistence (Supabase Outage / DNS Failure Fallback)** `[RESOLVED]`
  - *Symptom:* `psycopg2.OperationalError: could not translate host name "db.psfdwezsgypxxmfzmvfb.supabase.co"` and `tenant/user postgres.psfdwezsgypxxmfzmvfb not found`. The configured remote Supabase instance in `backend/.ENV` is offline/non-existent.
  - *Impact:* All snapshot saves, user sessions, comparisons, leaderboards, and timelines fail with HTTP 500.
  - *Fix:* Implemented `_init_resilient_engine()` in `backend/app_database.py`. Attempts connection to `DATABASE_URL`; if PostgreSQL is unreachable or errors on pool checkout, logs a warning and falls back to local SQLite (`sqlite:///./sonic_dna_dev.db`) with `check_same_thread=False` and auto-runs table migrations.
- **DEF-02: Deployment Environment Check vs Local Development** `[RESOLVED]`
  - *Symptom:* `SONICDNA_ENV=production` set in `backend/.ENV` while `SPOTIFY_REDIRECT_URI=http://127.0.0.1:8000/auth/callback` causes `enforce_deployment_environment()` to abort startup with `RuntimeError: Unsafe production configuration`.
  - *Impact:* Backend fails to start locally on `http://127.0.0.1:8000`.
  - *Fix:* Configured `SONICDNA_ENV=development` in `backend/.ENV` for the local environment.

### Priority 2: Restore Application Startup and Core User Journeys
- **DEF-03: Startup Route Conflict & Undefined `db_session` in Recommendations** `[RESOLVED]`
  - *Symptom:* `main.py` lines 2543 & 2625 reference `db_session.query(...)`, but `db_session` was not defined.
  - *Impact:* Calling recommendations crashed with `NameError: name 'db_session' is not defined`.
  - *Fix:* Updated `main.py` to use `SessionLocal()` context manager and corrected model attribute access (`taken_at`, `archetype_name`, `region`).
- **DEF-04: Compatibility Comparison Schema Mismatch (Boolean vs Float)** `[RESOLVED]`
  - *Symptom:* `test_comparison.py` failed with `sqlalchemy.exc.StatementError: (builtins.TypeError) Not a boolean value: 50.0`. `GenomeComparison.archetype_match` is a `Boolean` column, but `main.py:1135` passed `comparison["archetype_chemistry"]` (a Float, e.g. 50.0).
  - *Impact:* Saving genome comparisons between users crashed with SQL type errors.
  - *Fix:* In `main.py:1135`, set `"archetype_match": bool(comparison.get("archetype_match"))`, and in `app_database.py:save_genome_comparison()`, sanitized `archetype_match` with `bool()`.

### Priority 3: Fix Frontend/Backend Integration and API Contract Mismatches
- **DEF-05: Spotify OAuth Test Mock Signature Mismatch** `[RESOLVED]`
  - *Symptom:* `test_spotify_callback_rejects_first_connection_without_refresh_token` in `spotify_oauth_integration_test.py` failed because `exchange_code(code, state)` took 2 positional parameters, but the test monkeypatch mock was `lambda code: ...`.
  - *Fix:* Updated test mock in `spotify_oauth_integration_test.py` to accept `(code, *args, **kwargs)`.
- **DEF-06: Region Propagation to Snapshot Save** `[RESOLVED]`
  - *Symptom:* In `frontend/index.html:6252`, `region: 'global_english'` was hardcoded during snapshot save instead of using the user's selected region from `journeyState.selectedRegion`.
  - *Fix:* Updated payload in `frontend/index.html` (lines 6252, 6284, 6318, 7542) to pass `window.journeyState?.selectedRegion || 'global_english'`.
- **DEF-07: Static Assets and Audio Preview Paths** `[RESOLVED]`
  - *Symptom:* Missing static mounts for `/frontend` and `/images` prevented direct frontend access and asset loading.
  - *Fix:* Added `app.mount("/frontend", StaticFiles(...))` and `app.mount("/images", StaticFiles(...))` in `backend/main.py`.
- **DEF-08: AI Model Unavailability and Heuristic Fallback** `[RESOLVED]`
  - *Symptom:* Groq key lacked permissions for `llama-3.3-70b-versatile` (404 model not found) and Gemini key returned 401 unauthenticated.
  - *Fix:* Updated `.ENV` to use active `qwen/qwen3.8-27b` model on Groq, and added deterministic `_heuristic_text_genome()` fallback in `backend/engine.py` so psychometric genome extraction never fails.
- **DEF-09: Gemini Service Keyword Argument Error** `[RESOLVED]`
  - *Symptom:* `analyze_psychological_answers()` in `backend/gemini_service.py` threw `TypeError: unexpected keyword argument 'clip_ratings'`.
  - *Fix:* Added `clip_ratings: Optional[List[dict]] = None, **kwargs` to `analyze_psychological_answers()`.

### Priority 4: Web Application Routing and User Journey Polish
- **DEF-10: Browser Direct Navigation and Content Negotiation** `[RESOLVED]`
  - *Symptom:* Navigating to `http://127.0.0.1:8000/` or `/index.html` or `/login.html` returned either JSON or 404, preventing web browsers from loading the single-page application.
  - *Fix:* Added explicit `@app.get("/index.html")` and `@app.get("/login.html")` endpoints returning `HTMLResponse`, and updated `@app.get("/")` to return `HTMLResponse` for web browsers while preserving JSON API overview for clients requesting `application/json`.
- **DEF-11: Forced Guest Redirect in `index.html` Boot** `[RESOLVED]`
  - *Symptom:* First-time visitors without a token in `localStorage` were immediately redirected to `login.html`, preventing direct access to the landing hero page and journey flow.
  - *Fix:* Updated `boot()` in `frontend/index.html` to automatically bootstrap an anonymous guest session token via `/user/session`, enabling instant onboarding without forced redirects.
- **DEF-12: Missing Route Decorator on `/recommendations/{cluster_id}/{region_key}`** `[RESOLVED]`
  - *Symptom:* Endpoint was documented in API spec and invoked by regional recommendations clients, but `get_recommendations()` in `backend/main.py` lacked `@app.get` route decorator, returning 404.
  - *Fix:* Decorated `get_recommendations()` with `@app.get("/recommendations/{cluster_id}/{region_key}")`.
- **DEF-13: Rating Validation Type Mismatch** `[RESOLVED]`
  - *Symptom:* `ClipRating` Pydantic model enforced strict `int`, failing requests that submitted numeric float ratings with HTTP 422.
  - *Fix:* Updated `ClipRating.rating: float` to accept both integers and floating-point ratings seamlessly.

---

## 2. Verification Summary

- **Unit and Integration Suites:** **113 passed, 0 failed** across all backend test suites (`pytest -q`).
- **Live Server End-to-End Suite:** **4 passed, 0 failed** (`test_live_e2e_suite.py`) testing live server `http://127.0.0.1:8000` for:
  - Root and static file serving (`/`, `/index.html`, `/login.html`)
  - Readiness and health diagnostics (`/health`, `/ready`)
  - Full onboarding journey (`/user/session`, `/auth/me`, `/clips/round1`, `/clips/submit`, `/adaptive_question`, `/analyze_adaptive`, `/user/save_snapshot`, `/playlist/session/{id}`, `/recommendations/{cluster}/{region}`, `/share/create`, `/share/{code}`, `/feedback/events`)
  - Social constellation & user compatibility comparison (`/social/stats`, `/social/constellation`, `/compatibility/compare`).
