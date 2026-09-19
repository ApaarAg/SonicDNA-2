# SonicDNA Support Runbook

Issue triage flow for common problems. Use this during soft launch to resolve user-reported issues quickly.

---

## 1. "Spotify Won't Connect"

**Symptoms:** User clicks Spotify login but gets redirected back with `?spotify=error`.

**Triage steps:**

1. Check `SPOTIFY_REDIRECT_URI` matches the Spotify Developer Dashboard callback URL exactly (including trailing slash).
2. Check `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` are valid and not expired.
3. Check server logs for `[spotify.callback.failed]` — the error detail will indicate whether it's:
   - `missing_code` → User denied Spotify permissions
   - `connection_failed` → Token exchange failed (credential issue)
   - `missing_refresh_token` → Spotify didn't return a refresh token (user may need to re-authorize with `show_dialog=true`)
4. Verify `GET /spotify/status?session_token=<token>` returns correct state.

**Recovery:** If credentials are wrong, fix in secret manager and restart backend.

---

## 2. "Playlist Has No Tracks"

**Symptoms:** Playlist generation returns empty or very few tracks.

**Triage steps:**

1. Check `GET /health` — is `spotify_service: true`?
2. Check server logs for `[error] Playlist generation` messages.
3. If SpotifyService failed to initialize, check `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET`.
4. Verify the user has a saved genome snapshot (`POST /user/timeline`).
5. Check if the region/cluster combination has available tracks.

**Recovery:** If Spotify credentials are invalid, fix and restart. If the user has no snapshot, they need to complete the quiz first.

---

## 3. "Quiz Is Stuck / No Questions"

**Symptoms:** User sees loading state or no adaptive question appears.

**Triage steps:**

1. Check `GET /health` — is `openrouter_question_provider: true`?
2. Check `OPENROUTER_API_KEY` is set and has remaining quota.
3. Check server logs for `adaptive_question service fallback` messages.
4. The fallback question provider should always return a question even if OpenRouter is down.

**Recovery:** If OpenRouter is down, the stateless fallback provider generates questions automatically. If even that fails, check `adaptive_questions.py` for import errors.

---

## 4. "Results Look Wrong"

**Symptoms:** User's archetype or genome features don't match their musical identity.

**Triage steps:**

1. Check if Spotify taste blending was applied (`spotify_taste_influence.applied` in the result).
2. The blend weight is 12% Spotify / 88% quiz — extreme Spotify listening habits may subtly shift results.
3. If the user answered very short or nonsensical quiz answers, the LLM analysis may produce unexpected genome vectors.
4. Check the `source` field in the result to understand which analysis path was used.

**Recovery:** User can retake the quiz. Drift tracking will show how results change.

---

## 5. "Share Link Not Working"

**Symptoms:** Friend opens share link but gets 404 or 410.

**Triage steps:**

1. Check `GET /share/<code>` — does it return `is_valid: true`?
2. If `is_expired: true`, the link has passed its expiry date.
3. If `is_completed: true`, the link has already been used.
4. Check that `SONIC_SHARE_BASE_URL` is set if you're using full URLs.

**Recovery:** User can create a new share link.

---

## 6. "Page Won't Load / Blank Screen"

**Symptoms:** Frontend shows blank page or console errors.

**Triage steps:**

1. Check browser console for JavaScript errors.
2. Verify `VITE_SONIC_API_URL` was set correctly at build time.
3. Check if the backend is reachable from the browser (CORS errors in console).
4. Verify CORS origins match the frontend domain.

**Recovery:** If CORS is misconfigured, update `CORS_ALLOW_ORIGINS` and restart backend.

---

## Emergency Rollback

### Frontend

1. Re-deploy the previous `website/dist` build to the static host.
2. DNS/CDN changes take effect based on TTL.

### Backend

1. Re-deploy the previous backend release/image.
2. Verify `GET /ready` returns 200 after rollback.

### Spotify Down / Playlist Generation Broken

1. The quiz and onboarding still function without Spotify.
2. Playlist generation will fail gracefully — users see an error message, not a crash.
3. If needed, temporarily disable playlist routes by returning 503.

### Feedback Ingestion Failure

1. The `/feedback/events` endpoint returns 202 if persistence fails — it never blocks the user flow.
2. Feedback data may be lost during the outage but the user experience is unaffected.

---

## Contact & Escalation

- Check server logs first (structured `[tag]` format).
- Check `GET /admin/health` for rolling metrics and anomaly detection.
- Rotate secrets immediately if they appear in logs, screenshots, or issue trackers.
