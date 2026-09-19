# SonicDNA Cinematic Product Integration Design

Date: 2026-05-17

## Purpose

Transform the existing `/website` cinematic frontend into the production SONICDNA product without replacing its visual identity. The final experience must feel like one evolving emotional film: editorial first, interface second, with real backend systems expressed as quiet, immersive interactions.

The product architecture is a continuous cinematic scroll with internal, stateful emotional scenes. It must not become a routed SaaS app, dashboard, analytics surface, or collection of feature panels.

## Source Design System

The current `/website` pages are the visual canon. Preserve their strongest systems:

- Dark luxury atmosphere with black foundations, ivory typography, low-contrast secondary text, subtle grain, and atmospheric video or image media.
- Giant typography as the primary storytelling layer, especially oversized sans headings paired with italic Instrument Serif emotional emphasis.
- Editorial spacing with long breathing room, dramatic section entrances, restrained copy density, and asymmetric grid composition.
- Motion based on slow reveals, text pull-up, scroll-linked reading, image scale drift, subtle fades, stillness, interruption, delayed response, tension, silence, and long easing curves. Blur/filter motion is budgeted at zero by default.
- Cinematic framing through full-bleed or large media slabs, overlays, vignettes, and low UI chrome.
- Minimal navigation that feels like chapter movement rather than app routing.

The duplicate prototype folders under `/website/new_website` and `/website/new website` can inform liquid-glass navigation and video fade behavior, but the active Vite React app under `/website/src` remains the integration target.

## Product Shape

The product remains a single continuous scroll experience with deep scene modules inside it.

The outside layer is a cinematic narrative shell. The inside layer is a persistent emotional system that carries state across identity, quiz, Spotify, playlist, flow, discovery, audio clips, snapshots, and sharing.

Navigation may jump to scene anchors, but it must not visually imply separate pages. Any hidden route support should exist only for recovery states or share links, not as primary information architecture.

The core balance is cinematic ambiguity with felt intelligence and real utility. Mystery without payoff becomes aesthetic fog. Every poetic scene must eventually create a concrete moment of recognition: a question that feels unusually personal, an identity statement that lands, a playlist arc that makes emotional sense, or a memory artifact worth revisiting.

## Highest-Risk Failure Modes

These risks must be checked during implementation reviews:

- Recognition becomes branding theater instead of emotionally responsive product entry.
- Scenes are technically modular but psychologically fragmented.
- Flow becomes Spotify Wrapped for sequencing telemetry.
- Worlds becomes a visible taxonomy of regions, genres, graph nodes, and clusters.
- Mobile becomes a stacked desktop layout instead of a re-authored cinematic experience.
- Audio becomes continuous stimulation instead of rare punctuation.
- Progressive disclosure erodes into visible state, labels, panels, indicators, and scores.
- Memory becomes saved playlists plus sharing instead of emotional recursion.
- Frontend romanticism exceeds backend clarity and users cannot tell what SonicDNA actually does.
- Global emotional state becomes decorative theming instead of materially changing behavior.
- The experience becomes too solemn, self-serious, or aesthetically reverent to feel human.
- Cinematic assets overload the browser and damage frame pacing, which damages emotional trust.

## Approved Scene Hierarchy

The scene order is fixed unless future usability testing shows severe friction:

1. Recognition
2. Identity
3. Listening Interview
4. Private Sync
5. Emotional Session
6. Flow
7. Worlds
8. Memory

This hierarchy mirrors psychological progression rather than backend feature inventory.

## Scene Designs

### 1. Recognition

Purpose: emotional intrigue, atmosphere, aesthetic trust.

This scene preserves the existing hero and origin language. It should not mechanically explain the product. It should imply that SonicDNA understands music as identity, memory, and emotional return.

The first 20-40 seconds must establish emotional intrigue, behavioral curiosity, and subtle system responsiveness. It cannot be only atmospheric. The opening should imply "this system understands musical identity differently," not "this is a beautiful creative-tech website."

Primary backend touches:

- `POST /user/session` to establish an anonymous or named listening session.
- `GET /spotify/status` only after a session token exists, used quietly to personalize later states.

Visible interaction:

- One primary CTA into the Listening Interview or Identity reveal.
- One secondary path for Spotify sync, framed emotionally rather than technically.
- A lightweight responsive beat that reacts to the user's first choice or scroll behavior. Examples: hero copy subtly shifts after a hover/scroll, the system asks a single evocative prompt, or the page reveals "what song keeps finding you?" before the full interview begins.

Avoid:

- "AI recommendation engine" language.
- Dense feature claims.
- Immediate control surfaces.
- A long poetic intro that delays interaction tension.

### 2. Identity

Purpose: self-definition and musical psychology.

Identity is the first major emotional center. It presents the user's taste genome, archetype, regional identity, emotional profile, exploration tendencies, and sonic texture affinity as a living self-portrait.

