# SonicDNA Website Migration Audit

Date: 2026-06-02

## Mission

Keep `website/` as the visual and interaction source of truth. Transplant only the
missing business logic and backend integration from `frontend/`. The only
intentional onboarding change is:

`Landing -> Spotify Connect or Continue without Spotify -> Region Selection -> Audio Clips -> Adaptive Quiz -> Analysis -> DNA Results -> Recommendations -> Playlist`

## Protected Website Baseline

The current uncommitted `website/` working tree is the approved baseline. It must
be preserved and extended in place. No existing UI, styling, motion, typography,
spacing, or cinematic chapter work should be replaced.

Baseline verification before migration:

- `npm test`: 39 tests passed in 6 files.
- Existing React shell: continuous cinematic scroll with eight chapters.
- Existing runtime: session bootstrap, Spotify status, adaptive text questions,
  result identity, snapshot save, playlist generation, playback, sharing,
  timeline loading, recovery copy, and feedback events.
- Existing API base URL in `website/.env`: `http://127.0.0.1:8010`.

## Existing Modified Website Files Audited

| File | Existing baseline work to preserve |
| --- | --- |
| `website/index.html` | Theme color and refined font loading. |
| `website/vite.config.ts` | Source maps and Vitest setup. |
| `website/src/test/setup.ts` | DOM cleanup, media mocks, and intersection observer test support. |
| `website/src/index.css` | Cinematic design tokens, atmospheric states, hero, chapter layout, runtime threads, buttons, playlist ribbon, recovery notice, closing frame, responsive behavior, and reduced-motion behavior. |
| `website/src/lib/api.ts` | Typed session, Spotify, adaptive quiz, snapshot, playlist, timeline, share, feedback, timeout, and base URL transport helpers. |
| `website/src/lib/performanceBudgets.ts` | Device-aware moving-atmosphere budget checks. |
| `website/src/motion/transitions.ts` | Refined reveal and tension timing. |
| `website/src/runtime/types.ts` | Split session, Spotify, quiz, playlist, playback, timeline, share, async, resilience, emotional-memory, and transition state. |
| `website/src/runtime/sonicRuntimeReducer.ts` | Emotional transitions, duplicate-question protection, playlist arrival state, playback phases, and safe recovery messages. |
| `website/src/runtime/SonicRuntimeProvider.tsx` | Session persistence, stale-session refresh, local fallback, adaptive text quiz, snapshot save, playlist generation, feedback events, and Spotify login URL generation. |
| `website/src/structure/cinematicChapters.ts` | Refined cinematic chapter copy. |
| `website/src/components/WordsPullUp.tsx` | Shared filmic easing and slower reveal. |
| `website/src/components/WordsPullUpMultiStyle.tsx` | Shared filmic easing, slower reveal, and left alignment. |
| `website/src/components/cinematic/AtmosphericMediaLayer.tsx` | Device-aware moving media, page visibility handling, and emotional atmosphere attributes. |
| `website/src/components/cinematic/ChapterNav.tsx` | Active chapter observation. |
| `website/src/components/cinematic/CinematicScaffold.tsx` | Hero, closing frame, runtime atmosphere wiring, recovery notice, and transition orchestrator. |
| `website/src/components/cinematic/RuntimeRecoveryNotice.tsx` | Animated calm recovery notice. |
| `website/src/components/cinematic/SceneRuntimeContent.tsx` | Existing partial session, text interview, delayed Spotify sync, playlist generation, playback, and sharing interactions. |
| `website/src/components/cinematic/TransitionOrchestrator.tsx` | New untracked transition wash and message layer. |
| `website/src/__tests__/apiClient.test.ts` | Typed transport and feedback event coverage. |
| `website/src/__tests__/atmosphericMediaLayer.test.tsx` | Environmental state coverage. |
| `website/src/__tests__/cinematicStructure.test.tsx` | Chapter, copy, and runtime shell coverage. |
| `website/src/__tests__/performanceBudgets.test.ts` | Constrained-device atmosphere coverage. |
| `website/src/__tests__/sonicRuntime.test.tsx` | Session recovery, adaptive text quiz, playlist, playback, and emotional continuity coverage. |
| `website/.env` | Local API URL. |
| `website/.env.production.example` | Production API URL placeholder. |

## Component And Screen Mapping

