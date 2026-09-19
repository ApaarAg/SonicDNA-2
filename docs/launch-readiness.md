# SonicDNA Launch Readiness

This checklist is for the first public-facing deployment. It is intentionally operational, not a design backlog.

## Deployment Topology

- Frontend: static Vite build from `website/dist`, served over HTTPS.
- Backend: FastAPI app from `backend/main.py`, served over HTTPS.
- Frontend env: `VITE_SONIC_API_URL` points to the public backend origin.
- Backend env: use `backend/.env.production.example` as the required variable map.
- Spotify dashboard callback must exactly match `SPOTIFY_REDIRECT_URI`.
- CORS must list the production frontend origin only; do not use `*` in production.
- Media/CDN: keep atmospheric video and static fallback cacheable; API/user/feedback endpoints must remain `no-store`.

## Required Launch Checks

- `GET /ready` returns `200` and contains no secret values.
- `GET /health` returns service booleans only, not credentials.
- `GET /admin/health` is available only when `SONICDNA_MONITOR=1`.
- Frontend build points at the production API origin.
- Spotify connect, reconnect, disconnect, and expired-session paths are tested.
- Feedback ingestion writes append-only JSONL events without canonical identity.
- Production exception responses return generic messages.
- Security headers are present: `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options`, `Permissions-Policy`.

## Pre-Launch QA Matrix

- Desktop: Chrome, Safari, Firefox, Edge.
- Mobile: iPhone Safari, Android Chrome, low-memory Android device.
- Accessibility: keyboard navigation, visible focus, screen reader smoke pass, reduced motion.
- Network: normal, slow 3G, offline/retry, tab suspension and resume.
- Spotify profiles: brand-new account, sparse account, large account, obscure genres, expired auth.
- Playlist scenarios: heartbreak, focus, calm, workout, healing, celebration, discovery, night-drive, long session.
- Runtime failure cases: OpenRouter timeout, Spotify outage, empty recommendation pool, duplicate clicks, refresh during generation.

## Rollback Plan

- Keep the previous frontend static build available for immediate redeploy.
- Keep the previous backend image/release available for immediate rollback.
- If Spotify or playlist generation fails broadly, keep onboarding and reflective fallback active while disabling launch traffic.
- If feedback ingestion fails, allow the endpoint to degrade without blocking user flow.
- If atmospheric video causes mobile issues, force static media by treating the affected device class as constrained.

## Known Limits Before First Users

- Real iPhone Safari and Android Chrome validation must be done on physical devices.
- Feedback analytics are internal and offline-oriented; no user-facing analytics UI exists.
- `/admin/health` uses bounded in-memory monitoring and should be paired with hosting-provider uptime checks.
- The first production run should be treated as a monitored soft launch, not a traffic spike.