Primary backend touches:

- Result objects from `POST /analyze_adaptive` and `POST /clips/submit`.
- `POST /user/timeline` for saved identity snapshots.
- `POST /user/drift` for emotional change over time.
- Spotify profile influence from the backend's `spotify_taste_influence` result.

UI translation:

- Use editorial fragments, large identity statements, texture bands, and atmosphere-reactive copy instead of analytics charts.
- Genome values should appear as emotional language first. Numeric values stay hidden or secondary.
- Regional and texture affinity should feel like identity signals, not filter settings.

Avoid:

- Radar charts, stat tables, equal feature cards, dense labels.
- Explaining every backend score.

### 3. Listening Interview

Purpose: adaptive introspection and behavioral profiling.

The adaptive quiz must feel like an intimate psychological music journey. It cannot feel like a form, survey, wizard, productivity flow, or quiz app.

Primary backend touches:

- `POST /adaptive_question`
- `GET /clips/round1`
- `POST /clips/adaptive`
- `POST /analyze_adaptive`
- `POST /user/save_snapshot`

UI translation:

- Present one question at a time inside a cinematic scene with large type and atmospheric transitions.
- Question copy should feel personal and reflective.
- Clip reactions should feel like gut-listening moments with elegant audio controls and no repetitive playback behavior.
- Progress should be ambient, not a visible form stepper.
- Completion should dissolve into Identity, not submit to a result page.

Avoid:

- Form labels, progress bars that dominate, radio-card grids, "Next question" mechanics that feel generic.
- Showing covered dimensions or inference internals as visible UI.

### 4. Private Sync

Purpose: trust, intimacy, Spotify ingestion.

Spotify connection must feel personal, not technical. The user is revealing a listening archive, not authorizing a utility integration.

Primary backend touches:

- `GET /spotify/login`
- `GET /spotify/status`
- `POST /spotify/disconnect`
- Backend taste retrieval and cache behavior through OAuth completion.

UI translation:

- Use language like "unlock your emotional archive," "let SonicDNA read the rooms your music has lived in," and "reveal your listening memory."
- Connection states should become atmospheric synchronization sequences.
- Reconnect and disconnect flows should be calm and respectful.
- Technical failures should be translated into human recovery copy without leaking OAuth mechanics.

Avoid:

- Generic "Connect Spotify to continue."
- OAuth-looking panels, account-management UI, technical status dumps.

### 5. Emotional Session

Purpose: active emotional intent formation and playlist generation.

Playlist generation is the core interactive product moment. It should feel like entering an emotional state, not clicking a button to receive songs.

Primary backend touches:

- `POST /playlist/trial`
- `POST /playlist/session/{cluster_id}`
- `backend/config/session_intents.py` intent profiles
- Generator support for mood, duration, discovery ratio, exploration factor, regional crossover, explanations, and session type.

UI translation:

- Session intents become cinematic emotional modes: healing, night drive, confidence, heartbreak, focus, calm, celebration, rage, romantic, party, workout.
- Controls are sparse and emotionally named.
- Duration and exploration intensity should feel like pacing choices, not parameter sliders unless the slider is visually understated.
- Generated playlist identity should appear as a title, emotional premise, and curated sequence.
- Familiar, discovery, and exploration tracks should be visible through language and pacing, not heavy badges.

Avoid:

- Dense parameter panels.
- Raw settings tables.
- "Generate playlist" as the only meaningful interaction.

### 6. Flow

Purpose: communicate SonicDNA's differentiator: emotional movement.

This is the most important differentiator scene. Most music products optimize relevance; SonicDNA must communicate movement, recovery, release, contrast, escalation, texture continuity, and emotional sequencing.

Primary backend touches:

- Ordered playlist response fields.
- Public playlist track fields: energy, valence, danceability, acousticness, instrumentalness, speechiness, tempo, duration, source, region, explanation fields.
- Backend flow systems in `playlist_flow_engine.py`, `flow_evaluation.py`, and semantic contracts, but only through user-facing interpretations.

UI translation:

- Render the playlist as an emotional arc with chapters such as threshold, rise, rupture, recovery, and afterglow.
- Use flowing timelines, cinematic scene cuts, and track-to-track atmosphere shifts.
- Texture continuity should be felt through transition copy and visual continuity, not raw metrics.
- Emotional arc visualization must not look like a generic graph.
- The user should feel flow before inspecting anything. The first read should be experiential: "this playlist breaks, recovers, and releases." Details appear only as sparse track-to-track rationale when the user leans in.
- Abstract cinematic devices are preferred: shifting light bands, chapter cards without borders, vertical emotional descent/ascent, track title choreography, atmosphere crossfades, and restrained transition prose.

Avoid:

- Raw flow quality scores, spider charts, diagnostic tables, graph jargon.
- Treating flow as analytics.
- Explicit curves, node maps, sequencing metrics, transition scores, or diagnostic overlays as primary UI.

### 7. Worlds

Purpose: exploration, discovery topology, cultural crossover.

Worlds should feel like entering musical territories, not browsing categories or recommendations.

Primary backend touches:

- `GET /regions`
- `GET /recommendations/{cluster_id}/{region_key}`
- Playlist discovery and exploration fields from generated playlists.
- Regional and topology-aware discovery behavior from `spotify_service_fixed.py`, `track_graph.py`, and `exploration_engine.py`.

UI translation:

- Regions become atmospheric territories or corridors.
- Discovery is spatialized as movement from familiar anchors into adjacent worlds.
- Cultural crossover should feel respectful, exploratory, and emotionally connected to the user's identity.
- Semantic bridges and texture-aware transitions remain implicit unless they help explain why a discovery belongs.
- Discovery language should use wandering, drifting, border-crossing, corridor, and hidden-continuity metaphors. Topology is felt as coherence between unfamiliar tracks, not shown as infrastructure.

Avoid:

- Category grids, generic recommendation feeds, map gimmicks, world music stereotypes.
- Genre trees, region chip clouds, semantic node diagrams, visible clusters, ontology browsers, or "because graph adjacency" explanations.

### 8. Memory

Purpose: persistence, emotional residue, replayability, sharing.

Memory is essential, not a footer. It transforms SonicDNA from playlist generation into an ongoing emotional relationship.

Memory must become emotionally recursive. It should make the user revisit who they were when a playlist or identity snapshot was created, notice how their listening self changes, and re-enter older emotional states with new context.

Primary backend touches:

- `POST /user/save_snapshot`
- `POST /user/timeline`
- `POST /user/drift`
- `POST /share/create`
- `GET /share/{share_code}`
- `POST /share/{share_code}/complete`
- `POST /share/my`
- `POST /compatibility/compare`

UI translation:

- Snapshots are emotional music portraits saved across time.
- Sharing should feel like sending a cinematic memory artifact, not a social card.
- Timeline and drift should show emotional continuity over time with restrained copy and atmospheric visuals.
- Compatibility should be framed as resonance between listening identities, not a score contest.
- Revisit states should be first-class: "return to this night drive," "see what changed," "rebuild from this memory," "send this version of you."
- Drift should read as identity evolution, not analytics.

Avoid:

- Footer treatment.
- Viral widgets, leaderboard emphasis, social growth mechanics as the dominant experience.
- Reducing Memory to saved playlists, links, and share buttons.

## Backend-To-Scene Mapping

| Scene | Backend surface | Frontend interpretation |
| --- | --- | --- |
| Recognition | `/user/session`, `/spotify/status` | Establish a private listening session quietly |
| Identity | `/analyze_adaptive`, `/clips/submit`, `/user/timeline`, `/user/drift` | Living sonic self-portrait |
| Listening Interview | `/adaptive_question`, `/clips/round1`, `/clips/adaptive`, `/analyze_adaptive` | Reflective conversation and gut audio reactions |
| Private Sync | `/spotify/login`, `/spotify/status`, `/spotify/disconnect` | Emotional archive unlock |
| Emotional Session | `/playlist/trial`, `/playlist/session/{cluster_id}` | Intent-led playlist creation |
| Flow | playlist response, safe track fields, sequencing order | Emotional arc and transition experience |
| Worlds | `/regions`, `/recommendations/{cluster_id}/{region_key}` | Musical territory exploration |
| Memory | `/user/save_snapshot`, `/user/timeline`, `/share/create`, `/share/{share_code}`, `/compatibility/compare` | Emotional continuity, snapshots, sharing |

Backend intelligence should be exposed unevenly. The frontend should reveal only what deepens the emotional moment.

## Global Split Runtime State Model

Create a global emotional state model for the frontend, but do not implement it as a single monolithic reducer. It should be split into separate runtime domains with clear ownership and coordinated through a thin provider/composition layer.

This model is not just persistence. It continuously evolves the product's tone, pacing, typography density, soundtrack restraint, interaction rhythm, and scene emphasis based on accumulated inference from quiz answers, clip ratings, Spotify taste, playlist generation, exploration choices, and memory history.

The emotional runtime must materially alter behavior. It cannot merely tint colors, vary copy, or change animation speed. It must influence pacing, scene transition timing, interaction density, typography rhythm, emotional contrast between sections, playlist presentation behavior, question cadence, discovery aggressiveness, soundtrack restraint, and how much visual silence each scene holds.

Scenes may be modular in code, but they must read from coordinated runtime state so the product feels alive rather than assembled.

### Runtime Architecture Split

Use these runtime slices:

- Session/backend state: session token, profile code, Spotify status, identity result, playlist result, memory/share payloads.
- Emotional runtime state: dominant tone, intensity, intimacy, exploration readiness, typography density, motion tempo, audio permission, last emotional beat.
- Scene runtime state: active scene, previous scene, transition phase, interaction payoff cadence, scene completion, silence-zone eligibility.
- Audio runtime state: active clip, active preview, muted state, playback permission, single-source arbitration, last audio punctuation.
- Async/network state: request lifecycle, loading surfaces, recoverable errors, retry state, stale data markers.

Each slice should have its own reducer or focused state module. The orchestration layer may derive cross-slice selectors, but it must not become a hidden mega-reducer.

Illustrative state shape:

```ts
type SessionBackendState = {
  sessionToken: string | null;
  user?: {
    displayName?: string;
    profileCode?: string;
  };
  spotify: {
    connected: boolean;
    profileReady: boolean;
    topArtists: string[];
    topGenres: string[];
    regionalAffinity?: string;
  };
  interview: {
    answers: string[];
    askedQuestions: string[];
    coveredDimensions: string[];
    clipRatings: Array<{ clip_id: string; rating: number }>;
    currentQuestion?: {
      question: string;
      hint?: string;
      question_number?: number;
    };
  };
  identity: {
    genome?: Record<string, number>;
    archetype?: { id?: number; name?: string; tagline?: string };
    region?: string;
    reasoning?: string;
    spotifyTasteInfluence?: {
      top_artists?: string[];
      top_genres?: string[];
      regional_affinity?: string;
      music_diversity?: number;
    };
    snapshotId?: string;
  };
  sessionIntent: {
    mode: string;
    targetMinutes: number;
    explorationTone: "close" | "open" | "far";
    regionKey: string;
  };
  playlist: {
    name?: string;
    description?: string;
    tracks: SonicTrack[];
    actualMinutes?: number;
    discoveryRatio?: number;
    explorationRatio?: number;
  };
  audio: {
    activeClipId?: string;
    activeTrackId?: string;
    ambientLayer: "recognition" | "interview" | "sync" | "session" | "flow" | "worlds" | "memory";
    muted: boolean;
  };
  memory: {
    timeline: unknown[];
    shareCode?: string;
    shareUrl?: string;
  };
};

type EmotionalRuntimeState = {
  dominantTone: "curious" | "tender" | "charged" | "nocturnal" | "restorative" | "expansive";
  intensity: number;
  intimacy: number;
  explorationReadiness: number;
  typographyDensity: "spare" | "balanced" | "compressed";
  motionTempo: "still" | "slow" | "medium";
  audioPermission: "silent" | "punctuation" | "preview";
  lastEmotionalBeat?: string;
};

type SceneRuntimeState = {
  activeScene: "recognition" | "identity" | "listening-interview" | "private-sync" | "emotional-session" | "flow" | "worlds" | "memory";
  previousScene?: SceneRuntimeState["activeScene"];
  transitionPhase: "settled" | "entering" | "leaving";
  payoffCount: number;
  silenceZone: boolean;
};

type AudioRuntimeState = {
  activeClipId?: string;
  activeTrackId?: string;
  muted: boolean;
  permission: "silent" | "punctuation" | "preview";
  lastPunctuationAt?: number;
};

type AsyncNetworkState = {
  pending: Record<string, boolean>;
  errors: Record<string, string | undefined>;
  stale: Record<string, boolean>;
};
```

The coordinated runtime should make scene transitions aware of state changes without forcing every scene to show all state. For example, a tender low-intensity user should see slower pacing, softer copy density, and quieter transitions than a high-energy confidence session.

Global emotional state must not become visible debug state. It is a director, not a dashboard.

Minimum systemic effects:

- `intensity` adjusts how quickly the interview advances, how many tracks are revealed per beat, and how much contrast appears in the Flow scene.
- `intimacy` adjusts copy density, question phrasing, private-sync tone, and whether Memory asks for reflection or stays quiet.
- `explorationReadiness` adjusts discovery aggressiveness, regional distance, and whether Worlds reveals close corridors or farther cultural crossings.
- `typographyDensity` adjusts line count and body copy presence by scene.
- `motionTempo` adjusts transition duration and stagger spacing.
- `audioPermission` gates whether clips, previews, or ambient punctuation can appear at all.

## Media Orchestration Layer

Add a dedicated media orchestration layer before motion polish. It owns:

- Progressive asset loading.
- Viewport-aware unloading.
- Mobile media fallbacks.
- GPU-conscious transitions.
- Preview/audio arbitration.
- Atmospheric asset budgeting.

This layer protects the cinematic experience from video bloat, mobile GPU collapse, overlapping previews, and transition stacking. Scenes request atmospheric media intent; the media orchestrator decides whether to serve video, image fallback, reduced-motion fallback, or silence.