| Website component or scene | Frontend reference screen or handler | Migration decision |
| --- | --- | --- |
| `CinematicScaffold` and `cinematicChapters` | `.screen`, `showScreen()` | Preserve website shell. Add journey state without copying screen HTML. |
| Hero CTA | `heroScreen`, `startFlow()` | Preserve hero. Begin with Spotify-first onboarding. |
| Recognition runtime passage | No direct equivalent | Use as first onboarding entry without changing cinematic composition. |
| Existing `SpotifySync` runtime passage | `connectSpotify()`, `_loadSpotifyStatus()`, `_handleSpotifyRedirectStatus()`, `disconnectSpotify()` | Move connection opportunity to the first onboarding step. Add visible `Continue without Spotify`. Keep later sync chapter as status/reconnect reflection only. |
| New region runtime passage inside website cinematic shell | `regionScreen`, `selectRegion()`, `setClipCount()` | Transplant region loading, selection, and clip-count state only. Do not copy frontend markup or styling. |
| New audio clip runtime passage inside website cinematic shell | `clipScreen`, `gotoClipQuiz()`, `renderClip()`, `setRating()`, `prevClip()`, `nextClip()`, `submitRound1()` | Transplant clip request, playable filtering, rating, navigation, adaptive round, and audio lifecycle logic only. Use website styling primitives. |
| `ListeningInterview` | `questionsScreen`, `fetchAndRenderNextQuestion()`, `lockQuestionAndContinue()` | Keep website one-question-at-a-time UI. Feed real clip ratings and selected region into requests. |
| `IdentityInsight` | `renderResults(profileData)` | Preserve website identity rendering. Use real analyzed identity. |
| `EmotionalSession` | `generateGenomePlaylist()` | Preserve website CTA. Generate from saved snapshot and cluster. |
| `FlowPlayback` | Result track cards and playlist rendering | Preserve website passage UI and one-audio-element preview behavior. |
| Worlds chapter | Region-aware recommendations concept | Preserve chapter design. Connect recommendation data only if surfaced by current UI. |
| `MemoryShare` | `_autoSaveAndShowTimeline()`, `createShareLink()` | Preserve website memory UI. Keep share and timeline calls. |

## API Mapping

| Journey stage | Frontend reference call | Backend route | Website baseline | Required migration |
| --- | --- | --- | --- | --- |
| Session persistence | `POST /user/session` | `session_user()` | Working | Preserve. |
| Spotify status | `GET /spotify/status` | `spotify_status()` | Working but passive | Promote to first onboarding stage and refresh after OAuth redirect. |
| Spotify login | `GET /spotify/login` | `spotify_login()` | URL helper exists | Surface first. Preserve token-backed return URL. |
| Spotify disconnect | `POST /spotify/disconnect` | `spotify_disconnect()` | Typed API exists, no runtime action | Add action for later status chapter. |
| Regions | `GET /regions` or frontend constants | `get_regions()` | Missing | Add typed API method and runtime state. |
| Round-one clips | `GET /clips/round1?count=&session_key=` | `get_round1_clips()` | Missing | Add typed API method, exact-count validation, and playable filtering. |
| Adaptive clip round | `POST /clips/adaptive` | `get_adaptive_clip_round()` | Missing | Add typed API method and fallback to quiz if round two is unavailable. |
| Adaptive question | `POST /adaptive_question` | `get_adaptive_question()` | Working for text-only flow | Pass real clip ratings and preserve asked-question and covered-dimension memory. |
| DNA analysis | `POST /analyze_adaptive` | `analyze_adaptive()` | Working for text-only flow | Pass region and clip ratings so backend can blend clips, text, and Spotify taste. |
| Snapshot save | `POST /user/save_snapshot` | `save_snapshot()` | Working with hard-coded region | Save selected region. |
| Recommendations | `GET /recommendations/{cluster_id}/{region_key}` | `get_recommendations()` | Missing | Add typed API method for the results pipeline. |
| Playlist | `POST /playlist/session/{cluster_id}` | `generate_session_playlist()` | Working | Preserve; snapshot must already include selected region. |
| Timeline | `POST /user/timeline` | `get_timeline()` | Working | Preserve. |
| Share | `POST /share/create` | `create_share()` | Working | Preserve. |

## State Management Mapping

| Website baseline state | Frontend reference state | Status |
| --- | --- | --- |
| `session` | `_currentSessionToken`, `sonic_session_token` | Working and more robust in website. |
| `spotify` | `_loadSpotifyStatus()`, `_renderSpotifyStatus()` | Working state model; onboarding order is wrong. |
| `quiz.answers`, `askedQuestions`, `coveredDimensions` | `adaptiveAnswers`, `adaptiveAskedQuestions`, `adaptiveCoveredDims` | Working for text-only mode. Must receive clip context. |
| `quiz.identity`, `clusterId` | `profileData` | Working. |
| `playlist`, `playback` | generated playlist and result track rendering | Working in website cinematic form. |
| `timeline`, `share` | `_loadAndRenderTimeline()`, `createShareLink()` | Working partial integration. |
| Missing `journey` state | frontend screen progression | Missing. Add explicit stage transitions. |
| Missing `region` state | `selectedRegion`, `CLIP_COUNT` | Missing. Add selection, available regions, and persisted clip count. |
| Missing `clips` state | `round1Clips`, `round1Ratings`, `round2Clips`, `round2Ratings`, `clipSessionKey`, `currentClipIdx`, `isRound2` | Missing. Add playable clip batches, ratings, current index, round state, and loading/error state. |

## Working In Website

- Cinematic shell, typography, motion, atmospheric media, responsive rules, and chapter navigation.
- Anonymous session creation, stale session retry, local recovery session, and storage failure tolerance.
- Spotify login URL generation and background status lookup after session creation.
- Adaptive text-only question progression and exact duplicate guard.
- DNA analysis, identity state, snapshot save, playlist generation, playback, sharing, timeline, and feedback events.
- Calm user-facing error shaping.

