# SonicDNA Production Deployment

## Frontend

1. Set `VITE_SONIC_API_URL` to the public backend origin.
2. Run `npm ci` and `npm run build` in `website`.
3. Deploy `website/dist` to a static HTTPS host.
4. Configure CDN caching for static assets; do not cache HTML longer than the host's normal safe default.

## Backend

1. Set all variables from `backend/.env.production.example` in the hosting secret manager.
2. Run the FastAPI app from `backend/main.py` with the working directory set to `backend`.
3. Expose HTTPS through the host/load balancer.
4. Use `/ready` for deploy readiness checks.
5. Use `/health` for lightweight service health.
6. Use `/admin/health` only with `SONICDNA_MONITOR=1` for internal operations.

## Release Gate

Run these before promoting:

```powershell
cd website
npm test
npm run build
npm run lint
cd ..
python -m py_compile backend/main.py
python -m pytest backend/spotify_oauth_integration_test.py backend/feedback_test.py
```

## Production Safety

- Never commit real values for `SESSION_TOKEN_SECRET`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_TOKEN_ENCRYPTION_KEY`, or provider API keys.
- Keep `CORS_ALLOW_ORIGINS` restricted to the frontend origin.
- Keep `SPOTIFY_REDIRECT_URI` on public HTTPS.
- Rotate secrets immediately if they appear in logs, screenshots, issue trackers, or chat.
- Treat feedback events as internal operational data only.