Media orchestration logic must not appear directly in UI copy or controls. It is infrastructure, not a visible product concept.

## Progressive Disclosure Strategy

Use three layers:

1. Emotional layer: always visible. Large type, feeling, memory, atmosphere.
2. Interaction layer: visible only when the scene needs action. Sparse controls and one primary decision at a time.
3. System layer: revealed only after interaction, on demand, or when it strengthens trust. Never lead with mechanisms.

Examples:

- Show "Your listening leans toward warm rupture and late-night recovery" before showing genome categories.
- Show "This session rises, breaks, and resolves" before track-level sequencing rationale.
- Show "A familiar anchor opens the corridor" before explaining discovery or topology.

### Forbidden UI Patterns

These patterns are prohibited unless the user explicitly requests a debug or admin mode:

- Analytics cards.
- KPI grids.
- Floating debug state.
- Persistent sidebars.
- Dense settings panels.
- Visible recommendation scores.
- Raw genome score tables.
- Graph dashboards.
- Node-link diagrams.
- Region chip clouds.
- Genre taxonomy trees.
- Recommendation telemetry overlays.
- Multi-column control decks.
- System health widgets.
- "How it works" blocks that explain internals before the user feels value.

If a design starts needing one of these patterns, convert it into emotional language, progressive detail, or an optional hidden inspection state.

## Interaction Silence Rules

The experience needs intentional stillness zones. Cinematic systems fail when every element tries to be cinematic at once.

Required silence patterns:

- Every major scene must include at least one beat where typography dominates and motion is minimal.
- After any high-stimulation moment, such as clip playback, playlist generation, or a discovery reveal, the next beat should reduce motion and interaction density.
- Do not animate background media, text, controls, and audio transitions simultaneously unless it is the scene climax.
- Let users scroll through quiet space without hover reactivity or visible state changes.
- Silence is an active design material: fewer controls, fewer labels, fewer simultaneous fades, and less audio.

Forbidden:

- Constant parallax across the full page.
- Multiple reactive hover zones in the same viewport.
- Animated metrics, animated controls, and animated backgrounds running together.
- Ambient audio under every section.

## Motion System Rules

Motion should feel like film scene transitions:

- Use long easing curves: `[0.16, 1, 0.3, 1]` as the default expressive ease.
- Prefer 700ms to 1600ms entrance durations.
- Use opacity dissolves, text pull-up, slow media scale, asymmetric drift, stillness holds, interruption cuts, delayed response, tension rise, silence holds, and atmospheric fades.
- Stagger typography at word or phrase level, not every minor UI element.
- Use section-to-section environmental shifts through overlays, ambient media, and gradual color temperature changes.
- Avoid bounce, springy product animation, fast hover theatrics, confetti, kinetic counters, or dense microanimation.
- Avoid filter and blur animation by default. Any future blur must be explicitly budgeted, brief, and disabled on mobile/reduced motion.

Motion should never make the interface feel busy. It should make emotional transitions legible.

## Scene Transition Rules

Scene boundaries must not hard-cut.

Use:

- Typography dissolves or pull-up exits.
- Ambient audio fades or layer changes.
- Media crossfades.
- Slow overlay shifts.
- Shared visual motifs that carry from one scene to the next.
- Scroll-linked opacity and scale for chapter thresholds.

The transition from Listening Interview to Identity and from Emotional Session to Flow should receive special polish because these are high-emotion conversion moments.

## Typography Rhythm System

Typography remains dominant:

- Hero and major scene titles use giant sans type with tight tracking and very low line height.
- Emotional emphasis uses Instrument Serif italic sparingly.
- Labels stay small, uppercase, widely tracked, and low contrast.
- Body copy stays narrow, low contrast, and quiet.
- Interactive controls should not compete with headings.
- Never scale fonts directly with raw viewport width. Use Tailwind responsive classes and clamp values where needed for fixed-format hero text.

Suggested hierarchy:

- Hero title: `clamp(4.5rem, 13vw, 13rem)`, leading `0.82-0.9`.
- Scene title: `clamp(3rem, 8vw, 8.5rem)`, leading `0.88-0.96`.
- Scene heading: `clamp(2rem, 5vw, 5.5rem)`, leading `0.95-1.05`.
- Body: `0.875rem-1.125rem`, leading `1.55-1.75`, max width `36-58ch`.
- Labels: `10-12px`, letter spacing `0.24-0.32em`.

## Shared Spacing System

Preserve the existing cinematic rhythm:

- Full viewport hero.
- 96-180px scene breathing space on desktop.
- 64-120px scene breathing space on mobile, with fewer simultaneous elements.
- Constrained inner width around `1200px`.
- Asymmetric 12-column desktop layouts.
- Large empty zones are allowed when they hold tension or focus.
- Cards only for meaningful repeated items or framed interactive moments. Do not nest cards.

