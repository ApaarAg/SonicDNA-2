# SonicDNA Website Functional Migration Completion Report

Date: 2026-06-02

## Scope

`website/` remains the visual and interaction source of truth. The migration
extends the existing cinematic shell in place and transplants only the missing
business logic and backend connections from `frontend/`.

The approved runtime journey is:

`Landing -> Spotify Connect or Continue without Spotify -> Region Selection -> Audio Clips -> Adaptive Quiz -> Analysis -> DNA Results -> Recommendations -> Playlist`

The existing cinematic chapter order remains unchanged. The later private-sync
chapter is still present as a status reflection, but it no longer starts a
second authentication request after onboarding.

The pre-fix architecture comparison is documented in
`docs/website-migration-audit-2026-06-02.md`.

## Architecture Comparison

| Website scene or runtime slice | Functional frontend reference | Final website behavior |
| --- | --- | --- |
| Recognition chapter | Spotify login, redirect status, optional continuation | First interactive step with `Bring in Spotify` and visible `Continue without Spotify`. |
| Journey runtime | Imperative frontend screen progression | Explicit stage transitions: Spotify, region, clips, quiz, analysis, results, recommendations, playlist. |
| Identity chapter before results | Region selection and clip-count preference | Loads backend regions, selects a region, and persists `sonic_dna_clip_count`. |
| Listening-interview chapter before text quiz | Round-one clips, rating navigation, adaptive clip round | Loads an exact playable batch, renders one active audio player, records ratings, then loads adaptive clips. |
| Listening-interview chapter after clips | Adaptive text question progression | Preserves the website interview UI and enriches requests with clip ratings, question history, and covered dimensions. |
| Identity results | Genome and archetype rendering | Preserves the existing result treatment and renders analyzed backend identity. |
| Worlds chapter | Region-aware recommendations | Requests and renders recommendations by analyzed cluster and selected region. |
| Emotional-session chapter | Session playlist generation | Preserves the existing playlist CTA and generates after snapshot persistence. |
| Flow chapter | Generated playlist playback | Preserves existing playlist and playback UI. |
| Private-sync chapter | Spotify connection state | Status-only reflection. No duplicate late OAuth request. |

## Backend Route Trace

| Stage | UI event | Website runtime action | Backend route | Backend layer | UI update |
| --- | --- | --- | --- | --- | --- |
| Session | Runtime bootstrap | `createSession` | `POST /user/session` | Session identity and database | Persisted session token |
| Spotify-first | `Bring in Spotify` | `spotifyLoginUrl` | `GET /spotify/login` | Spotify OAuth callback and saved account link | OAuth return refreshes status |
| Spotify bypass | `Continue without Spotify` | `continueWithoutSpotify` | No auth request | Optional path | Region selection opens |
| Regions | Region choice | `selectRegion`, `setClipCount` | `GET /regions` | Region catalog | Selected region and clip count |
| Clips round one | `Begin listening` | `loadRoundOneClips` | `GET /clips/round1` | Clip rotation and playable batch builder | Exact playable clip batch |
| Clips round two | Last rating `Next` | `nextClip` | `POST /clips/adaptive` | Adaptive clip selector | Follow-up clips or quiz fallback |
| Adaptive quiz | `Keep going` | `answerQuestion` | `POST /adaptive_question` | Adaptive question service | Next unique question or analysis |
| DNA analysis | Quiz completion | `answerQuestion` | `POST /analyze_adaptive` | Genome engine and optional Spotify taste blend | DNA identity and archetype |
| Snapshot | Analysis completion | `saveSnapshot` | `POST /user/save_snapshot` | Database genome snapshot | Persisted result |
| Recommendations | Identity ready | `getRecommendations` | `GET /recommendations/{cluster_id}/{region_key}` | Recommendation engine | Worlds recommendations list |
| Playlist | Playlist CTA | `generatePlaylist` | `POST /playlist/session/{cluster_id}` | Snapshot lookup and playlist generator | Existing flow playlist UI |

## Files Modified For Migration

The working tree already contained approved cinematic-shell changes before this
migration. Those files were audited and preserved. The migration-specific edits
are:

