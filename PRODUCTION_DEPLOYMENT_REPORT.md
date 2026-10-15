# SonicDNA — Production Deployment Report

**Date:** 2026-10-16  
**Final Release Status:** **DEPLOYED WITH LIMITATIONS**  
*(Live application is deployed and operational at public HTTPS origin with 100% verified core journeys and resilient SQLite fallback; external persistent Supabase PostgreSQL sync remains blocked pending manual project unpause).*

---

## 1. Deployment Platform & Public URLs

- **Hosting Platform:** Render Cloud Platform (Web Service)
- **Repository Remote:** `https://github.com/ApaarAg/SonicDNA-2.git`
- **Active Branch:** `main`
- **Deployed Commit:** `e93f5fb` (`fix(prod): resilient database fallback, HTML SPA routing, and API contract parity`)
- **Public Application URLs:**
  - **Landing Page (Single Page App):** `https://sonicdna-2.onrender.com/` (HTTP 200, UTF-8 HTML)
  - **Direct Index SPA:** `https://sonicdna-2.onrender.com/index.html` (HTTP 200, UTF-8 HTML)
  - **Dedicated Login Portal:** `https://sonicdna-2.onrender.com/login.html` (HTTP 200, UTF-8 HTML)
  - **Readiness Diagnostic:** `https://sonicdna-2.onrender.com/ready` (HTTP 200)
  - **Health Diagnostic:** `https://sonicdna-2.onrender.com/health` (HTTP 200)

---

## 2. Deployment ID, Build, and Startup Commands

- **Build Pipeline:** Render native Python environment
  - **Build Command:** `pip install -r requirements.txt`
  - **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
  - **Trigger:** Automated Git push to `origin/main`
- **Local Startup Verification:**
  - `python -m py_compile backend/main.py backend/app_database.py backend/engine.py` (Exit code 0, 0 syntax errors)
  - `python -m uvicorn main:app --host 127.0.0.1 --port 8000` (Running daemon on port 8000)

---

## 3. Test Commands & Exact Execution Results

### 3.1 Local Pytest Regression Suite
```bash
pytest -q
```
- **Exit Code:** `0`
- **Result:** **113 passed**, 0 failed, 51 warnings (Python 3.13 `datetime.utcnow()` notices) in 80.16s.

### 3.2 Live Local E2E Suite (`http://127.0.0.1:8000`)
```bash
pytest test_live_e2e_suite.py -v -s
```
- **Exit Code:** `0`
- **Result:** **4 passed**, 0 failed in 7.22s.

### 3.3 Live Public Production E2E Suite (`https://sonicdna-2.onrender.com`)
```bash
$env:SONICDNA_TEST_URL="https://sonicdna-2.onrender.com"; pytest test_live_e2e_suite.py -v -s
```
- **Exit Code:** `0`
- **Result:** **4 passed**, 0 failed in 33.26s.
  - `test_01_root_and_static_serving`: **PASSED** (Root GET `/`, `/index.html`, `/login.html` return UTF-8 HTML containing DOM structures)
  - `test_02_health_and_ready`: **PASSED** (Services active, database status accurately exposed)
  - `test_03_full_user_onboarding_journey`: **PASSED** (Session token, 8 calibration clips, submit rating, adaptive question, genome synthesis, snapshot persistence, 20-track flow playlist, regional recommendations, viral share link creation and retrieval, feedback telemetry)
  - `test_04_social_and_compatibility`: **PASSED** (Social stats, constellation graph, multi-dimensional user compatibility comparison)

---

## 4. Feature Acceptance Matrix & Live Production Evidence

| Feature / Journey | Backend Route | Status | Observed Production Evidence (`https://sonicdna-2.onrender.com`) |
|---|---|---|---|
| **Root SPA Delivery** | `GET /` | **PASS** | Returns HTTP 200, `Content-Type: text/html; charset=utf-8`, serving 372 KB containing `#scene-1`, `#scene-quiz`, `#scene-share`. |
| **Direct Index HTML** | `GET /index.html` | **PASS** | Returns HTTP 200, serving full single-page application structure. |
| **Direct Login HTML** | `GET /login.html` | **PASS** | Returns HTTP 200, serving Spotify OAuth login interface. |
| **Lightweight Health** | `GET /health` | **PASS** | Returns HTTP 200 with service booleans; database status correctly reported as fallback SQLite without leaking credentials. |
| **Deploy Readiness** | `GET /ready` | **PASS** | Returns HTTP 200; reports database fallback state and configuration validity. |
| **Session Bootstrap** | `POST /user/session` | **PASS** | Returns HTTP 200; creates HMAC-signed session `sd1.*`, `profile_code: SD-53D8E9`, anonymous guest profile. |
| **Profile Retrieval** | `GET /auth/me` | **PASS** | Returns HTTP 200 with session user profile. |
| **Audio Calibration** | `GET /clips/round1` | **PASS** | Returns 8 calibration tracks with playable audio URLs and category diversity. |
| **Rating Submission** | `POST /clips/submit` | **PASS** | Accepts float and integer ratings without HTTP 422 errors. |
| **Adaptive Text Probe** | `POST /adaptive_question` | **PASS** | Generates contextual psychometric questions based on audio selections. |
| **Genome Synthesis** | `POST /analyze_adaptive` | **PASS** | Synthesizes 7D psychometric traits, archetype ID, shadow archetype, and cluster ID using Groq with deterministic heuristic fallback. |
| **Snapshot Persistence** | `POST /user/save_snapshot` | **PASS** | Persists genome snapshot, updates taste drift history, and links selected region. |
| **Emotional Flow Playlist** | `POST /playlist/session/{cluster_id}` | **PASS** | Generates 20-track dynamic emotional arc playlist with discovery/library balance. |
| **Regional Tracks** | `GET /recommendations/{cluster_id}/{region}` | **PASS** | Resolves curated regional tracks (tested with cluster 5, region `japan`). |
| **Viral Share Links** | `POST /share/create` & `GET /share/{code}` | **PASS** | Generates 8-character unique share codes and retrieves inviter profile for instant 2-user comparison. |
| **Social Constellation** | `GET /social/constellation` & `/stats` | **PASS** | Returns network density, node clusters, and listener graph. |
| **Compatibility Comparison** | `POST /compatibility/compare` | **PASS** | Computes cosine similarity, archetype chemistry, and enforces boolean column constraints. |
| **Feedback Telemetry** | `POST /feedback/events` | **PASS** | Ingests telemetry events without blocking user interaction. |
| **Spotify OAuth Flow** | `GET /auth/login` & `/callback` | **PARTIAL** | Integration tests and PKCE handling pass; live Spotify OAuth redirect requires active user Spotify account interaction. |
| **Email Reminders** | `email_scheduler.py` | **PARTIAL** | Background reminder queue and retry logic operational; external email dispatch depends on SMTP server credentials. |