Interactive scenes must not fill every blank area with controls.

## Interaction Philosophy

Interactions should feel like emotional choices, not configuration.

Rules:

- One primary user action per scene beat.
- Controls should be sparse, tactile, and semantically named.
- Sliders and toggles may be used only where they map to felt qualities, such as closeness, duration, or openness.
- Forms should be visually dissolved into conversational moments.
- Error recovery should be calm and human.
- Loading states should feel like atmospheric synchronization, not spinners unless the spinner is visually quiet.

## Audio And Clip Behavior

Audio is part of the emotional system:

- Clip playback must avoid repetition by using the rotating clip system.
- Category-aware clips should appear as listening prompts, not samples in a list.
- Transitions between clips should fade smoothly.
- Ambient scene audio, if used, must be optional, subtle, and muted by default or clearly controllable.
- Audio controls should be elegant and minimal: play, pause, replay, and rating/reaction.
- Audio state must persist enough to avoid accidental overlapping playback across scenes.

Do not autoplay loud or surprising audio.

Hard restraint rules:

- Silence is part of the product language.
- Audio should behave like rare emotional punctuation, not continuous stimulation.
- Do not layer ambient audio, clip previews, Spotify previews, transition effects, and UI sounds at the same time.
- Only one audible source may play at once.
- Ambient audio must never be required to understand the product.
- Scene transitions may visually imply audio fades even when no audio is playing.
- Prefer short clip moments and intentional pauses over constant soundtrack.

## Loading And Failure States

Loading states should be scene-specific:

- Spotify sync: "reading your listening archive" atmosphere.
- Adaptive question: quiet pause, like the system is listening.
- Playlist generation: emotional state formation with slow title changes.
- Worlds discovery: corridor opening or territory resolving.
- Share creation: memory artifact being prepared.

Failures should preserve tone and offer a clear next step. Do not expose stack traces, API jargon, or OAuth internals.

## Mobile Cinematic Behavior

Mobile must be reimagined, not simply stacked.

Rules:

- Preserve giant type, but choreograph it into fewer lines and deliberate reveal beats.
- Use shorter scenes with strong thresholds and one interaction at a time.
- Avoid stacked card dumps.
- Media should remain atmospheric and inspectable, not tiny thumbnails.
- Sticky controls may appear only when they protect flow, such as audio controls during clips.
- Navigation should collapse into a minimal chapter control, not a full app drawer.
- Flow visualization should become a vertical emotional arc, not a shrunken desktop timeline.
- Playlist tracks should reveal progressively in cinematic beats, not as a dense list.
- Type pacing should be authored for thumb-scroll rhythm: fewer simultaneous text blocks, more phrase-level reveals, and no compressed wall of copy.
- Gesture rhythm matters. Use scroll, tap, hold-to-preview, and swipe only when they feel native to the emotional moment.
- Transition compression should preserve feeling while shortening duration. Mobile fades can be shorter, but they must not become abrupt.
- Atmospheric retention matters: keep grain, vignettes, media, and chapter thresholds present even when layouts simplify.
- Avoid viewport-height traps where a user gets stuck in an over-composed scene with no clear next gesture.

Mobile should feel like a handheld film chapter.

## Opening Intelligence Requirement

The first product minute must include a concrete signal of intelligence. Acceptable patterns:

- A one-question musical memory prompt that reshapes the next hero line.
- A subtle session state creation moment that changes chapter language.
- A short clip reaction that immediately alters the first identity phrase.
- A Spotify-aware return state for connected users.

Unacceptable patterns:

- More than one screen of pure manifesto before any interaction tension.
- A hero that could belong to any cinematic AI/music brand.
- Product explanation without behavioral curiosity.

## Clarity And Payoff Rules

SonicDNA can be mysterious, but it must repeatedly prove itself.

Each major scene needs one concrete payoff:

- Recognition: the system asks or responds in a way that feels musically personal.
- Identity: the user sees an emotionally legible self-portrait.
- Listening Interview: each answer visibly deepens the system's understanding.
- Private Sync: Spotify changes the identity or playlist framing.
- Emotional Session: intent choices produce a playlist with a named emotional premise.
- Flow: sequence order feels purposeful.
- Worlds: unfamiliar tracks feel connected rather than random.
- Memory: prior sessions become meaningful material for return, comparison, or sharing.

Avoid abstract copy that cannot be traced to an interaction or backend capability.

Every abstract emotional scene must resolve into a concrete emotionally meaningful outcome before the next major chapter asks for attention. Valid outcomes include a playlist, an emotional insight, a rediscovered pattern, a memory resurfacing, a surprising crossover, or a recognized emotional tendency. The product must periodically prove: "I learned something meaningful about you."