| File | Exact reason |
| --- | --- |
| `website/src/lib/api.ts` | Added typed regions, round-one clips, adaptive clips, and recommendations calls. |
| `website/src/runtime/types.ts` | Added journey, region, clip, and recommendation state plus narrow actions. |
| `website/src/runtime/sonicRuntimeReducer.ts` | Added ordered state transitions, exact playable-batch rejection, clip rating navigation, adaptive clip completion, and recommendation states. |
| `website/src/runtime/SonicRuntimeContext.ts` | Exposed onboarding, region, clip-count, loading, rating, and navigation actions. |
| `website/src/runtime/SonicRuntimeProvider.tsx` | Added Spotify-first redirect handling, optional bypass, region discovery, clip-count persistence, clip session keys, clip-aware quiz and analysis payloads, selected-region snapshots, recommendations loading, and playlist ordering. |
| `website/src/components/cinematic/SceneRuntimeContent.tsx` | Rendered new runtime controls through the existing cinematic chapter composition and removed the duplicate late Spotify auth affordance. |
| `website/src/index.css` | Added restrained styles for the new controls, audio player, and recommendation list without replacing the existing design system. |
| `website/src/__tests__/apiClient.test.ts` | Added typed transport regression coverage for new route mappings. |
| `website/src/__tests__/sonicRuntime.test.tsx` | Added reducer and journey regressions for Spotify-first onboarding, bypass, OAuth return, regions, playable clips, adaptive flow, analysis payloads, recommendations, and no duplicate late auth link. |
| `website/src/test/setup.ts` | Clears the migrated clip-count preference between tests. |

## Logic Transplanted From Frontend

- Session-backed Spotify OAuth URL generation and redirect-status refresh.
- Optional Spotify bypass before region selection.
- Region loading, selection, and clip-count persistence.
- Unique clip session keys.
- Exact requested-count validation for playable round-one clips.
- Adaptive second-round clip loading.
- One active audio element with rating and previous/next navigation.
- Clip-rating projection into adaptive questions and DNA analysis.
- Asked-question and covered-dimension memory.
- Selected-region propagation into analysis and snapshot persistence.
- Recommendation retrieval by cluster and region.
- Snapshot-before-playlist ordering.

No `frontend/` markup, styling, cards, page hierarchy, or screen composition was
copied into `website/`.

## Broken Connections Repaired

| Broken connection | Repair |
| --- | --- |
| Quiz bootstrapped before onboarding prerequisites | Bootstrap now waits at Spotify-first onboarding unless an OAuth-connected session resumes. |
| Spotify appeared only later in the journey | Recognition chapter now owns the first auth decision and exposes the visible bypass. |
| OAuth return did not advance the React runtime | Redirect query status is consumed, removed from the URL, and followed by status refresh and region loading. |
| Region was always hard-coded to `global_english` | Selected region is propagated to analysis, snapshot save, and recommendations. |
| Adaptive question and analysis payloads always sent empty clip ratings | Runtime now projects round-one and round-two ratings into both requests. |
| Website had no playable clip guard | Client rejects partial round-one batches and returns to region selection instead of showing blank or dead cards. |
| Website had no recommendation request | Results pipeline now loads cluster-and-region recommendations into the Worlds chapter. |
| Playlist generation could run without persisted genome data | Existing playlist action now follows identity analysis and snapshot persistence. |
| Later private-sync chapter could reopen Spotify OAuth | Chapter remains visually present but is status-only. |

## Verification Checklist

- [x] Audited all existing modified and untracked `website/` baseline files before edits.
- [x] Preserved the eight cinematic chapters and their order.
- [x] Added visible Spotify-first `Bring in Spotify` and `Continue without Spotify` paths.
- [x] Verified OAuth-return status refresh and redirect-query cleanup in runtime tests.
- [x] Verified exact playable-batch rejection in reducer tests.
- [x] Verified adaptive clips reach the text quiz without repeated setup loops.
- [x] Verified analysis receives selected region and clip ratings.
- [x] Verified recommendations render through the existing Worlds chapter.
- [x] Verified the later private-sync chapter does not expose a duplicate auth link.
- [x] Ran `npm test`: 46 tests passed across 6 files.
- [x] Ran `npm run lint`: exit code 0.
- [x] Ran `npm run build`: TypeScript and Vite production build completed.
- [x] Ran `git diff --check -- website docs`: no whitespace errors.
- [x] Verified local website server: `http://127.0.0.1:5173` returned HTTP 200 with the React root.
- [x] Verified backend health: `http://127.0.0.1:8010/health` returned `status: ok`.
- [x] Ran a live backend journey probe: 13 regions, 4 requested and 4 renderable round-one clips, 2 adaptive clips, adaptive question, analyzed archetype, saved snapshot, 6 recommendations, and a 10-track 30-minute playlist.

## Remaining Technical Debt

- Complete a human Spotify OAuth consent pass with a real account. Automated
  coverage verifies the callback state transition, but browser consent requires
  an account-holder session.
- Complete browser QA for real audio playback and cinematic interaction after
  the deferred browser/mockup phase resumes.
- The runtime provider remains large. A later refactor can extract pure journey
  helpers after launch without changing behavior.
- The live backend health response reports the optional OpenRouter question
  provider as unconfigured. The configured question service fallback is active.
- The working tree includes approved pre-migration cinematic-shell edits and
  unrelated documentation drafts. They were intentionally preserved.

