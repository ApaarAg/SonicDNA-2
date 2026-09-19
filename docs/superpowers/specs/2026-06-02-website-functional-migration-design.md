# SonicDNA Website Functional Migration Design

Date: 2026-06-02

## Goal

Preserve the current `website/` cinematic shell and visual language while
connecting the missing production journey:

`Landing -> Spotify Connect or Continue without Spotify -> Region Selection -> Audio Clips -> Adaptive Quiz -> DNA Analysis -> Recommendations -> Playlist`

The current uncommitted `website/` tree is the protected baseline.

## Approved Approach

Extend the existing React runtime in place. Do not copy `frontend/` screens,
markup, styling, or layout. Transplant only API boundaries, state transitions,
payload mapping, persistence, async guards, and audio lifecycle logic.

Keep the existing chapter order. Runtime passages appear inside the existing
cinematic chapter composition:

- Recognition: Spotify-first onboarding choice.
- Identity: region selection and later DNA identity reveal.
- Listening Interview: audio clips first, adaptive questions second.
- Private Sync: connected, skipped, or reconnect status reflection.
- Emotional Session: recommendation arrival and playlist generation.
- Flow: generated playlist playback.
- Worlds: region-aware discovery reflection.
- Memory: timeline and sharing.

## Runtime Domains

Add three focused domains to the current split runtime:

### Journey

Track the active functional stage:

- `spotify-choice`
- `region`
- `clips`
- `quiz`
- `analysis`
- `results`
- `recommendations`
- `playlist`

The hero remains unchanged. The Recognition passage begins the functional path.
Spotify connection is optional, but the user must explicitly connect or choose
`Continue without Spotify` before region selection becomes active.

### Region

Track:

- available backend regions
- selected region key
- clip count, persisted locally
- loading and unavailable states

Region selection uses `GET /regions`. The default clip count is `8`, matching the
functional frontend reference.

### Clips

Track:

- unique clip session key
- round one and adaptive round two clips
- ratings for each round
- active round and clip index
- playable-count validation
- loading and unavailable states

The client must never render blank clip cards. Round one proceeds only if the
requested number of playable clips is returned. Round two may fall back to the
adaptive quiz when unavailable.

## Data Flow

### Spotify-first onboarding

`Recognition CTA -> session token -> GET /spotify/status -> Connect Spotify or Continue without Spotify -> region stage`

After OAuth callback, parse the `spotify` query parameter, refresh Spotify
status, remove callback query parameters, and advance to region when connected.

### Clips and adaptive quiz

`selected region -> GET /clips/round1 -> rate clips -> POST /clips/adaptive -> rate adaptive clips -> POST /adaptive_question`

Every adaptive question request includes:

- text answers
- all clip ratings
- covered dimensions
- asked questions

### Analysis and recommendations

`adaptive completion -> POST /analyze_adaptive -> POST /user/save_snapshot -> GET /recommendations/{cluster}/{region} -> results state`

Analysis includes:

- session token
- selected region
- text answers
- all clip ratings

The backend blends Spotify taste automatically when connected.

### Playlist

`results -> POST /playlist/session/{cluster} -> generated playlist -> Flow playback`

Playlist generation continues through the existing website CTA and playback
passage. Snapshot persistence carries the selected region into the backend
playlist generator.

## Error Handling

- Session bootstrap keeps the existing local recovery room.
- Spotify status failures keep the explicit bypass available.
- Partial round-one clip responses remain unavailable and do not render.
- Adaptive clip failures continue to the text interview with round-one ratings.
- Adaptive question failures use the existing calm fallback question.
- Analysis failures preserve the existing local identity fallback.
- Recommendation failures preserve identity and keep playlist generation
  available when snapshot persistence succeeds.

## UI Preservation Rules

- Do not reorder cinematic chapters.
- Do not redesign the shell.
- Do not copy legacy HTML or CSS.
- Reuse the existing `runtime-thread`, `runtime-button`, typography, atmosphere,
  transition, and recovery primitives.
- Add only the minimum CSS required for region choices and clip controls.
- Keep one audio element active at a time.

## Testing

Use failing tests before each production change:

1. Typed API methods for regions, round-one clips, adaptive clips, and
   recommendations.
2. Reducer progression for Spotify choice, region selection, clip loading,
   playable-count validation, ratings, and clip completion.
3. Provider integration for Spotify bypass, OAuth return refresh, region and
   clip progression, clip-aware adaptive question payloads, region-aware
   analysis, snapshot save, recommendations, and playlist generation.
4. Existing suite, production build, backend contract tests, and browser
   verification after implementation.

## Non-Goals

- No UI redesign.
- No legacy screen transplant.
- No chapter reordering.
- No compatibility, leaderboard, email capture, or trial-playlist expansion.
- No unrelated backend refactor.