## Broken In Website

- Spotify is intentionally hidden until the adaptive text interview completes. This conflicts with Spotify-first onboarding.
- The quiz starts during provider bootstrap before the user completes onboarding.
- Adaptive question and analysis requests always send `clipRatings: []`.
- Analysis and snapshot save always use `global_english`.
- No journey stage prevents users from reaching downstream controls before onboarding prerequisites.
- Spotify redirect status is not consumed by the React runtime, so status refresh after OAuth return is incomplete.

## Missing In Website

- Visible Spotify-first entry with `Continue without Spotify`.
- Region loading and region selection.
- Clip-count persistence.
- Round-one clip loading with requested-count validation.
- Audio clip rendering and rating.
- Adaptive clip round loading.
- Clip-aware adaptive-question requests.
- Clip-aware and region-aware analysis.
- Region-aware recommendation retrieval.
- Explicit journey transitions and cleanup for replay/restart.

## Frontend Logic To Transplant

Only transplant these behaviors:

- Session-backed Spotify OAuth URL and return handling.
- Region selection state and clip-count persistence.
- Unique clip session key generation.
- Round-one clip request and exact playable-count guard.
- Adaptive round-two clip request.
- Single active clip audio element lifecycle.
- Clip rating mutation, previous/next navigation, and payload projection.
- Adaptive question payload enrichment with ratings, asked questions, and covered dimensions.
- Region and rating propagation into `/analyze_adaptive`.
- Recommendation retrieval by cluster and region.

Do not transplant:

- `frontend/` HTML, CSS, cards, page headers, alerts, loading screens, visual hierarchy, or screen markup.
- Quick-mode bypass UI.
- Compatibility, leaderboard, email capture, legacy result cards, social share markup, or trial playlist UI unless a separate requirement asks for them.

## Route Trace

### Spotify-first onboarding

`Hero CTA -> journey.begin -> POST /user/session -> database session identity -> GET /spotify/status -> SpotifyConnect passage -> GET /spotify/login -> Spotify callback -> persisted Spotify connection -> return URL -> GET /spotify/status -> Region passage`

The explicit bypass is:

`SpotifyConnect passage -> Continue without Spotify -> Region passage`

### Region and audio clips

`Region choice -> runtime region state -> GET /clips/round1 -> clip rotation service -> playable clip batch -> clip passage -> rating state -> POST /clips/adaptive -> adaptive clip selector -> clip passage`

### Adaptive analysis

`Answer -> quiz state -> POST /adaptive_question with clip ratings -> adaptive question service -> next question or completion -> POST /analyze_adaptive with answers, ratings, region, session token -> genome engine -> Spotify taste blend when connected -> identity state -> POST /user/save_snapshot -> database`

### Results and playlist

`Identity state -> GET /recommendations/{cluster}/{region} -> recommendation engine -> results state -> playlist CTA -> POST /playlist/session/{cluster} -> snapshot lookup -> Spotify profile when connected -> playlist generator -> playlist state -> FlowPlayback`

## Recommended Minimal Migration Shape

Add three focused runtime domains without disturbing the cinematic shell:

1. `journey`: ordered onboarding and result stages.
2. `region`: available regions, selected key, and persisted clip count.
3. `clips`: clip session key, rounds, playable clips, ratings, index, and audio-selection state.

Extend the typed API client for regions, clips, and recommendations. Extend the
provider with narrow actions for Spotify-first continuation, region selection,
clip loading, clip rating, clip navigation, redirect refresh, and recommendation
loading. Render the new controls through existing website runtime-thread
composition and existing visual tokens.

## Pre-fix Verification Checklist

- [x] Audited all modified and untracked `website/` baseline files.
- [x] Ran current website test suite: 39 passing tests.
- [x] Traced backend contracts for session, Spotify, regions, clips, adaptive quiz, analysis, snapshot, recommendations, playlist, timeline, share, and feedback.
- [x] Traced functional reference handlers in `frontend/index.html`.
- [x] Identified logic-only transplant boundary.
- [ ] Add failing tests for Spotify-first onboarding and bypass.
- [ ] Add failing tests for region selection and persistence.
- [ ] Add failing tests for exact playable clip loading and rating projection.
- [ ] Add failing tests for clip-aware adaptive questions and analysis.
- [ ] Add failing tests for region-aware snapshot and recommendations.
- [ ] Apply minimal runtime fixes.
- [ ] Run unit, build, backend contract, and end-to-end verification.

## Remaining Technical Debt Before Fixes

- The website runtime provider is already large and should only receive tightly
  scoped additions. Extract pure journey helpers if additions become difficult to
  test.
- Backend clip APIs are robust enough to backfill playable batches, but the
  website must still reject partial client-visible batches.
- Existing website tests encode delayed Spotify sync and will need deliberate
  replacement because the approved onboarding requirement changed.
- The current graph report predates the latest uncommitted website runtime work,
  so source inspection remains authoritative for this migration.
