# SonicDNA Production Smoke Tests

Run these against any deployed instance to verify core functionality. Replace `$API` with the production backend URL.

---

## 1. Readiness Check

```bash
curl -s "$API/ready" | python -m json.tool
```

**Expected:** HTTP 200, `"status": "ready"`, no secret values.

---

## 2. Health Check

```bash
curl -s "$API/health" | python -m json.tool
```

**Expected:** HTTP 200, service booleans only. Verify:
- `genome_engine: true`
- `spotify_service: true`
- `playlist_generator: true`
- No API keys, tokens, or credentials in response.

---

## 3. Session Creation

```bash
curl -s -X POST "$API/user/session" \
  -H "Content-Type: application/json" \
  -d '{}' | python -m json.tool
```

**Expected:** Returns `session_token` (format `sd1.<payload>.<sig>`), `display_name`, `profile_code`.

Save the token:
```bash
TOKEN="<session_token from response>"
```

---

## 4. Adaptive Question Flow

```bash
curl -s -X POST "$API/adaptive_question" \
  -H "Content-Type: application/json" \
  -d '{"previous_answers": [], "clip_ratings": []}' | python -m json.tool
```

**Expected:** `"continue": true`, a `question` string, and a `hint`.

---

## 5. Genome Analysis

```bash
curl -s -X POST "$API/analyze_adaptive" \
  -H "Content-Type: application/json" \
  -d "{\"session_token\": \"$TOKEN\", \"answers\": [\"I love ambient electronic music that sounds like rain\", \"Radiohead changed how I think about sound\", \"Music hits hardest when I'm alone at 2am\"], \"clip_ratings\": []}" | python -m json.tool
```

**Expected:** Returns genome features, archetype, cluster_id, radar data.

---

## 6. Save Snapshot

```bash
# Use the result from step 5 as the "result" field
curl -s -X POST "$API/user/save_snapshot" \
  -H "Content-Type: application/json" \
  -d "{\"session_token\": \"$TOKEN\", \"result\": {\"genome_features\": {\"energy\": 0.3, \"valence\": -0.5}}, \"region\": \"global_english\"}" | python -m json.tool
```

**Expected:** `"saved": true`, `snapshot_count >= 1`.

---

## 7. Playlist Generation

```bash
curl -s -X POST "$API/playlist/session/3" \
  -H "Content-Type: application/json" \
  -d "{\"session_token\": \"$TOKEN\", \"target_minutes\": 30}" | python -m json.tool
```

**Expected:** Returns tracks array with `name`, `artist`, and metadata.

---

## 8. Share Link Creation

```bash
curl -s -X POST "$API/share/create" \
  -H "Content-Type: application/json" \
  -d "{\"session_token\": \"$TOKEN\"}" | python -m json.tool
```

**Expected:** Returns `share_code`, optionally `full_url`.

---

## 9. Share Link Retrieval

```bash
SHARE_CODE="<share_code from step 8>"
curl -s "$API/share/$SHARE_CODE" | python -m json.tool
```

**Expected:** Returns share details with `is_valid: true`.

---

## 10. Feedback Event Recording

```bash
curl -s -X POST "$API/feedback/events" \
  -H "Content-Type: application/json" \
  -d "{\"session_token\": \"$TOKEN\", \"events\": [{\"event_type\": \"smoke_test\", \"client_context\": {\"source\": \"smoke_test_script\"}}]}" | python -m json.tool
```

**Expected:** `"recorded": 1`.

---

## 11. Security Headers Check

```bash
curl -sI "$API/health" | grep -iE "(x-content-type|referrer-policy|x-frame|permissions-policy|strict-transport)"
```

**Expected:** All four security headers present. HSTS present if HTTPS.

---

## 12. Error Sanitization Check

```bash
# Trigger a controlled error in development
curl -s -X POST "$API/analyze" \
  -H "Content-Type: application/json" \
  -d '{"answers": [1]}' | python -m json.tool
```

**Expected in production:** Generic error message like `"Analysis failed."` — no Python stack traces or internal details.

---

## 13. Spotify OAuth Flow (Manual)

1. Open `$API/spotify/login?session_token=$TOKEN&return_to=<frontend_url>` in a browser.
2. Authorize on Spotify.
3. Verify redirect back to frontend with `?spotify=connected`.
4. Check `GET $API/spotify/status?session_token=$TOKEN` returns `connected: true`.
5. Disconnect: `POST $API/spotify/disconnect` with `session_token`.
6. Verify status returns `connected: false`.

---

## Quick One-Liner (All Automated Tests)

```powershell
$API = "http://127.0.0.1:8010"

# Health
Invoke-RestMethod "$API/ready" | ConvertTo-Json
Invoke-RestMethod "$API/health" | ConvertTo-Json

# Session
$session = Invoke-RestMethod -Method POST -Uri "$API/user/session" -ContentType "application/json" -Body '{}'
$token = $session.session_token
Write-Host "Session token: $token"

# Question
Invoke-RestMethod -Method POST -Uri "$API/adaptive_question" -ContentType "application/json" -Body '{"previous_answers": [], "clip_ratings": []}' | ConvertTo-Json

# Feedback
Invoke-RestMethod -Method POST -Uri "$API/feedback/events" -ContentType "application/json" -Body "{`"session_token`": `"$token`", `"events`": [{`"event_type`": `"smoke_test`"}]}" | ConvertTo-Json

Write-Host "Smoke tests complete."
```