## Memory Restraint Rules

Memory should feel haunting, lightweight, and discoverable. It must not become therapeutic journaling infrastructure.

Rules:

- Memory can deepen after the user has generated or saved something, but it should not slow first-use onboarding.
- Memory prompts should be optional and sparse.
- Avoid long written reflection inputs unless explicitly requested by the user.
- Favor resurfacing and revisiting over journaling and analysis.
- Keep replay spontaneous: "return to this version" should take less effort than writing about it.

## Invisible Orientation Systems

Topology and diagnostics stay implicit, but users still need subconscious orientation.

Use invisible orientation cues:

- Scene labels as chapter markers, not nav tabs.
- Environmental shifts that imply emotional movement.
- Progressive track reveal counts that imply movement without becoming progress bars.
- Directional language: closer, farther, across, return, threshold, afterglow.
- Anchor tracks that orient unfamiliar discoveries.
- Stable chapter order and repeated visual motifs.

Do not leave users disoriented in pure abstraction. Orientation should be felt through pacing and language, not exposed as infrastructure.

## Cross-Scene Review Gate

No scene may be implemented or reviewed in visual isolation. Every scene completion must be checked against:

- Previous and next scene pacing.
- Transition continuity.
- Typography rhythm consistency.
- Motion density.
- Emotional contrast.
- Global emotional state behavior.
- Mobile choreography.
- Performance impact.

If a scene looks strong alone but weakens the journey, revise the scene.

## Performance As Emotional Language

Performance is part of the cinematic feeling. A cinematic experience with unstable frame pacing loses credibility immediately.

Hard requirements:

- Maintain smooth scroll and animation on mid-range mobile devices.
- Prefer CSS transforms and opacity over layout-affecting animation.
- Avoid stacking multiple large videos in active viewport memory.
- Lazy-load non-critical media and scenes below the fold.
- Respect `prefers-reduced-motion`.
- Avoid oversized typography reflow during scroll.
- Keep fixed/sticky elements minimal.
- Test for scroll jank after each phase, not only at the end.
- Use static atmospheric fallbacks when video or motion would overload mobile GPU.

Explicit cinematic budgets before media/runtime implementation:

- Desktop target: 60 FPS.
- Mobile target: at least 45 FPS on mid-range devices.
- Max concurrent animated layers: 6 desktop, 3 mobile.
- Max simultaneous video/media surfaces: 2 desktop, 1 mobile.
- Blur/filter budget: 0px default on desktop and mobile.
- Mobile fallback threshold: under 768px uses static atmosphere or low-motion choreography.
- Reduced motion: degrade to static atmosphere, opacity-only transitions, no autoplaying media, no filter effects, no scroll traps.
- Fixed navigation and atmospheric layers must remain minimal and should never compete with the scene content.

## Phase 1.5 Structural Rhythm Gate

Before implementing the split emotional runtime, add an intermediate structural rhythm phase. This phase stabilizes the cinematic journey before state architecture encodes behavior assumptions.

Scope:

- Scene scaffolding in the approved order.
- Chapter pacing and transition continuity.
- Silence zones and spacing cadence.
- Mobile choreography and navigation rhythm.
- Typography flow across scenes.
- A restrained atmospheric moving media layer restored from the original `/website` aesthetic.
- Mocked emotional states only.
- No backend APIs, persistent runtime logic, playlist generation, Spotify sync, audio orchestration, or real emotional inference.

Phase 1.5 should use mocked state as a visual and behavioral rehearsal layer. It may suggest how tone, intensity, and chapter rhythm feel, but it must not persist state or imply final backend behavior.

The moving media layer should behave like environmental cinematography, not animated decoration. It should use at most one active moving surface, move slowly, sit beneath the content, preserve silence zones, and degrade to static atmospheric imagery for mobile and reduced-motion contexts.

## Warmth And Humanity

The tone must not become too solemn or self-serious. SonicDNA is intimate and cinematic, but it should still feel human.

Add small moments of warmth, surprise, and subtle playfulness:

- Gentle microcopy that feels observant rather than grandiose.
- Occasional relief after intense emotional scenes.
- Song-specific humanity in playlist and Memory moments.
- A sense that the system is listening with curiosity, not performing reverence.

Avoid jokes that break the atmosphere, but do not let the product become emotionally distant.

## Implementation Sequencing Discipline

Implementation must proceed in this order to avoid visual drift and rework:

1. Phase 1: global shell, typography, spacing, design tokens, motion primitives, and cinematic infrastructure.
2. Phase 1.5: cinematic structural rhythm with scene scaffolding, mocked emotional states, chapter pacing, silence zones, navigation rhythm, spacing cadence, typography flow, and mobile choreography.
3. Phase 2: split runtime architecture for session/backend, emotional, scene, audio, and async/network state.
4. Phase 3: backend integrations and typed API client.
5. Phase 4: media orchestration layer for asset loading, unloading, mobile fallbacks, GPU budgets, and playback arbitration.
6. Phase 5: motion refinement and scene transition polish.
7. Phase 6: audio, clip behavior, and atmospheric polish.
8. Phase 7: performance optimization, mobile choreography, and browser verification.

