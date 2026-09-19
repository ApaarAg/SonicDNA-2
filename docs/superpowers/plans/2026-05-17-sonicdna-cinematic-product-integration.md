# SonicDNA Cinematic Product Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the production SonicDNA frontend as one continuous cinematic scroll experience with stateful emotional scenes connected to the real backend.

**Architecture:** Preserve the existing `/website` cinematic language while replacing the current four-section shell with a typed React architecture: shared cinematic primitives, a global emotional runtime, scene modules, typed API clients, and strict cross-scene verification gates. Scenes remain visually continuous but internally modular and backend-aware.

**Tech Stack:** React 19, TypeScript, Vite, Tailwind CSS, Framer Motion, lucide-react, Vitest, React Testing Library, FastAPI backend at `http://127.0.0.1:8000`.

---

## Required Phase Order

1. Global shell, typography, spacing, design tokens, motion primitives, and cinematic infrastructure.
2. Phase 1.5 structural rhythm: scene scaffolding, chapter pacing, transition continuity, silence zones, mobile choreography, navigation rhythm, spacing cadence, typography flow, and mocked emotional states only.
3. Split runtime architecture: session/backend state, emotional runtime state, scene runtime state, audio runtime state, and async/network state.
4. Backend integrations and typed API client.
5. Dedicated media orchestration layer: progressive loading, viewport-aware unloading, mobile fallbacks, GPU-conscious transitions, preview/audio arbitration, and atmospheric asset budgeting.
6. Motion refinement and scene transition polish.
7. Audio, clip behavior, and atmospheric polish.
8. Performance optimization, mobile choreography, and browser verification.

No scene may be implemented in visual isolation. Every scene review must check previous and next scene pacing, typography rhythm, transition continuity, mobile behavior, motion density, performance, and interaction payoff density. The product must prove emotional intelligence at regular intervals without surfacing backend machinery.

---

## File Structure

Create or modify these files:

- Modify: `website/package.json` - add test scripts and testing dependencies.
- Create: `website/src/test/setup.ts` - test environment setup.
- Modify: `website/src/index.css` - global cinematic tokens, typography, silence-zone classes, reduced-motion rules.
- Modify: `website/src/App.tsx` - assemble provider, cinematic shell, and approved scene order.
- Create: `website/src/runtime/types.ts` - shared runtime types for the five state domains.
- Create: `website/src/runtime/sessionBackendReducer.ts` - session token, profile, Spotify status, backend identity, and persistence references.
- Create: `website/src/runtime/emotionalRuntimeReducer.ts` - derived psychological pacing, tone, intensity, typography density, and interaction density.
- Create: `website/src/runtime/sceneRuntimeReducer.ts` - active chapter, transition phase, stillness zones, orientation, and section continuity.
- Create: `website/src/runtime/audioRuntimeReducer.ts` - silence permissions, clip focus, ambient layer, and playback arbitration state.
- Create: `website/src/runtime/asyncNetworkReducer.ts` - request lifecycle, optimistic locks, error recovery, and in-flight backend work.
- Create: `website/src/runtime/SonicRuntimeProvider.tsx` - composed runtime provider and narrow selector hooks.
- Create: `website/src/media/mediaOrchestrator.ts` - asset budgeting, progressive loading, viewport unloading, mobile fallbacks, and audio/preview arbitration.
- Create: `website/src/lib/api.ts` - typed backend API client.
- Create: `website/src/lib/emotionalCopy.ts` - copy helpers that translate system state into emotional language.
- Create: `website/src/lib/flowProjection.ts` - converts ordered playlist tracks into abstract emotional chapters.
- Create: `website/src/lib/orientation.ts` - invisible orientation labels and chapter movement language.
- Create: `website/src/motion/transitions.ts` - shared filmic easing and timing rules.
- Create: `website/src/motion/Reveal.tsx` - reusable reveal primitive.
- Create: `website/src/motion/SceneBoundary.tsx` - chapter threshold and transition wrapper.
- Create: `website/src/components/cinematic/ChapterNav.tsx` - minimal chapter navigation.
- Create: `website/src/components/cinematic/CinematicButton.tsx` - editorial CTA primitive.
- Create: `website/src/components/cinematic/EditorialLabel.tsx` - small uppercase label.
- Create: `website/src/components/cinematic/MediaScene.tsx` - atmospheric media frame with fallbacks.
- Create: `website/src/components/audio/ClipPlayer.tsx` - restrained single-source clip playback.
- Create: `website/src/components/audio/AudioBoundary.tsx` - prevents overlapping audio and enforces silence rules.
- Create: `website/src/components/scenes/RecognitionScene.tsx`
- Create: `website/src/components/scenes/IdentityScene.tsx`
- Create: `website/src/components/scenes/ListeningInterviewScene.tsx`
- Create: `website/src/components/scenes/PrivateSyncScene.tsx`
- Create: `website/src/components/scenes/EmotionalSessionScene.tsx`
- Create: `website/src/components/scenes/FlowScene.tsx`
- Create: `website/src/components/scenes/WorldsScene.tsx`
- Create: `website/src/components/scenes/MemoryScene.tsx`
- Create: `website/src/__tests__/runtimeReducers.test.ts`
- Create: `website/src/__tests__/mediaOrchestrator.test.ts`
- Create: `website/src/__tests__/flowProjection.test.ts`
- Create: `website/src/__tests__/api.test.ts`
- Create: `website/src/__tests__/App.sceneOrder.test.tsx`
- Create: `website/src/__tests__/ClipPlayer.test.tsx`

---

### Task 1: Test Harness

**Files:**
- Modify: `website/package.json`
- Create: `website/src/test/setup.ts`

- [ ] **Step 1: Install test dependencies**

Run:

```powershell
npm install -D vitest jsdom @testing-library/react @testing-library/jest-dom
```

Expected: package install succeeds and `website/package-lock.json` updates.

- [ ] **Step 2: Add test scripts to `website/package.json`**

Add these scripts:

```json
{
  "test": "vitest run --environment jsdom --setupFiles ./src/test/setup.ts",
  "test:watch": "vitest --environment jsdom --setupFiles ./src/test/setup.ts"
}
```

- [ ] **Step 3: Create `website/src/test/setup.ts`**

```ts
import '@testing-library/jest-dom/vitest';
```

- [ ] **Step 4: Run test command to confirm harness starts**

Run:

```powershell
npm test -- --passWithNoTests
```

Expected: Vitest exits successfully with no tests found.

- [ ] **Step 5: Commit**

```powershell
git add website/package.json website/package-lock.json website/src/test/setup.ts
git commit -m "test: add frontend test harness"
```

---

### Task 2: Motion And Cinematic Primitives

**Files:**
- Create: `website/src/motion/transitions.ts`
- Create: `website/src/motion/Reveal.tsx`
- Create: `website/src/motion/SceneBoundary.tsx`
- Modify: `website/src/index.css`
- Test: `website/src/__tests__/motionPrimitives.test.tsx`

- [ ] **Step 1: Write failing tests**