---

## 5. Production Database Verification

- **Configured Remote Database:** Supabase PostgreSQL (`aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres`)
- **Observed Remote Connection Result:**  
  `connection to server at "aws-0-ap-southeast-2.pooler.supabase.com" failed: FATAL: (ENOTFOUND) tenant/user postgres.psfdwezsgypxxmfzmvfb not found`
- **Root Cause:** The remote Supabase free-tier project `psfdwezsgypxxmfzmvfb` is paused by Supabase infrastructure due to inactivity.
- **Resilient Fallback Behavior:**  
  - Application implements `_init_resilient_engine()` in `backend/app_database.py`.
  - Falls back cleanly to local SQLite (`sonic_dna_dev.db`) on PostgreSQL connection failure.
  - Automatically migrates and verifies all 24 schema tables.
  - Verified persistence: `users`, `genome_snapshots`, `share_links`, and `genome_comparisons` read and write cleanly across sessions.
- **Production Guardrail:**  
  - In production mode, `/ready` and `/health` accurately report:
    `"database": {"connected": false, "dialect": "sqlite", "fallback_active": true, "persistent_storage": false}`.
  - Ephemeral SQLite is visibly exposed and warns operator that cross-instance persistence requires PostgreSQL restoration.

---

## 6. AI, Spotify, and External Integrations

- **Groq AI Service:**
  - Configured with `qwen/qwen3.8-27b` model.
  - Active and operational for psychometric genome extraction.
- **Google Gemini SDK:**
  - Configured API key returns HTTP 401 Unauthenticated.
  - Handled via deterministic `_heuristic_text_genome()` fallback; user onboarding never crashes or stalls.
- **Spotify OAuth & Web API:**
  - Client ID and Client Secret configured.
  - OAuth redirect URI points to `https://sonicdna-2.onrender.com/auth/callback`.
  - Non-authenticated visitors seamlessly use regional cached tracks and audio clips.
- **Email Service (SMTP):**
  - Background scheduler operational; live email dispatch requires real SMTP credentials.

---

## 7. Security and Configuration Audit

- [x] **No Secrets Leaked:** No private tokens, API keys, or database passwords appear in frontend bundles, logs, or diagnostic endpoint responses (`/ready`, `/health`).
- [x] **Production Security Headers:** `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, and `Cache-Control: no-store` attached to API responses.
- [x] **Session Signing:** HMAC-signed session tokens (`sd1.*`) with secret key validation.
- [x] **CORS Configuration:** Production origins configured with trusted hosts.
- [x] **Environment Isolation:** Credentials stored exclusively in environment variables; `.ENV` files excluded via `.gitignore`.

---

## 8. Known Issues & Outstanding Risks

1. **Supabase PostgreSQL Paused (High):**  
   The managed PostgreSQL instance is currently paused on Supabase. The deployed application is functioning using local SQLite storage. Until Supabase is restored, storage is local to the Render container.
2. **Gemini API Key Unauthorized (Low):**  
   Gemini API key is invalid/expired; Groq and heuristic fallback are handling all AI analysis smoothly.
3. **CDP Automation Container Lock (Info):**  
   Local Windows CDP browser session is bound to a locked desktop widget container, requiring HTTP-level E2E integration verification.

---

## 9. Action Required (Single Human Step)

> **Unpause Supabase PostgreSQL Database:**  
> Log into [Supabase Dashboard](https://supabase.com/dashboard/project/psfdwezsgypxxmfzmvfb) and click **"Restore project"** (or update `DATABASE_URL` in the Render dashboard environment settings with a newly provisioned PostgreSQL connection string).  
> The deployed application will automatically detect the active PostgreSQL connection upon next restart without requiring code modifications.

---

## 10. Rollback Procedure

If immediate rollback is necessary:
1. Revert Git `main` branch to the previous commit `899d686`:
   ```bash
   git revert e93f5fb
   git push origin main
   ```
2. Render will automatically detect the push and redeploy previous commit `899d686`.
   *(Note: Rolling back will re-introduce the Supabase crash on `POST /user/session` unless Supabase is restored).*
