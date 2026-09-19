# SonicDNA Known Limitations

Honest list of constraints for the soft launch. These are not bugs — they are deliberate boundaries.

---

## Analytics & Feedback

- **No real-time analytics dashboard.** Feedback events are append-only JSONL (`feedback_events.jsonl`) designed for offline analysis. No user-facing analytics UI exists.
- **`/admin/health` uses bounded in-memory monitoring.** It should be paired with hosting-provider uptime checks for production reliability.

## Email

- **Email notifications require SMTP credentials.** If `SMTP_USERNAME` and `SMTP_PASSWORD` are not set, email-dependent features (retake reminders, share notifications, comparison alerts) degrade silently.
- **No email verification flow.** Email is optional and trusted at face value.

## Leaderboards

- **City leaderboard requires critical mass.** The default `min_users=5` threshold means new cities won't appear until enough users from that city complete the quiz.

## Audio Clips

- **Clip coverage may be incomplete.** Some genre categories may have fewer clips than ideal. The clip rotator handles this gracefully but coverage diagnostics should be reviewed post-launch.

## Security & Sessions

- **No rate limiting on public API endpoints.** The system relies on hosting-provider-level rate limiting. Consider adding application-level rate limiting if abuse is detected.
- **No user account deletion flow.** Users can disconnect Spotify but cannot delete their SonicDNA session data through the UI.
- **Session tokens are stateless (HMAC-signed).** There is no server-side revocation mechanism — compromised tokens remain valid until the `SESSION_TOKEN_SECRET` is rotated.
- **Token encryption uses a development fallback key** when `SPOTIFY_TOKEN_ENCRYPTION_KEY` is not set. This is blocked in production by `enforce_deployment_environment()`.

## Mobile & Browser

- **Mobile Safari audio autoplay restrictions** may affect clip playback. Users may need to tap to initiate audio.
- **Private browsing / restricted WebViews** may reject `localStorage`. The app handles this gracefully (session works in memory) but the session won't persist across page refreshes.
- **No offline mode.** The app requires an active network connection.

## Spotify Integration

- **Spotify API rate limits apply.** High-traffic periods may cause temporary degradation in taste profile fetching.
- **Spotify free-tier users** have limited preview URL availability. Some playlist tracks may lack playable previews.
- **Brand-new Spotify accounts** with little listening history produce sparse taste profiles.

## Playlist Generation

- **Playlist quality depends on Spotify API credentials.** If the client credentials are missing or invalid, playlist generation falls back to recommendations.
- **No saved playlist export to Spotify.** Playlists are generated and displayed but not saved to the user's Spotify library (this is intentional for the soft launch).

## General

- **The first production run should be treated as a monitored soft launch**, not a traffic spike event. Plan for observation, not scale.