Create `website/src/__tests__/motionPrimitives.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import { filmEase, motionTempoDurations } from '../motion/transitions';
import Reveal from '../motion/Reveal';
import SceneBoundary from '../motion/SceneBoundary';

describe('cinematic motion primitives', () => {
  test('exports restrained filmic timing tokens', () => {
    expect(filmEase).toEqual([0.16, 1, 0.3, 1]);
    expect(motionTempoDurations.slow).toBeGreaterThan(motionTempoDurations.medium);
    expect(motionTempoDurations.still).toBeGreaterThan(motionTempoDurations.slow);
  });

  test('Reveal renders content without requiring animation to understand it', () => {
    render(<Reveal><p>Every listener leaves a pattern.</p></Reveal>);
    expect(screen.getByText('Every listener leaves a pattern.')).toBeInTheDocument();
  });

  test('SceneBoundary marks chapters without page routing', () => {
    render(<SceneBoundary id="identity" label="Identity"><h2>Sonic fingerprint</h2></SceneBoundary>);
    expect(screen.getByTestId('scene-identity')).toHaveAttribute('id', 'identity');
    expect(screen.getByText('Identity')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run failing test**

Run:

```powershell
npm test -- src/__tests__/motionPrimitives.test.tsx
```

Expected: fails because `../motion/transitions`, `Reveal`, and `SceneBoundary` do not exist.

- [ ] **Step 3: Implement `website/src/motion/transitions.ts`**

```ts
export const filmEase = [0.16, 1, 0.3, 1] as const;

export const motionTempoDurations = {
  medium: 0.7,
  slow: 1.1,
  still: 1.6,
} as const;

export const revealTransition = {
  duration: motionTempoDurations.slow,
  ease: filmEase,
};

export const quietTransition = {
  duration: motionTempoDurations.still,
  ease: filmEase,
};
```

- [ ] **Step 4: Implement `website/src/motion/Reveal.tsx`**

```tsx
import { motion } from 'framer-motion';
import type { ReactNode } from 'react';
import { revealTransition } from './transitions';

type RevealProps = {
  children: ReactNode;
  className?: string;
  delay?: number;
};

export default function Reveal({ children, className = '', delay = 0 }: RevealProps) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y: 24, filter: 'blur(10px)' }}
      whileInView={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
      viewport={{ once: true, margin: '-80px' }}
      transition={{ ...revealTransition, delay }}
    >
      {children}
    </motion.div>
  );
}
```

- [ ] **Step 5: Implement `website/src/motion/SceneBoundary.tsx`**

```tsx
import type { ReactNode } from 'react';
import Reveal from './Reveal';

type SceneBoundaryProps = {
  id: string;
  label: string;
  children: ReactNode;
  className?: string;
  silence?: boolean;
};

export default function SceneBoundary({ id, label, children, className = '', silence = false }: SceneBoundaryProps) {
  return (
    <section
      id={id}
      data-testid={`scene-${id}`}
      data-silence={silence ? 'true' : 'false'}
      className={`scene-boundary ${silence ? 'interaction-silence' : ''} ${className}`}
    >
      <Reveal className="scene-label">{label}</Reveal>
      {children}
    </section>
  );
}
```

- [ ] **Step 6: Extend `website/src/index.css`**

Add:

```css
:root {
  --sonic-black: #000000;
  --sonic-panel: #0f0f0f;
  --sonic-ivory: #e1e0cc;
  --sonic-muted: rgba(225, 224, 204, 0.42);
  --sonic-quiet: rgba(225, 224, 204, 0.16);
  --sonic-max: 1200px;
}

.scene-boundary {
  position: relative;
  max-width: var(--sonic-max);
  margin: 0 auto;
  padding: 8rem 1.5rem;
}

.scene-label {
  color: var(--sonic-muted);
  font-size: 0.68rem;
  letter-spacing: 0.3em;
  text-transform: uppercase;
  margin-bottom: 3rem;
}

.interaction-silence {
  min-height: 64vh;
}

@media (max-width: 768px) {
  .scene-boundary {
    padding: 5rem 1rem;
  }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.001ms !important;
    animation-iteration-count: 1 !important;
    scroll-behavior: auto !important;
    transition-duration: 0.001ms !important;
  }
}
```

- [ ] **Step 7: Run test**

Run:

```powershell
npm test -- src/__tests__/motionPrimitives.test.tsx
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```powershell
git add website/src/motion website/src/index.css website/src/__tests__/motionPrimitives.test.tsx
git commit -m "feat: add cinematic motion primitives"
```

---

### Task 3: Phase 1.5 Cinematic Structural Rhythm

**Files:**
- Modify: `website/eslint.config.js`
- Modify: `website/src/App.tsx`
- Modify: `website/src/index.css`
- Modify: `website/src/motion/transitions.ts`
- Modify: `website/src/motion/SceneBoundary.tsx`
- Create: `website/src/components/cinematic/CinematicScaffold.tsx`
- Create: `website/src/components/cinematic/AtmosphericMediaLayer.tsx`
- Create: `website/src/components/cinematic/ChapterNav.tsx`
- Create: `website/src/structure/cinematicChapters.ts`
- Create: `website/src/lib/performanceBudgets.ts`
- Create: `website/src/__tests__/cinematicStructure.test.tsx`
- Create: `website/src/__tests__/atmosphericMediaLayer.test.tsx`
- Create: `website/src/__tests__/performanceBudgets.test.ts`

**Boundary:** This is a structural rehearsal phase only. Do not integrate backend APIs, persistent runtime logic, playlist generation, Spotify sync, audio orchestration, real emotional inference, or media orchestration. Mocked emotional states are allowed only as non-persistent design scaffolding.

- [ ] **Step 1: Fix repository hygiene**

Archived prototype folders must not break linting. Exclude `website/new website/**` and `website/new_website/**` from ESLint, or move them into an explicit archive location outside the production lint surface.

- [ ] **Step 2: Add structural rhythm tests**

Write tests proving:

- The approved chapter order is Recognition, Identity, Listening Interview, Private Sync, Emotional Session, Flow, Worlds, Memory.
- Chapters use mocked emotional states only.
- Rendered UI avoids dashboard/backend/topology/metric language.
- Silence zones and mobile choreography are first-class attributes.
- Motion primitives include stillness, asymmetry, interruption, delayed response, tension, and silence.

- [ ] **Step 3: Add explicit cinematic performance budgets**

Define tested budgets for target FPS, max concurrent animated layers, max simultaneous media surfaces, blur/filter limits, mobile fallback threshold, and reduced-motion degradation rules.

- [ ] **Step 4: Implement cinematic scaffold**

Create a continuous single-scroll scaffold with sparse chapter navigation, editorial typography, asymmetric scene rhythm, silence zones, and mocked emotional state labels. Keep interaction density low and do not create dashboard cards or control panels.

- [ ] **Step 5: Restore restrained atmospheric media**

Restore the original `/website` cinematic moving media language as environmental cinematography. Use a single fixed moving surface on desktop, static fallback on mobile/reduced motion, no audio, no stacked video layers, and no generic hero wallpaper behavior. The moving layer must support silence zones and obey the explicit performance budgets.

- [ ] **Step 6: Verify Phase 1.5**

Run:

