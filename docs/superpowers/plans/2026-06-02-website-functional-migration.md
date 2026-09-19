# SonicDNA Website Functional Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve the current cinematic `website/` while connecting Spotify-first optional onboarding, region selection, audio clips, adaptive analysis, recommendations, and playlist generation.

**Architecture:** Extend the existing typed API client and split React runtime with three focused domains: `journey`, `region`, and `clips`. Render new controls through the existing cinematic runtime-thread composition. Keep the existing chapter order and backend unchanged.

**Tech Stack:** React 19, TypeScript, Vite, Vitest, React Testing Library, FastAPI.

---

## File Structure

- Modify: `website/src/lib/api.ts` - typed region, clip, and recommendation methods.
- Modify: `website/src/runtime/types.ts` - journey, region, clip, and recommendation state.
- Modify: `website/src/runtime/sonicRuntimeReducer.ts` - pure state transitions and exact-count guards.
- Modify: `website/src/runtime/SonicRuntimeContext.ts` - narrow runtime actions.
- Modify: `website/src/runtime/SonicRuntimeProvider.tsx` - API orchestration, persistence, OAuth return refresh, and payload propagation.
- Modify: `website/src/components/cinematic/SceneRuntimeContent.tsx` - existing-shell Spotify choice, region, clips, quiz, recommendation, and playlist passage composition.
- Modify: `website/src/index.css` - minimal region and clip control styling using existing tokens.
- Modify: `website/src/__tests__/apiClient.test.ts` - typed transport coverage.
- Modify: `website/src/__tests__/sonicRuntime.test.tsx` - reducer and integrated journey coverage.

## Task 1: API Client Boundaries

- [ ] Add failing tests for `getRegions()`, `getRoundOneClips()`, `getAdaptiveClips()`, and `getRecommendations()`.
- [ ] Run `npm test -- src/__tests__/apiClient.test.ts` and confirm missing-method failures.
- [ ] Add typed API methods and response models.
- [ ] Run the API client test and confirm it passes.

## Task 2: Journey, Region, And Clip Reducer State

- [ ] Add failing reducer tests for explicit Spotify bypass, region loading and selection, round-one exact playable count, clip ratings, adaptive round progression, and quiz transition.
- [ ] Run `npm test -- src/__tests__/sonicRuntime.test.tsx` and confirm reducer action failures.
- [ ] Add `journey`, `region`, `clips`, and `recommendations` state plus reducer actions.
- [ ] Keep all existing runtime state behavior green.
- [ ] Run the runtime tests and confirm they pass.

## Task 3: Spotify-First Provider Integration

- [ ] Replace the delayed-Spotify test with failing tests that assert the first Recognition passage exposes Spotify connect and `Continue without Spotify`.
- [ ] Add a failing test that OAuth callback query status refreshes Spotify state and advances to region.
- [ ] Run the runtime tests and confirm expected failures.
- [ ] Stop quiz bootstrap from loading a question before onboarding finishes.
- [ ] Add `continueWithoutSpotify()`, redirect-query handling, and status refresh orchestration.
- [ ] Run the runtime tests and confirm Spotify-first tests pass.

## Task 4: Region And Audio Clip Integration

- [ ] Add failing tests for region loading after bypass, region selection, round-one loading, clip rendering, ratings, exact-count rejection, and adaptive clip fallback.
- [ ] Run the runtime tests and confirm expected failures.
- [ ] Add provider actions for region selection, clip-count persistence, clip loading, rating, previous/next clip navigation, and adaptive round loading.
- [ ] Add Recognition, Identity, and Listening Interview runtime passages using existing shell composition.
- [ ] Add minimal CSS for region choices and clip controls.
- [ ] Run runtime tests and confirm region and clip flow passes.

## Task 5: Clip-Aware Analysis And Recommendations

- [ ] Add failing integration tests that inspect request bodies for clip ratings and selected region.
- [ ] Add a failing test that recommendations load after analysis and before playlist generation.
- [ ] Run runtime tests and confirm expected failures.
- [ ] Pass real ratings into `/adaptive_question` and `/analyze_adaptive`.
- [ ] Save snapshots with the selected region.
- [ ] Load `/recommendations/{cluster}/{region}` after identity creation.
- [ ] Preserve the existing generated playlist CTA and Flow playback.
- [ ] Run runtime tests and confirm the full flow passes.

## Task 6: Verification

- [ ] Run `npm test`.
- [ ] Run `npm run build`.
- [ ] Run focused backend contract tests for clip count, adaptive question progression, Spotify OAuth state, session flow, and end-to-end flow.
- [ ] Start the backend and website dev servers if needed.
- [ ] Use the in-app browser to verify desktop and mobile flows, console cleanliness, clip rendering, and no overlap.
- [ ] Update the migration audit with modified-file rationale, transplanted logic, fixed connections, verification results, and remaining debt.
