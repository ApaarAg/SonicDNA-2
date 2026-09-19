# SonicDNA Launch Checklist

Every item is a binary pass/fail gate. Complete all before promoting to production.

---

## Environment Configuration

- [ ] `SONICDNA_ENV=production` is set
- [ ] `SESSION_TOKEN_SECRET` is a cryptographically random string ≥48 characters
- [ ] `SPOTIFY_TOKEN_ENCRYPTION_KEY` is set to a Fernet key (not the dev fallback)
- [ ] `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` are production Spotify app credentials
- [ ] `SPOTIFY_REDIRECT_URI` is a public HTTPS URL matching the Spotify dashboard exactly
- [ ] `OPENROUTER_API_KEY` is set and quota verified
- [ ] `CORS_ALLOW_ORIGINS` lists only the production frontend origin (no `*`)
- [ ] `SONICDNA_FRONTEND_URL` / `FRONTEND_URL` points to the production frontend
- [ ] `SONICDNA_MONITOR=1` is set for operational monitoring
- [ ] No real secrets appear in git history, screenshots, or chat logs

## DNS & HTTPS

- [ ] Domain name is registered and DNS is configured
- [ ] Frontend is served over HTTPS (valid TLS certificate)
- [ ] Backend is served over HTTPS (valid TLS certificate)
- [ ] `HSTS` header is active on backend responses
- [ ] Spotify dashboard callback URL matches the production `SPOTIFY_REDIRECT_URI`

## Frontend Deployment

- [ ] `VITE_SONIC_API_URL` is set to the production backend origin before building
- [ ] `npm ci && npm run build` produces `website/dist` cleanly
- [ ] `website/dist` is deployed to static HTTPS host
- [ ] CDN caching is configured for static assets (JS/CSS/images)
- [ ] HTML is not cached longer than the host's safe default
- [ ] Previous `dist` build is preserved for rollback

## Backend Deployment

- [ ] All env vars from `.env.production.example` are set in the hosting secret manager
- [ ] FastAPI app runs from `backend/main.py` with `backend/` as working directory
- [ ] HTTPS is provided by the hosting provider or load balancer
- [ ] Previous backend release is preserved for rollback

## Health Verification

- [ ] `GET /ready` returns HTTP 200 with `"status": "ready"`
- [ ] `GET /health` returns HTTP 200 with service booleans only (no secrets)
- [ ] `GET /admin/health` is accessible (requires `SONICDNA_MONITOR=1`)
- [ ] No secret values appear in any health endpoint response

## Functional Smoke Tests

- [ ] `POST /user/session` creates a valid session token
- [ ] Spotify connect → callback → status flow completes end-to-end
- [ ] Spotify disconnect flow works
- [ ] Adaptive quiz flow: question → answer → question → analyze → result
- [ ] Genome snapshot saves successfully
- [ ] Playlist generation returns real Spotify tracks
- [ ] Share link creation and retrieval works
- [ ] Feedback events are recorded without blocking user flow

## Security Headers

- [ ] `X-Content-Type-Options: nosniff` present
- [ ] `Referrer-Policy: strict-origin-when-cross-origin` present
- [ ] `X-Frame-Options: DENY` present
- [ ] `Permissions-Policy: camera=(), microphone=(), geolocation=()` present
- [ ] Production error responses return generic messages (no `str(e)` leaks)

## Cross-Browser / Device Testing

- [ ] Desktop Chrome
- [ ] Desktop Safari
- [ ] Desktop Firefox
- [ ] iPhone Safari (physical device)
- [ ] Android Chrome (physical device)
- [ ] Keyboard navigation works
- [ ] Reduced motion is respected

## Rollback Readiness

- [ ] Previous frontend static build available for immediate redeploy
- [ ] Previous backend release available for immediate rollback
- [ ] Rollback procedure documented and tested
- [ ] Team knows how to trigger rollback