```powershell
npm test -- src/__tests__/cinematicStructure.test.tsx src/__tests__/atmosphericMediaLayer.test.tsx src/__tests__/performanceBudgets.test.ts src/__tests__/motionPrimitives.test.tsx
npm run build
npm run lint
```

Expected: all tests, build, and lint pass.

---

### Task 4: Split Runtime Architecture

**Files:**
- Create: `website/src/runtime/types.ts`
- Create: `website/src/runtime/sessionBackendReducer.ts`
- Create: `website/src/runtime/emotionalRuntimeReducer.ts`
- Create: `website/src/runtime/sceneRuntimeReducer.ts`
- Create: `website/src/runtime/audioRuntimeReducer.ts`
- Create: `website/src/runtime/asyncNetworkReducer.ts`
- Create: `website/src/runtime/SonicRuntimeProvider.tsx`
- Test: `website/src/__tests__/runtimeReducers.test.ts`

**Architectural rule:** Do not create a monolithic `SonicSessionReducer`. Runtime state is split into five domains, and the provider composes them through narrow hooks/selectors. Cross-domain behavior flows through explicit actions and derived runtime helpers, not one catch-all object.

- [ ] **Step 1: Write failing split-runtime tests**

Create `website/src/__tests__/runtimeReducers.test.ts` with coverage for:

```ts
import { describe, expect, test } from 'vitest';
import { initialSessionBackendState, sessionBackendReducer } from '../runtime/sessionBackendReducer';
import { deriveEmotionalRuntime, emotionalRuntimeReducer, initialEmotionalRuntimeState } from '../runtime/emotionalRuntimeReducer';
import { initialSceneRuntimeState, sceneRuntimeReducer } from '../runtime/sceneRuntimeReducer';
import { audioRuntimeReducer, initialAudioRuntimeState } from '../runtime/audioRuntimeReducer';
import { asyncNetworkReducer, initialAsyncNetworkState } from '../runtime/asyncNetworkReducer';

describe('split SonicDNA runtime architecture', () => {
  test('keeps backend session state separate from emotional runtime behavior', () => {
    const session = sessionBackendReducer(initialSessionBackendState, {
      type: 'session/created',
      payload: { sessionToken: 'abc123', profileCode: 'SD-ABC123' },
    });

    expect(session.sessionToken).toBe('abc123');
    expect(JSON.stringify(session)).not.toContain('motionTempo');
  });

  test('material emotional inference changes pacing and interaction density', () => {
    const emotional = emotionalRuntimeReducer(initialEmotionalRuntimeState, {
      type: 'emotional/inferenceUpdated',
      payload: { intensity: 0.76, intimacy: 0.68, explorationReadiness: 0.42 },
    });

    expect(emotional.motionTempo).toBe('slow');
    expect(emotional.typographyDensity).toBe('spare');
    expect(emotional.interactionDensity).toBe('low');
  });

  test('scene runtime owns chapter transitions and stillness zones', () => {
    const scene = sceneRuntimeReducer(initialSceneRuntimeState, {
      type: 'scene/entered',
      payload: { chapter: 'flow', transition: 'dissolve', stillness: true },
    });

    expect(scene.activeChapter).toBe('flow');
    expect(scene.stillnessZone).toBe(true);
  });

  test('audio runtime enforces silence and preview arbitration separately', () => {
    const audio = audioRuntimeReducer(initialAudioRuntimeState, {
      type: 'audio/previewRequested',
      payload: { clipId: 'anchor-memory', scene: 'identity' },
    });

    expect(audio.activePreviewId).toBe('anchor-memory');
    expect(audio.competingSources).toHaveLength(0);
  });

  test('async runtime tracks network work without leaking backend machinery into UI state', () => {
    const network = asyncNetworkReducer(initialAsyncNetworkState, {
      type: 'request/started',
      payload: { key: 'playlist.generate' },
    });

    expect(network.inFlight['playlist.generate']).toBe(true);
    expect(JSON.stringify(network)).not.toContain('topologyScore');
  });

  test('derived emotional runtime can read session evidence without mutating session state', () => {
    const emotional = deriveEmotionalRuntime({
      spotifyReady: true,
      clipAverage: 4.8,
      explorationTone: 'far',
      currentChapter: 'worlds',
    });

    expect(emotional.explorationReadiness).toBeGreaterThan(0.7);
    expect(emotional.audioPermission).toBe('punctuation');
  });
});
```

- [ ] **Step 2: Run failing test**

```powershell
npm test -- src/__tests__/runtimeReducers.test.ts
```

Expected: fails because runtime files do not exist.

- [ ] **Step 3: Implement `website/src/runtime/types.ts`**

Define narrow types for:

- `SessionBackendState`: session token, profile code, Spotify connection state, backend identity references, playlist IDs, share IDs.
- `EmotionalRuntimeState`: dominant tone, intensity, intimacy, exploration readiness, interaction density, typography density, motion tempo, audio permission, last emotional beat.
- `SceneRuntimeState`: active chapter, previous chapter, chapter progress, transition phase, stillness zone, invisible orientation copy.
- `AudioRuntimeState`: muted state, active preview, ambient layer permission, competing sources, last punctuation timestamp.
- `AsyncNetworkState`: in-flight requests, recoverable errors, last successful request, blocked interaction keys.

- [ ] **Step 4: Implement one reducer per state domain**

Each reducer must be small and domain-owned. No reducer may store all five domains. Emotional runtime derivation may read summarized evidence from other domains, but it must return emotional behavior controls rather than raw backend facts.

- [ ] **Step 5: Implement `SonicRuntimeProvider` composition**

The provider composes the five reducers, persists only safe session/backend and scene continuity state, and exposes focused hooks such as:

```ts
useSessionBackend()
useEmotionalRuntime()
useSceneRuntime()
useAudioRuntime()
useAsyncNetwork()
```

Avoid a single catch-all `useSonicRuntime` selector. Interactive scenes should request only the domain they need.

- [ ] **Step 6: Verify split runtime tests**

```powershell
npm test -- src/__tests__/runtimeReducers.test.ts
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```powershell
git add website/src/runtime website/src/__tests__/runtimeReducers.test.ts
git commit -m "feat: add split SonicDNA runtime architecture"
```
---

### Task 4: Typed API Client

**Files:**
- Create: `website/src/lib/api.ts`
- Test: `website/src/__tests__/api.test.ts`

- [ ] **Step 1: Write failing API tests**

Create `website/src/__tests__/api.test.ts`:

```ts
import { afterEach, describe, expect, test, vi } from 'vitest';
import { createSonicApi } from '../lib/api';

