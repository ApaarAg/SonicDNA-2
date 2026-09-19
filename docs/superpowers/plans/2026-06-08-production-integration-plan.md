# Plan - SonicDNA Cinematic Production Integration (Multi-Theme React + TS + Tailwind v4)

We will migrate the existing `/frontend` vanilla HTML/JS setup to a modern, production-grade React 19 + TypeScript + Tailwind CSS v4 app. To honor the user's love for all three designs, we will engineer the frontend with an **Emotional Theme Orchestrator** allowing users to experience the application in **Elemental Crimson**, **Analog Amber**, or **Nordic Void** mode, or let the system dynamically adapt the theme based on the user's intuitive listening profile.

---

# 1. Design-Plan (UI/UX)

The user interface will be implemented as a continuous cinematic scroll with 8 distinct, stateful scenes. 

### Theme Token Mapping

| Token / Asset | Elemental Crimson | Analog Amber | Nordic Void |
| :--- | :--- | :--- | :--- |
| **Primary BG** | Pitch Black (`#050505`) | Deepest Espresso (`#120A05`) | Void Black (`#000000`) |
| **Accent Glow** | Deep Crimson (`#4A0404`) | Amber Glow (`#D97725`) | Glacial Blue (`#1A2B3C`) |
| **Primary Font**| `Oswald` (Sans, compressed) | `Anton` (Heavy display) | `Inter` (Stark & clean) |
| **Serif Font**  | `Instrument Serif` (Italic) | `Instrument Serif` (Italic) | `Instrument Serif` (Italic) |
| **Sensory Media**| Red Smoke Video | Warm Light Leaks Video | Falling Dust/Snow Video |

### Component Hierarchy Tree

```
App.tsx (Theme Context & Split Runtime Orchestrator)
 ├── AtmosphericMediaLayer (Orchestrates background videos/fallback image streams)
 ├── ChapterNav (Minimal floating timeline navigator)
 └── ContinuousScrollContainer
      ├── SceneBoundary [1. Recognition] (Hero, Name Input, Spotify Connect hook)
      ├── SceneBoundary [2. Listening Interview] (Calibration clips & adaptive rating slider)
      ├── SceneBoundary [3. Identity] (Sonic genome reveal, archetype statement)
      ├── SceneBoundary [4. Private Sync] (Subtle Spotify archive synchronizer)
      ├── SceneBoundary [5. Emotional Session] (Cinematic mode dial generator)
      ├── SceneBoundary [6. Flow] (The horizontal/vertical emotional playlist arc)
      ├── SceneBoundary [7. Worlds] (Interactive geographic crossover corridors)
      └── SceneBoundary [8. Memory] (Historical snapshots & compatibility sharing ledger)
```

---

# 2. Technical Implementation & Architecture

### Five-Domain Split Runtime State Shape
We will define state across five lightweight, coordinated slices in React Context:
1. **Session Slice:** User profile, token, Spotify OAuth connection, generated playlist cache.
2. **Emotional Slice:** Active theme (`crimson` | `amber` | `nordic`), intensity coefficient, interaction pacing.
3. **Scene Slice:** Active scene index, scroll transition status, stillness-zone gates.
4. **Audio Slice:** Active audio stream, single-source clip play/pause arbitration, ambient layer toggle.
5. **Network Slice:** In-flight loading flags, retry contexts, error boundaries.

---

# 3. Definition of Done (DoD)

- [ ] Complete migration of `/frontend` to Vite + React + TypeScript + Tailwind CSS.
- [ ] Implement all 3 visual identities (Crimson, Amber, Nordic) in a unified theme provider.
- [ ] Connect the 8 cinematic scenes to the actual FastAPI backend (`http://127.0.0.1:8000`) with typed API requests.
- [ ] Fully support mobile layouts with vertical choreography and responsive media fallbacks.