Do not build dense scene-specific interactions before the shared shell, state model, and motion primitives exist. Do not polish audio before the core emotional state and backend flows work.

Execution quality now matters more than new ideas. Implementation should favor consistency, restraint, repeatable primitives, and polish over adding additional concepts.

## Component Architecture

Keep files focused and modular.

Recommended structure:

```txt
website/src/
  App.tsx
  styles/
    cinematic.css
  lib/
    api.ts
    storage.ts
    emotionalCopy.ts
    flowProjection.ts
  runtime/
    SonicRuntimeProvider.tsx
    asyncNetworkReducer.ts
    audioRuntimeReducer.ts
    emotionalRuntimeReducer.ts
    sceneRuntimeReducer.ts
    sessionBackendReducer.ts
    types.ts
  media/
    mediaOrchestrator.ts
  motion/
    transitions.ts
    Reveal.tsx
    SceneBoundary.tsx
  components/
    cinematic/
      ChapterNav.tsx
      CinematicButton.tsx
      EditorialLabel.tsx
      MediaScene.tsx
      TextReveal.tsx
    audio/
      ClipPlayer.tsx
      AmbientAudioController.tsx
    scenes/
      RecognitionScene.tsx
      IdentityScene.tsx
      ListeningInterviewScene.tsx
      PrivateSyncScene.tsx
      EmotionalSessionScene.tsx
      FlowScene.tsx
      WorldsScene.tsx
      MemoryScene.tsx
```

The current `WordsPullUp`, `WordsPullUpMultiStyle`, and `ScrollTextReveal` patterns should be retained or generalized, not discarded.

## API Client Design

Create a typed API client for the frontend:

- `createSession(displayName?: string)`
- `getSpotifyStatus(sessionToken: string)`
- `beginSpotifyLogin(sessionToken: string, returnTo: string)`
- `disconnectSpotify(sessionToken: string)`
- `getRoundOneClips(sessionKey: string, count?: number)`
- `getAdaptiveClips(existingRatings, roundNumber, sessionKey)`
- `getAdaptiveQuestion(previousAnswers, clipRatings, coveredDimensions, askedQuestions)`
- `analyzeAdaptive(answers, clipRatings, region, sessionToken)`
- `saveSnapshot(sessionToken, result, region)`
- `generateTrialPlaylist(payload)`
- `generateSessionPlaylist(clusterId, payload, queryOptions)`
- `getRegions()`
- `getRecommendations(clusterId, regionKey, limit)`
- `createShare(sessionToken, snapshotId?)`
- `getShare(shareCode)`
- `compareCompatibility(sessionToken, shareCode, displayName?)`

The API client should keep raw transport details out of scene components.

## Testing Strategy

Use test-first implementation for new behavior.

Priority tests:

- API client builds the correct requests and handles error envelopes.
- Session reducer preserves emotional state and avoids losing identity after Spotify sync or playlist generation.
- Flow projection converts playlist tracks into emotional chapter data without exposing raw diagnostics.
- Interview state handles adaptive question completion and clip ratings.
- Share state stores share code and URL without leaking internal user IDs.
- Component smoke tests verify scenes render primary emotional content from state.

Visual verification:

- Run `npm run build`.
- Run the Vite dev server.
- Use the in-app browser to inspect desktop and mobile viewports.
- Capture screenshots of hero, identity, interview, playlist, flow, worlds, memory.
- Check console errors.
- Confirm text does not overlap or overflow on mobile.
- Confirm motion is restrained and not visually noisy.

## Non-Goals

- No routed dashboard product structure.
- No generic SaaS navigation.
- No analytics-heavy identity display.
- No equally weighted backend feature grid.
- No visible raw embeddings, topology internals, graph adjacency, or diagnostic score dumps.
- No generic AI visuals.
- No startup landing-page copy.
- No redesign of the existing visual identity.

## Success Criteria

The final frontend succeeds when:

- It feels like one evolving emotional film.
- The current `/website` cinematic language is recognizably preserved.
- Identity and Listening Interview feel psychologically intimate.
- Spotify sync feels personal and trust-building.
- Playlist generation feels like entering an emotional state.
- Flow communicates movement and sequencing without analytics heaviness.
- Worlds feels like emotional and cultural exploration.
- Memory feels like a core relationship layer, not an add-on.
- Mobile preserves cinematic pacing instead of collapsing into stacked app UI.
- Backend intelligence feels present, human, and alive without being over-explained.