describe('SonicDNA API client', () => {
  afterEach(() => vi.restoreAllMocks());

  test('creates a session user through /user/session', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ session_token: 'tok', profile_code: 'SD-TOK' }) });
    const api = createSonicApi({ baseUrl: 'http://api.test', fetcher: fetchMock });

    const result = await api.createSession('Apar');

    expect(fetchMock).toHaveBeenCalledWith('http://api.test/user/session', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ display_name: 'Apar' }),
    }));
    expect(result.session_token).toBe('tok');
  });

  test('builds Spotify login URL without fetching', () => {
    const api = createSonicApi({ baseUrl: 'http://api.test' });
    expect(api.spotifyLoginUrl('tok', 'http://localhost:5173')).toBe('http://api.test/spotify/login?session_token=tok&return_to=http%3A%2F%2Flocalhost%3A5173');
  });

  test('throws readable error envelopes', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 503, json: async () => ({ detail: 'Spotify unavailable' }) });
    const api = createSonicApi({ baseUrl: 'http://api.test', fetcher: fetchMock });

    await expect(api.getSpotifyStatus('tok')).rejects.toThrow('Spotify unavailable');
  });
});
```

- [ ] **Step 2: Run failing test**

Run:

```powershell
npm test -- src/__tests__/api.test.ts
```

Expected: fails because `../lib/api` does not exist.

- [ ] **Step 3: Implement `website/src/lib/api.ts`**

```ts
type Fetcher = typeof fetch;

type ApiOptions = {
  baseUrl?: string;
  fetcher?: Fetcher;
};

async function readJson<T>(response: Response): Promise<T> {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof payload.detail === 'string' ? payload.detail : `Request failed with ${response.status}`;
    throw new Error(detail);
  }
  return payload as T;
}

export function createSonicApi(options: ApiOptions = {}) {
  const baseUrl = (options.baseUrl ?? import.meta.env.VITE_SONIC_API_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '');
  const fetcher = options.fetcher ?? fetch;

  const post = async <T>(path: string, body: unknown) => readJson<T>(await fetcher(`${baseUrl}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }));

  const get = async <T>(path: string) => readJson<T>(await fetcher(`${baseUrl}${path}`));

  return {
    createSession(displayName?: string) {
      return post<{ session_token: string; profile_code?: string }>('/user/session', { display_name: displayName });
    },
    getSpotifyStatus(sessionToken: string) {
      return get(`/spotify/status?session_token=${encodeURIComponent(sessionToken)}`);
    },
    spotifyLoginUrl(sessionToken: string, returnTo: string) {
      return `${baseUrl}/spotify/login?session_token=${encodeURIComponent(sessionToken)}&return_to=${encodeURIComponent(returnTo)}`;
    },
    disconnectSpotify(sessionToken: string) {
      return post('/spotify/disconnect', { session_token: sessionToken });
    },
    getRoundOneClips(sessionKey: string, count = 6) {
      return get(`/clips/round1?count=${count}&session_key=${encodeURIComponent(sessionKey)}`);
    },
    getAdaptiveClips(existingRatings: unknown[], roundNumber: number, sessionKey: string) {
      return post('/clips/adaptive', { existing_ratings: existingRatings, round_number: roundNumber, session_key: sessionKey });
    },
    getAdaptiveQuestion(payload: { previous_answers: string[]; clip_ratings: unknown[]; covered_dimensions: string[]; asked_questions: string[] }) {
      return post('/adaptive_question', payload);
    },
    analyzeAdaptive(payload: { answers: string[]; clip_ratings: unknown[]; region: string; session_token?: string | null }) {
      return post('/analyze_adaptive', payload);
    },
    saveSnapshot(payload: { session_token?: string | null; result: unknown; region: string }) {
      return post('/user/save_snapshot', payload);
    },
    generateTrialPlaylist(payload: unknown) {
      return post('/playlist/trial', payload);
    },
    generateSessionPlaylist(clusterId: number, payload: unknown, query = '') {
      return post(`/playlist/session/${clusterId}${query}`, payload);
    },
    getRegions() {
      return get('/regions');
    },
    getRecommendations(clusterId: number, regionKey: string, limit = 5) {
      return get(`/recommendations/${clusterId}/${regionKey}?limit=${limit}`);
    },
    createShare(payload: { session_token?: string | null; snapshot_id?: string }) {
      return post('/share/create', payload);
    },
    getShare(shareCode: string) {
      return get(`/share/${shareCode}`);
    },
    compareCompatibility(payload: { session_token?: string | null; share_code?: string; display_name?: string }) {
      return post('/compatibility/compare', payload);
    },
  };
}

export const sonicApi = createSonicApi();
```

- [ ] **Step 4: Run API tests**

Run:

```powershell
npm test -- src/__tests__/api.test.ts
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add website/src/lib/api.ts website/src/__tests__/api.test.ts
git commit -m "feat: add typed SonicDNA API client"
```

---

### Task 5: Emotional Copy, Flow Projection, And Invisible Orientation

**Files:**
- Create: `website/src/lib/emotionalCopy.ts`
- Create: `website/src/lib/flowProjection.ts`
- Create: `website/src/lib/orientation.ts`
- Test: `website/src/__tests__/flowProjection.test.ts`

- [ ] **Step 1: Write failing projection tests**

Create `website/src/__tests__/flowProjection.test.ts`:

```ts
import { describe, expect, test } from 'vitest';
import { describeIdentity, describeSessionIntent } from '../lib/emotionalCopy';
import { projectFlowChapters } from '../lib/flowProjection';
import { orientationForScene } from '../lib/orientation';
import type { SonicTrack } from '../state/types';

const tracks: SonicTrack[] = [
  { name: 'Low Light', artist: 'A', energy: 0.2, valence: 0.3, source: 'library' },
  { name: 'Static Bloom', artist: 'B', energy: 0.55, valence: 0.45, source: 'discovery' },
  { name: 'Afterimage', artist: 'C', energy: 0.38, valence: 0.62, source: 'exploration' },
];

describe('emotional projections', () => {
  test('flow projection creates abstract chapters without telemetry labels', () => {
    const chapters = projectFlowChapters(tracks);
    const serialized = JSON.stringify(chapters).toLowerCase();

    expect(chapters).toHaveLength(3);
    expect(chapters[0].label).toBe('Threshold');
    expect(serialized).not.toContain('score');
    expect(serialized).not.toContain('metric');
    expect(serialized).not.toContain('graph');
  });

  test('identity copy resolves genome into emotional language', () => {
    expect(describeIdentity({ energy: -0.8, valence: -0.5, acousticness: 0.7 })).toContain('quiet');
  });

  test('session intent copy stays concrete', () => {
    expect(describeSessionIntent('night_drive')).toContain('night');
  });

  test('orientation gives direction without exposing topology', () => {
    expect(orientationForScene('worlds', 'far')).toContain('farther');
    expect(orientationForScene('worlds', 'far')).not.toContain('node');
  });
});
```

- [ ] **Step 2: Run failing tests**

Run:

```powershell
npm test -- src/__tests__/flowProjection.test.ts
```

Expected: fails because projection modules do not exist.

- [ ] **Step 3: Implement `website/src/lib/flowProjection.ts`**

```ts
import type { SonicTrack } from '../state/types';

export type FlowChapter = {
  label: 'Threshold' | 'Rise' | 'Afterglow';
  description: string;
  tracks: SonicTrack[];
};

export function projectFlowChapters(tracks: SonicTrack[]): FlowChapter[] {
  const third = Math.max(1, Math.ceil(tracks.length / 3));
  const groups = [tracks.slice(0, third), tracks.slice(third, third * 2), tracks.slice(third * 2)];

  return [
    { label: 'Threshold', description: 'Where the session opens and finds its first emotional anchor.', tracks: groups[0] ?? [] },
    { label: 'Rise', description: 'Where contrast enters without breaking the thread.', tracks: groups[1] ?? [] },
    { label: 'Afterglow', description: 'Where the movement settles into residue and release.', tracks: groups[2] ?? [] },
  ].filter((chapter) => chapter.tracks.length > 0);
}
```

- [ ] **Step 4: Implement `website/src/lib/emotionalCopy.ts`**

```ts
export function describeIdentity(genome: Record<string, number> = {}) {
  const energy = Number(genome.energy ?? 0);
  const valence = Number(genome.valence ?? 0);
  const acousticness = Number(genome.acousticness ?? 0);

  if (energy < -0.4 && acousticness > 0.35) return 'A quiet listener drawn to texture, memory, and songs that leave room around the feeling.';
  if (energy > 0.5 && valence > 0.2) return 'A kinetic listener pulled toward lift, motion, and songs that turn emotion into momentum.';
  if (valence < -0.35) return 'A reflective listener who returns to tension, ache, and the strange comfort of unresolved songs.';
  return 'A listener with a shifting center: part instinct, part memory, part atmosphere.';
}

export function describeSessionIntent(mode: string) {
  const normalized = mode.replace(/_/g, ' ');
  const lines: Record<string, string> = {
    night_drive: 'A night session built for movement, shadow, and a slow emotional horizon.',
    healing: 'A healing session that starts softly and lets warmth return without forcing it.',
    confidence: 'A confidence session that builds from internal pulse to visible momentum.',
    heartbreak: 'A heartbreak session that descends, lingers, and finds a quiet release.',
    focus: 'A focus session that keeps the room steady and the edges soft.',
  };
  return lines[mode] ?? `A ${normalized} session shaped around emotional continuity.`;
}
```

- [ ] **Step 5: Implement `website/src/lib/orientation.ts`**

```ts
import type { ExplorationTone } from '../state/types';

export function orientationForScene(scene: string, explorationTone: ExplorationTone = 'open') {
  if (scene === 'worlds') {
    if (explorationTone === 'far') return 'Moving farther from the familiar anchor, without losing the thread.';
    if (explorationTone === 'close') return 'Staying close to the emotional center, widening only at the edges.';
    return 'Crossing into adjacent territory through a familiar emotional doorway.';
  }
  if (scene === 'flow') return 'The session is moving from threshold toward release.';
  if (scene === 'memory') return 'A previous version of the listener is resurfacing.';
  return 'The chapter is opening slowly.';
}
```

- [ ] **Step 6: Run tests**

Run:

```powershell
npm test -- src/__tests__/flowProjection.test.ts
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```powershell
git add website/src/lib website/src/__tests__/flowProjection.test.ts
git commit -m "feat: add emotional projection helpers"
```

---

### Task 6: Scene Scaffolding And Approved Order

**Files:**
- Modify: `website/src/App.tsx`
- Create: all files under `website/src/components/scenes/`
- Create: `website/src/components/cinematic/ChapterNav.tsx`
- Create: `website/src/components/cinematic/CinematicButton.tsx`
- Create: `website/src/components/cinematic/EditorialLabel.tsx`
- Create: `website/src/components/cinematic/MediaScene.tsx`
- Test: `website/src/__tests__/App.sceneOrder.test.tsx`

- [ ] **Step 1: Write failing scene order test**

Create `website/src/__tests__/App.sceneOrder.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import App from '../App';

describe('SonicDNA cinematic journey', () => {
  test('renders approved scene order as one continuous experience', () => {
    render(<App />);
    const scenes = screen.getAllByTestId(/scene-/).map((node) => node.id);

    expect(scenes).toEqual([
      'recognition',
      'identity',
      'listening-interview',
      'private-sync',
      'emotional-session',
      'flow',
      'worlds',
      'memory',
    ]);
  });

  test('does not render dashboard language', () => {
    render(<App />);
    const page = document.body.textContent?.toLowerCase() ?? '';
    expect(page).not.toContain('dashboard');
    expect(page).not.toContain('kpi');
    expect(page).not.toContain('score:');
  });
});
```

- [ ] **Step 2: Run failing test**

Run:

```powershell
npm test -- src/__tests__/App.sceneOrder.test.tsx
```

Expected: fails because current app renders old sections and no scene boundaries.

- [ ] **Step 3: Create cinematic primitives**

Create `website/src/components/cinematic/EditorialLabel.tsx`:

```tsx
export default function EditorialLabel({ children }: { children: React.ReactNode }) {
  return <p className="text-primary/40 text-[10px] sm:text-xs tracking-[0.3em] uppercase">{children}</p>;
}
```

Create `website/src/components/cinematic/CinematicButton.tsx`:

```tsx
import { ArrowRight } from 'lucide-react';

type CinematicButtonProps = {
  children: React.ReactNode;
  onClick?: () => void;
  href?: string;
};

export default function CinematicButton({ children, onClick, href }: CinematicButtonProps) {
  const className = 'group inline-flex items-center gap-2 hover:gap-3.5 bg-primary rounded-full pl-6 pr-1.5 py-1.5 transition-all duration-500 ease-out w-fit text-black';
  const content = (
    <>
      <span className="font-medium text-sm sm:text-base tracking-[-0.01em]">{children}</span>
      <span className="bg-black rounded-full w-9 h-9 sm:w-10 sm:h-10 flex items-center justify-center group-hover:scale-110 transition-transform duration-500 ease-out">
        <ArrowRight className="w-4 h-4 sm:w-5 sm:h-5 text-primary" />
      </span>
    </>
  );
  return href ? <a className={className} href={href}>{content}</a> : <button className={className} onClick={onClick}>{content}</button>;
}
```

Create `website/src/components/cinematic/MediaScene.tsx`:

```tsx
type MediaSceneProps = {
  children: React.ReactNode;
  className?: string;
};

export default function MediaScene({ children, className = '' }: MediaSceneProps) {
  return (
    <div className={`relative overflow-hidden rounded-2xl md:rounded-[2rem] bg-[#0f0f0f] ${className}`}>
      <div className="absolute inset-0 bg-noise opacity-[0.08] pointer-events-none" />
      <div className="relative z-10">{children}</div>
    </div>
  );
}
```

Create `website/src/components/cinematic/ChapterNav.tsx`:

```tsx
const chapters = [
  ['recognition', 'Recognition'],
  ['identity', 'Identity'],
  ['listening-interview', 'Interview'],
  ['private-sync', 'Sync'],
  ['emotional-session', 'Session'],
  ['flow', 'Flow'],
  ['worlds', 'Worlds'],
  ['memory', 'Memory'],
] as const;

export default function ChapterNav() {
  return (
    <nav className="fixed top-0 left-1/2 -translate-x-1/2 z-40 bg-black rounded-b-2xl md:rounded-b-3xl px-4 py-2 md:px-8">
      <ul className="flex items-center gap-3 sm:gap-6 md:gap-10">
        {chapters.map(([id, label]) => (
          <li key={id}>
            <a href={`#${id}`} className="text-[10px] sm:text-xs text-primary/60 hover:text-primary transition-colors duration-500 whitespace-nowrap">
              {label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
```

- [ ] **Step 4: Create initial scene components**

Each scene must use `SceneBoundary`. Start with static emotional content and no backend calls.

Example for `website/src/components/scenes/RecognitionScene.tsx`:

```tsx
import CinematicButton from '../cinematic/CinematicButton';
import SceneBoundary from '../../motion/SceneBoundary';
import WordsPullUp from '../WordsPullUp';

export default function RecognitionScene() {
  return (
    <SceneBoundary id="recognition" label="Recognition" className="min-h-screen max-w-none p-4 md:p-6">
      <div className="relative min-h-[calc(100vh-2rem)] rounded-2xl md:rounded-[2rem] overflow-hidden bg-black">
        <div className="absolute inset-0 bg-[url('/src/assets/hero.png')] bg-cover bg-center opacity-60 scale-105" />
        <div className="absolute inset-0 bg-gradient-to-b from-black/30 via-black/20 to-black/80" />
        <div className="absolute inset-x-0 bottom-0 z-10 p-6 md:p-10 grid grid-cols-12 gap-4 items-end">
          <h1 className="col-span-12 lg:col-span-8 text-[18vw] md:text-[14vw] font-medium leading-[0.85] tracking-[-0.06em] text-primary">
            <WordsPullUp text="SonicDNA" showAsterisk />
          </h1>
          <div className="col-span-12 lg:col-span-4 flex flex-col gap-5">
            <p className="text-primary/60 text-sm md:text-base max-w-sm leading-[1.45]">
              Your listening history is a map of who you are. SonicDNA listens for the emotional patterns underneath it.
            </p>
            <p className="text-primary/35 text-xs leading-relaxed max-w-xs">
              What song keeps finding you when the room gets quiet?
            </p>
            <CinematicButton href="#listening-interview">Begin listening</CinematicButton>
          </div>
        </div>
      </div>
    </SceneBoundary>
  );
}
```

For the remaining scene files, use matching `SceneBoundary` ids and concise static copy:

```tsx
export default function IdentityScene() {
  return <SceneBoundary id="identity" label="Identity" silence><h2>Your sonic fingerprint is still forming.</h2></SceneBoundary>;
}
```

Use the exact exported function names: `IdentityScene`, `ListeningInterviewScene`, `PrivateSyncScene`, `EmotionalSessionScene`, `FlowScene`, `WorldsScene`, `MemoryScene`.

- [ ] **Step 5: Replace `website/src/App.tsx`**

```tsx
import ChapterNav from './components/cinematic/ChapterNav';
import RecognitionScene from './components/scenes/RecognitionScene';
import IdentityScene from './components/scenes/IdentityScene';
import ListeningInterviewScene from './components/scenes/ListeningInterviewScene';
import PrivateSyncScene from './components/scenes/PrivateSyncScene';
import EmotionalSessionScene from './components/scenes/EmotionalSessionScene';
import FlowScene from './components/scenes/FlowScene';
import WorldsScene from './components/scenes/WorldsScene';
import MemoryScene from './components/scenes/MemoryScene';
import { SonicRuntimeProvider } from './runtime/SonicRuntimeProvider';

function App() {
  return (
    <SonicRuntimeProvider>
      <main className="bg-black text-primary overflow-x-hidden">
        <ChapterNav />
        <RecognitionScene />
        <IdentityScene />
        <ListeningInterviewScene />
        <PrivateSyncScene />
        <EmotionalSessionScene />
        <FlowScene />
        <WorldsScene />
        <MemoryScene />
      </main>
    </SonicRuntimeProvider>
  );
}

export default App;
```

- [ ] **Step 6: Run scene order test**

Run:

```powershell
npm test -- src/__tests__/App.sceneOrder.test.tsx
```

Expected: all tests pass.

- [ ] **Step 7: Cross-scene browser check**

Run:

```powershell
npm run dev -- --host=127.0.0.1 --port=5173
```

Open `http://127.0.0.1:5173` in the in-app browser. Check that Recognition flows into Identity without hard app-page separation.

- [ ] **Step 8: Commit**

```powershell
git add website/src/App.tsx website/src/components website/src/__tests__/App.sceneOrder.test.tsx
git commit -m "feat: scaffold cinematic scene journey"
```

---

### Task 7: Recognition, Interview, And Identity Backend Loop

**Files:**
- Modify: `website/src/components/scenes/RecognitionScene.tsx`
- Modify: `website/src/components/scenes/ListeningInterviewScene.tsx`
- Modify: `website/src/components/scenes/IdentityScene.tsx`
- Test: `website/src/__tests__/interviewIdentityFlow.test.tsx`

- [ ] **Step 1: Write failing flow test**

Create `website/src/__tests__/interviewIdentityFlow.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, test } from 'vitest';
import ListeningInterviewScene from '../components/scenes/ListeningInterviewScene';
import IdentityScene from '../components/scenes/IdentityScene';
import { SonicRuntimeProvider } from '../runtime/SonicRuntimeProvider';

describe('interview and identity emotional center', () => {
  test('interview collects one answer without looking like a form wizard', async () => {
    render(<SonicRuntimeProvider><ListeningInterviewScene /></SonicRuntimeProvider>);

    expect(screen.queryByText(/step/i)).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('musical memory answer'), 'A song I played every winter.');
    await userEvent.click(screen.getByRole('button', { name: 'Let it listen' }));

    expect(screen.getByText(/listening/i)).toBeInTheDocument();
  });

  test('identity scene renders emotional self portrait copy', () => {
    render(<SonicRuntimeProvider><IdentityScene /></SonicRuntimeProvider>);
    expect(screen.getByText(/sonic fingerprint/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run failing test**

Run:

```powershell
npm test -- src/__tests__/interviewIdentityFlow.test.tsx
```

Expected: fails because interview controls are not implemented.

- [ ] **Step 3: Implement interview UI**

In `ListeningInterviewScene.tsx`, render one cinematic prompt, a visually quiet textarea, and one CTA. On submit dispatch `interview/answerAdded`, then call `sonicApi.getAdaptiveQuestion` in implementation if a session token exists. Initial static prompt:

```tsx
const openingQuestion = 'What song keeps returning to you, even when you have changed?';
```

Use `aria-label="musical memory answer"` on the textarea and button text `Let it listen`.

- [ ] **Step 4: Implement identity UI**

Use `useSonicRuntime` and `describeIdentity(state.identity.genome)`. If no identity exists, render:

```tsx
Your sonic fingerprint is still forming.
```

Once identity resolves, render archetype, emotional copy, and restrained genome language without numeric values.

- [ ] **Step 5: Run tests**

Run:

```powershell
npm test -- src/__tests__/interviewIdentityFlow.test.tsx src/__tests__/runtimeReducers.test.ts
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add website/src/components/scenes website/src/__tests__/interviewIdentityFlow.test.tsx
git commit -m "feat: connect interview and identity state"
```

---

### Task 8: Spotify Private Sync And Emotional Session Generation

**Files:**
- Modify: `website/src/components/scenes/PrivateSyncScene.tsx`
- Modify: `website/src/components/scenes/EmotionalSessionScene.tsx`
- Modify: `website/src/runtime/types.ts`
- Test: `website/src/__tests__/syncSessionFlow.test.tsx`

- [ ] **Step 1: Write failing tests**

Create `website/src/__tests__/syncSessionFlow.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import EmotionalSessionScene from '../components/scenes/EmotionalSessionScene';
import PrivateSyncScene from '../components/scenes/PrivateSyncScene';
import { SonicRuntimeProvider } from '../runtime/SonicRuntimeProvider';

describe('private sync and emotional session scenes', () => {
  test('spotify sync is framed as emotional archive access', () => {
    render(<SonicRuntimeProvider><PrivateSyncScene /></SonicRuntimeProvider>);
    expect(screen.getByText(/emotional archive/i)).toBeInTheDocument();
    expect(screen.queryByText(/oauth/i)).not.toBeInTheDocument();
  });

  test('session modes are emotionally named and sparse', () => {
    render(<SonicRuntimeProvider><EmotionalSessionScene /></SonicRuntimeProvider>);
    expect(screen.getByText(/Night drive/i)).toBeInTheDocument();
    expect(screen.getByText(/Healing/i)).toBeInTheDocument();
    expect(screen.queryByText(/discovery_ratio/i)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run failing tests**

Run:

```powershell
npm test -- src/__tests__/syncSessionFlow.test.tsx
```

Expected: fails until scenes render required copy.

- [ ] **Step 3: Implement `PrivateSyncScene`**

Render copy around "unlock your emotional archive" and use `sonicApi.spotifyLoginUrl` to redirect only when a session token exists. If no session exists, create one first through `createSession`.

- [ ] **Step 4: Implement `EmotionalSessionScene`**

Render sparse intent options:

```ts
const modes = [
  { id: 'night_drive', label: 'Night drive', line: 'Shadow, motion, and a slow horizon.' },
  { id: 'healing', label: 'Healing', line: 'Soft lift without forced brightness.' },
  { id: 'confidence', label: 'Confidence', line: 'An internal pulse becoming visible.' },
  { id: 'heartbreak', label: 'Heartbreak', line: 'Descent, ache, and quiet release.' },
  { id: 'focus', label: 'Focus', line: 'A steady room with softened edges.' },
];
```

On selection, dispatch `sessionIntent/updated`. The generate action should call `/playlist/trial` if no session identity exists and `/playlist/session/{cluster_id}` if a saved session identity exists.

- [ ] **Step 5: Run tests**

Run:

```powershell
npm test -- src/__tests__/syncSessionFlow.test.tsx
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add website/src/components/scenes website/src/runtime website/src/__tests__/syncSessionFlow.test.tsx
git commit -m "feat: add private sync and emotional session scenes"
```

---

### Task 9: Flow, Worlds, And Memory Scenes

**Files:**
- Modify: `website/src/components/scenes/FlowScene.tsx`
- Modify: `website/src/components/scenes/WorldsScene.tsx`
- Modify: `website/src/components/scenes/MemoryScene.tsx`
- Test: `website/src/__tests__/flowWorldsMemory.test.tsx`

- [ ] **Step 1: Write failing tests**

Create `website/src/__tests__/flowWorldsMemory.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import FlowScene from '../components/scenes/FlowScene';
import MemoryScene from '../components/scenes/MemoryScene';
import WorldsScene from '../components/scenes/WorldsScene';
import { SonicRuntimeProvider } from '../runtime/SonicRuntimeProvider';

describe('flow worlds and memory scenes', () => {
  test('flow avoids telemetry language', () => {
    render(<SonicRuntimeProvider><FlowScene /></SonicRuntimeProvider>);
    const text = document.body.textContent?.toLowerCase() ?? '';
    expect(text).toContain('threshold');
    expect(text).not.toContain('metric');
    expect(text).not.toContain('graph');
    expect(text).not.toContain('score');
  });

  test('worlds avoids taxonomy language', () => {
    render(<SonicRuntimeProvider><WorldsScene /></SonicRuntimeProvider>);
    const text = document.body.textContent?.toLowerCase() ?? '';
    expect(text).toContain('territory');
    expect(text).not.toContain('cluster');
    expect(text).not.toContain('node');
  });

  test('memory is recursive without becoming journaling', () => {
    render(<SonicRuntimeProvider><MemoryScene /></SonicRuntimeProvider>);
    expect(screen.getByText(/return to this version/i)).toBeInTheDocument();
    expect(screen.queryByText(/journal/i)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run failing tests**

Run:

```powershell
npm test -- src/__tests__/flowWorldsMemory.test.tsx
```

Expected: fails until scene copy and structure are implemented.

- [ ] **Step 3: Implement `FlowScene`**

Use `projectFlowChapters(state.playlist.tracks)`. If no tracks exist, show an abstract empty state:

```tsx
The sequence will appear here as movement, not telemetry.
```

Render chapters as large text bands with track names. Do not render metrics, charts, or curves.

- [ ] **Step 4: Implement `WorldsScene`**

Use `orientationForScene('worlds', state.sessionIntent.explorationTone)`. Render close/open/far territory choices as emotional corridors. Do not render region chips until a user asks to open a corridor.

- [ ] **Step 5: Implement `MemoryScene`**

Render memory as optional revisit actions:

- `Return to this version`
- `See what changed`
- `Send this version of you`

Wire `createShare` and timeline loading after core scene rendering works.

- [ ] **Step 6: Run tests**

Run:

```powershell
npm test -- src/__tests__/flowWorldsMemory.test.tsx src/__tests__/flowProjection.test.ts
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```powershell
git add website/src/components/scenes website/src/__tests__/flowWorldsMemory.test.tsx
git commit -m "feat: add flow worlds and memory scenes"
```

---

### Task 10: Media Orchestration Layer

**Files:**
- Create: `website/src/media/mediaOrchestrator.ts`
- Test: `website/src/__tests__/mediaOrchestrator.test.ts`

**Purpose:** This layer must exist before motion polish. It keeps cinematic atmosphere performant and restrained by budgeting media, unloading offscreen assets, choosing mobile fallbacks, and arbitrating between preview clips and ambient punctuation.

- [ ] **Step 1: Write failing media orchestration tests**

Create `website/src/__tests__/mediaOrchestrator.test.ts` with coverage for progressive loading, viewport-aware unloading, mobile fallbacks, GPU budget caps, and single-source audio/preview arbitration.

- [ ] **Step 2: Implement `website/src/media/mediaOrchestrator.ts`**

Expose pure orchestration helpers first:

```ts
createMediaBudget(viewport: 'mobile' | 'desktop', reducedMotion: boolean)
selectSceneAsset(sceneId, budget, connectionHint)
shouldUnloadAsset(asset, viewportDistance)
arbitratePlayback(current, requested)
```

Rules:

- Mobile defaults to static or low-motion assets unless the scene is in focus and budget allows motion.
- Offscreen media unloads when it exceeds the viewport distance threshold.
- Preview audio wins over ambient punctuation; ambient punctuation must fade or remain silent.
- No scene may reserve unlimited atmospheric assets.
- Media orchestration state is internal and must never appear as visible UI diagnostics.

- [ ] **Step 3: Verify media tests**

```powershell
npm test -- src/__tests__/mediaOrchestrator.test.ts
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```powershell
git add website/src/media website/src/__tests__/mediaOrchestrator.test.ts
git commit -m "feat: add cinematic media orchestration"
```

---
### Task 11: Restrained Audio And Clip Playback

**Files:**
- Create: `website/src/components/audio/AudioBoundary.tsx`
- Create: `website/src/components/audio/ClipPlayer.tsx`
- Modify: `website/src/components/scenes/ListeningInterviewScene.tsx`
- Test: `website/src/__tests__/ClipPlayer.test.tsx`

- [ ] **Step 1: Write failing audio tests**

Create `website/src/__tests__/ClipPlayer.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import AudioBoundary from '../components/audio/AudioBoundary';
import ClipPlayer from '../components/audio/ClipPlayer';
import { SonicRuntimeProvider } from '../runtime/SonicRuntimeProvider';

describe('restrained audio behavior', () => {
  test('audio boundary defaults to silence', () => {
    render(<SonicRuntimeProvider><AudioBoundary><p>Quiet scene</p></AudioBoundary></SonicRuntimeProvider>);
    expect(screen.getByText('Quiet scene')).toBeInTheDocument();
    expect(document.body.textContent?.toLowerCase()).toContain('quiet scene');
  });

  test('clip player renders minimal controls only', () => {
    render(<ClipPlayer clip={{ clip_id: 'a', title: 'Soft weather', audio_url: '/clip.mp3' }} onRate={() => undefined} />);
    expect(screen.getByRole('button', { name: 'Play clip' })).toBeInTheDocument();
    expect(screen.queryByText(/visualizer/i)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run failing tests**

Run:

```powershell
npm test -- src/__tests__/ClipPlayer.test.tsx
```

Expected: fails because audio components do not exist.

- [ ] **Step 3: Implement `AudioBoundary.tsx`**

```tsx
import type { ReactNode } from 'react';

export default function AudioBoundary({ children }: { children: ReactNode }) {
  return <div data-audio-policy="single-source-silent-default">{children}</div>;
}
```

- [ ] **Step 4: Implement `ClipPlayer.tsx`**

```tsx
import { Pause, Play } from 'lucide-react';
import { useRef, useState } from 'react';

type Clip = { clip_id: string; title: string; audio_url: string; description?: string };

export default function ClipPlayer({ clip, onRate }: { clip: Clip; onRate: (rating: number) => void }) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);

  const toggle = async () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (playing) {
      audio.pause();
      setPlaying(false);
    } else {
      await audio.play();
      setPlaying(true);
    }
  };

  return (
    <div className="flex flex-col gap-5">
      <audio ref={audioRef} src={clip.audio_url} onEnded={() => setPlaying(false)} />
      <button aria-label={playing ? 'Pause clip' : 'Play clip'} onClick={toggle} className="w-12 h-12 rounded-full border border-primary/20 flex items-center justify-center text-primary">
        {playing ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
      </button>
      <p className="text-primary/50 text-sm">{clip.title}</p>
      <div className="flex gap-2" aria-label="clip reaction">
        {[1, 2, 3, 4, 5].map((rating) => (
          <button key={rating} onClick={() => onRate(rating)} className="w-8 h-8 rounded-full border border-primary/15 text-primary/50 text-xs">
            {rating}
          </button>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Run tests**

Run:

```powershell
npm test -- src/__tests__/ClipPlayer.test.tsx
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add website/src/components/audio website/src/__tests__/ClipPlayer.test.tsx
git commit -m "feat: add restrained clip playback"
```

---

### Task 12: Cross-Scene Integration And Visual Pass

**Files:**
- Modify: `website/src/App.tsx`
- Modify: `website/src/index.css`
- Modify: scene files under `website/src/components/scenes/`

- [ ] **Step 1: Run full test suite**

Run:

```powershell
npm test
```

Expected: all frontend tests pass.

- [ ] **Step 2: Run lint**

Run:

```powershell
npm run lint
```

Expected: lint exits with code 0.

- [ ] **Step 3: Run build**

Run:

```powershell
npm run build
```

Expected: TypeScript and Vite build exits with code 0.

- [ ] **Step 4: Start backend**

Run from `backend`:

```powershell
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Expected: backend serves `http://127.0.0.1:8000/health`.

- [ ] **Step 5: Start frontend**

Run from `website`:

```powershell
npm run dev -- --host=127.0.0.1 --port=5173
```

Expected: frontend serves `http://127.0.0.1:5173`.

- [ ] **Step 6: Browser verification, desktop**

Use the in-app browser at `http://127.0.0.1:5173`. Verify:

- Recognition establishes curiosity within the first viewport.
- Identity and Listening Interview feel like the emotional center.
- Private Sync avoids technical OAuth language.
- Emotional Session does not expose raw controls.
- Flow feels like movement, not telemetry.
- Worlds feels exploratory, not taxonomic.
- Memory feels lightweight and recursive.
- No scene hard-cuts from the previous scene.

- [ ] **Step 7: Browser verification, mobile**

Set viewport to mobile width. Verify:

- No desktop card stack dump.
- Type is choreographed into readable beats.
- Flow is vertical and abstract.
- Audio controls do not become sticky unless protecting playback.
- Text does not overlap or overflow.
- Scroll remains smooth.

- [ ] **Step 8: Performance pass**

Check browser console and interaction feel:

- No console errors.
- No obvious scroll jank.
- No simultaneous heavy video layers in one viewport.
- Reduced motion preference is respected.

- [ ] **Step 9: Commit**

```powershell
git add website/src
git commit -m "polish: integrate cinematic SonicDNA journey"
```

---

## Plan Self-Review

Spec coverage:

- Emotional scene hierarchy: Tasks 6-9.
- Motion system rules: Task 2 and Task 12.
- Shared spacing and typography: Task 2, Task 6, Task 12.
- Interaction philosophy and silence: Tasks 2, 6, 10, 11.
- Backend-to-scene mapping: Tasks 4, 7, 8, 9.
- Split runtime architecture across session/backend, emotional, scene, audio, and async/network domains: Task 3.
- Progressive disclosure and forbidden UI patterns: Tasks 5, 6, 8, 9, 12.
- Media orchestration and atmospheric budgeting: Task 10.
- Mobile cinematic behavior: Task 12.
- Soundtrack and audio restraint: Task 11.
- Loading transitions: Tasks 7-9, media orchestration in Task 10, and final polish in Task 12.
- Implementation phase order: task order follows the required phase order.

Plan gap scan:

- No unresolved plan gaps are intentionally present.

Type consistency:

- Split runtime state domains, track types, emotional runtime controls, and action names are defined before use.
- Scene ids match the approved order and test expectations.
- API client function names match the spec.

---

## Execution Choice

Plan complete and saved to `docs/superpowers/plans/2026-05-17-sonicdna-cinematic-product-integration.md`. Two execution options:

1. **Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** - execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?

