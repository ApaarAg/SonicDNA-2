# SonicDNA Database And Persistence Audit

Date: 2026-05-08

Scope: static audit of the backend persistence architecture. This document does not propose or perform migrations. It inventories SQL tables, local files, runtime caches, session artifacts, embedding caches, graph caches, playlist history, Spotify storage, and user profile storage visible in the current repository.

Criticality labels:

- CANONICAL: source of truth for durable product state.
- DERIVED: recomputable from canonical state or external APIs, but currently persisted.
- CACHE: transient acceleration layer.
- SESSION: identity, queue, token, or short-lived workflow state.
- LEGACY: implemented or present, but not on the current primary path.

## Executive Summary

The backend has a SQL Server-centric core with several additive persistence layers around it. `users`, `genome_snapshots`, `spotify_connections`, `share_links`, `user_locations`, and `email_queue` are durable product state. Spotify tracks, generated playlists, genome comparisons, Graphify output, embedding caches, graph caches, and Spotify search caches are derived or cache-like state.

The main architectural risk is that canonical and derived state are not cleanly separated. Spotify taste is fetched live, cached into `spotify_tracks`, rehydrated into taste profiles, then blended into snapshots. Playlists can be generated without being saved to `generated_playlists`. Session identity exists both as SQL rows and client-side signed tokens. Graph and embedding state are useful but entirely process-local unless exported by Graphify.

## SQL Server Tables

### users

- Purpose: Canonical user identity for anonymous listeners and email-attached users.
- Written by: `get_or_create_user`, `create_session_user`, `get_or_create_session_user`, `attach_email_to_session_user`, session endpoints in `main.py`.
- Read by: `get_user_by_id`, `find_user_by_display_name`, `latest_snapshot_id_for_user`, share links, comparisons, leaderboard queries, Spotify connection flows, retention scheduler, email notifications.
- Criticality: CANONICAL.
- Expiration behavior: None. Anonymous users persist indefinitely; `last_seen` is refreshed but not used for retention or cleanup.
- Redundancy risks: Session users can later be merged into email users; fallback anonymous emails like `anonymous+<uuid>@sonicdna.local` act as identity stand-ins.
- Architectural smells: Table creation is not visible in the current migration helper, but many modules assume it exists. Merge logic updates several dependent tables manually, with `pyodbc.Error` swallowed for optional tables.

### genome_snapshots

- Purpose: Canonical record of completed SonicDNA profiles, genome feature vectors, archetype identity, region, and reasoning text.
- Written by: `save_genome_snapshot`, `/user/save_snapshot`.
- Read by: `get_user_timeline`, `get_snapshot_by_id`, `latest_snapshot_id_for_user`, compatibility flow, retention scheduler, leaderboard aggregation, share link joins, playlist generation.
- Criticality: CANONICAL.
- Expiration behavior: None. Snapshots are append-only in inspected code.
- Redundancy risks: Stores derived archetype fields and raw feature columns; current profile responses also carry similar generated structures before persistence.
- Architectural smells: Base table creation is not in `migrate_database`; only `created_at` is conditionally added. `taken_at` and `created_at` coexist as ordering fields.

### spotify_connections

- Purpose: Stores Spotify OAuth account link and access/refresh tokens per user.
- Written by: `save_spotify_connection`, `update_spotify_tokens`, Spotify callback and refresh flow.
- Read by: `get_spotify_connection`, `_ensure_spotify_access_token`, `_load_spotify_taste_profile`, `/spotify/status`, `/spotify/login`.
- Criticality: SESSION.
- Expiration behavior: `token_expires_at` controls token refresh. Rows are not deleted on expiration or disconnect in inspected code.
- Redundancy risks: Access tokens also exist temporarily in memory during request handling.
- Architectural smells: Sensitive tokens are stored directly in SQL without visible encryption-at-rest handling. One connection per `user_id` is expected by lookup code, but uniqueness is not enforced in the shown DDL.

### spotify_tracks

- Purpose: Cached/imported Spotify top tracks with artist metadata, genres, audio feature proxies, popularity, and time range.
- Written by: `save_spotify_tracks`, `_load_spotify_taste_profile`.
- Read by: `get_user_spotify_tracks`, `_cached_spotify_taste_profile`, playlist generation, Spotify status, profile blending.
- Criticality: DERIVED.
- Expiration behavior: `save_spotify_tracks` deletes and replaces rows for a `user_id` and `time_range`. No time-based invalidation; `imported_at` is only ordering metadata.
- Redundancy risks: Duplicates external Spotify state and overlaps with `generated_playlists.tracks`. It is also used as a fallback taste profile when OAuth fetch fails.
- Architectural smells: Cache behaves like durable profile storage. The `is_top_track` flag is always defaulted from input and is not enough to distinguish recent/top/source semantics.

### generated_playlists

- Purpose: Intended durable playlist history with playlist JSON and optional Spotify playlist id.
- Written by: `save_generated_playlist`.
- Read by: `get_user_playlists`.
- Criticality: LEGACY.
- Expiration behavior: None.
- Redundancy risks: Stores full track JSON that overlaps Spotify track cache and live playlist responses.
- Architectural smells: Current playlist generation paths do not call `save_generated_playlist`, so playlist persistence exists but is not consistently used. JSON blobs make later schema evolution and querying difficult.

### genome_comparisons

- Purpose: Stores social compatibility results between two snapshots/users.
- Written by: `save_genome_comparison`, `compare_internal` in `main.py`.
- Read by: `get_genome_comparison`, compatibility routes, notifications indirectly through comparison flow.
- Criticality: DERIVED.
- Expiration behavior: None; latest comparison is selected by `created_at`.
- Redundancy risks: Fully derived from two genome snapshots plus comparison algorithm, but persisted as JSON and scalar scores.
- Architectural smells: Algorithm changes will not invalidate old comparison rows. Direction is normalized by read query, but uniqueness of user/snapshot pair is not enforced.

### share_links

- Purpose: Durable viral/social invite state linking inviter snapshot to invitee completion.
- Written by: `create_share_links_table`, `generate_share_link`, `get_share_link_details` increments access count, `complete_share_link`, `invalidate_share_link`, session merge logic.
- Read by: share routes, compatibility compare by share code, analytics, email notifications.
- Criticality: CANONICAL.
- Expiration behavior: `expires_at` and status are checked on read; expired links are not automatically updated unless manually invalidated.
- Redundancy risks: Stores both `status` and temporal facts (`expires_at`, `completed_at`) that can disagree.
- Architectural smells: `get_share_link_details` mutates `times_accessed` on every read, including internal reads after completion. Hardcoded returned full URL uses a placeholder in the helper while the API constructs another URL from `SONIC_SHARE_BASE_URL`.

### user_locations

- Purpose: Stores user city/country/region/ip for leaderboard and geographic archetype analytics.
- Written by: `create_city_tracking_table`, `save_user_location`, `/location`.
- Read by: city leaderboard, archetype strongholds, global/city distribution comparisons.
- Criticality: CANONICAL.
- Expiration behavior: One current row per user is updated in place; no deletion or historical retention policy.
- Redundancy risks: Location is not linked to a snapshot, so current location is reused across all historical genome snapshots.
- Architectural smells: Stores `ip_address` without visible retention or privacy policy. Leaderboard queries join latest genome snapshots but use mutable location state.

### email_queue

- Purpose: Durable email work queue for share notifications, comparison notifications, and retention emails.
- Written by: `migrate_email_system`, `queue_email`, email notification helpers, retention scheduler.
- Read by: `process_email_queue`, retention scheduler `has_recent_retention_email`.
- Criticality: SESSION.
- Expiration behavior: Pending emails retry while `retry_count < 3`; failed/sent rows remain indefinitely.
- Redundancy risks: Email body HTML stores denormalized user/profile/share information at queue time.
- Architectural smells: Queue lifecycle is manual via `/admin/process_email_queue` or script. Failed rows do not automatically re-enter pending state after transient SMTP issues.

## SQL Indexes And Schema Side Effects

### IX_spotify_tracks_user

- Purpose: Speeds Spotify track lookup by user.
- Written by: `migrate_database`.
- Read by: SQL optimizer for `get_user_spotify_tracks`.
- Criticality: DERIVED.
- Expiration behavior: Follows table lifecycle.
- Redundancy risks: None significant.
- Architectural smells: No compound index on `(user_id, time_range, imported_at)` despite query filtering and ordering on those fields.

### IX_comparisons_users

- Purpose: Speeds comparison lookup by user pair.
- Written by: `migrate_database`.
- Read by: SQL optimizer for `get_genome_comparison`.
- Criticality: DERIVED.
- Expiration behavior: Follows table lifecycle.
- Redundancy risks: None significant.
- Architectural smells: Query is bidirectional but index is directional; may not help equally for reversed pairs.

### IX_share_code

- Purpose: Unique lookup for share codes.
- Written by: `create_share_links_table`.
- Read by: share code lookups and completion.
- Criticality: DERIVED.
- Expiration behavior: Follows table lifecycle.
- Redundancy risks: Duplicates table-level unique constraint if both are present.
- Architectural smells: Index and column unique constraint both express uniqueness.

### IX_user_city

- Purpose: Speeds city/country leaderboard lookups.
- Written by: `create_city_tracking_table`.
- Read by: leaderboard queries.
- Criticality: DERIVED.
- Expiration behavior: Follows table lifecycle.
- Redundancy risks: None significant.
- Architectural smells: Does not cover `user_id`, though writes search by `user_id`.

### IX_email_queue_status

- Purpose: Speeds pending email queue processing by status and created time.
- Written by: `migrate_email_system`.
- Read by: SQL optimizer for `process_email_queue`.
- Criticality: DERIVED.
- Expiration behavior: Follows table lifecycle.
- Redundancy risks: None significant.
- Architectural smells: Does not include `retry_count`, which is part of the pending selection.

## Local Persisted Files And Configuration

### backend/.ENV

- Purpose: Runtime configuration and secrets for database, Spotify, SMTP, Groq, frontend URLs.
- Written by: developer/operator outside application runtime.
- Read by: `database.py`, `Email_service.py`, `main.py`, `spotify_oauth_service.py`, and service initialization.
- Criticality: CANONICAL.
- Expiration behavior: None.
- Redundancy risks: Multiple modules load the same file independently; root-level legacy service uses generic `load_dotenv()`.
- Architectural smells: Secrets are in a repo-local file. Rotation and environment separation are manual.

### pass.txt

- Purpose: Unmanaged local secret-like file present at repository root.
- Written by: developer/operator outside inspected backend code.
- Read by: No backend reader found in inspected code.
- Criticality: LEGACY.
- Expiration behavior: None.
- Redundancy risks: May duplicate secrets already in `.ENV`.
- Architectural smells: Ambiguous sensitive artifact in project root with no owner or lifecycle.

### backend/data/clip_features.json

- Purpose: Static metadata for calibration/adaptive audio clips.
- Written by: developer/data preparation outside runtime.
- Read by: `engine.py`, `main.py`, clip recommendation endpoints.
- Criticality: CANONICAL.
- Expiration behavior: None; versioned by file replacement only.
- Redundancy risks: Loaded independently by `engine.py` and `main.py` into separate process memory.
- Architectural smells: Static data is local-file based and tightly coupled to clip file names/paths.

### backend/data/clips/**

- Purpose: Static MP3 assets for clip-rating calibration and adaptive clip flows.
- Written by: developer/data preparation outside runtime.
- Read by: FastAPI static mount `/audio`, `engine.py` clip selection.
- Criticality: CANONICAL.
- Expiration behavior: None.
- Redundancy risks: Some category folders appear duplicated or near-duplicated, such as ambient folder name variants.
- Architectural smells: Audio taxonomy is encoded in folder names; no manifest-backed validation that every audio file has feature metadata.

### backend/data/user_genome_clustered.csv

- Purpose: Static clustered user genome dataset used by `GenomeEngine`.
- Written by: offline data preparation.
- Read by: `GenomeEngine.__init__`.
- Criticality: CANONICAL.
- Expiration behavior: None.
- Redundancy risks: Represents a separate static user/profile universe from SQL `users` and `genome_snapshots`.
- Architectural smells: The engine can serve dataset profiles by `user_id` that are not the same identity namespace as production SQL users.

### backend/data/user_genre_similarity.csv

- Purpose: Static genre similarity matrix for cluster genre averages.
- Written by: offline data preparation.
- Read by: `GenomeEngine.__init__`.
- Criticality: DERIVED.
- Expiration behavior: None.
- Redundancy risks: Derived from the same offline corpus as clustered genome CSV.
- Architectural smells: Recomputed cluster averages are process-local and not version-stamped.

### graphify-out/graph.json

- Purpose: Persisted Graphify knowledge graph of code structure.
- Written by: `graphify update .`.
- Read by: Graphify CLI/query tooling and project rules.
- Criticality: DERIVED.
- Expiration behavior: Manual refresh only.
- Redundancy risks: Duplicates repository structure and code symbols.
- Architectural smells: Can become stale after code edits unless update is run.

### graphify-out/GRAPH_REPORT.md

- Purpose: Human-readable Graphify architecture report.
- Written by: `graphify update .`.
- Read by: agents and developers before architecture/codebase questions.
- Criticality: DERIVED.
- Expiration behavior: Manual refresh only.
- Redundancy risks: Summarizes graph state that is already in `graph.json`.
- Architectural smells: Staleness risk and encoding artifacts visible in generated text.

### graphify-out/graph.html

- Purpose: Interactive visualization of the Graphify graph.
- Written by: `graphify update .`.
- Read by: developers in browser.
- Criticality: DERIVED.
- Expiration behavior: Manual refresh only.
- Redundancy risks: Duplicates `graph.json` in rendered form.
- Architectural smells: Large generated artifact in repo workspace.

### graphify-out/manifest.json

- Purpose: Graphify file/entity manifest.
- Written by: `graphify update .`.
- Read by: Graphify tooling.
- Criticality: DERIVED.
- Expiration behavior: Manual refresh only.
- Redundancy risks: Duplicates scan metadata.
- Architectural smells: Same staleness risk as graph output.

### graphify-out/cache/ast/**

- Purpose: Graphify AST extraction cache.
- Written by: Graphify update/extract commands.
- Read by: Graphify tooling for incremental rebuilds.
- Criticality: CACHE.
- Expiration behavior: Tool-managed; no app-level lifecycle.
- Redundancy risks: Duplicates parsed source structure.
- Architectural smells: Generated cache is adjacent to app runtime files.

### .agent/rules/graphify.md and .agent/workflows/graphify.md

- Purpose: Agent workflow/configuration persistence for Graphify behavior.
- Written by: Graphify install/setup.
- Read by: agent tooling, not backend runtime.
- Criticality: DERIVED.
- Expiration behavior: Manual.
- Redundancy risks: Duplicates Graphify usage instructions.
- Architectural smells: Developer tooling state lives inside app repository.

## Runtime In-Memory Stores And Caches

### EmbeddingRanker.cache

- Purpose: Maps profile/query text to sentence-transformer embeddings.
- Written by: `EmbeddingRanker.embed_texts_cached`.
- Read by: embedding ranking, user profile encoding, track embedding evaluation, graph construction.
- Criticality: CACHE.
- Expiration behavior: Clears entire cache when `cache_limit` of 10,000 would be exceeded; resets on process restart.
- Redundancy risks: Same semantic embedding may be recomputed across processes and after restarts.
- Architectural smells: Cache key is full text, so trace/profile text changes invalidate all prior embeddings. No memory size accounting beyond entry count.

### SpotifyService.search_cache

- Purpose: Caches Spotify API search pages by query/market/limit/offset.
- Written by: `_cache_set` in `spotify_service_fixed.py`.
- Read by: `_search_tracks_page`.
- Criticality: CACHE.
- Expiration behavior: 300-second TTL.
- Redundancy risks: Duplicates Spotify API state and overlaps with regional cache.
- Architectural smells: Process-local only; no cache bound or eviction except TTL on read.

### SpotifyService.regional_cache

- Purpose: Caches final regional discovery result by region, cluster, and requested limit.
- Written by: `_regional_cache_set`.
- Read by: `search_regional_tracks`.
- Criticality: CACHE.
- Expiration behavior: 120-second TTL.
- Redundancy risks: Stores formatted tracks that may later be persisted into playlists or Spotify track cache.
- Architectural smells: Empty results during cooldown are cached, which can mask recovery for the TTL.

### SpotifyService.access_token and token_expires_at

- Purpose: Client-credentials Spotify API token for app-owned search calls.
- Written by: `_authenticate`.
- Read by: `_make_request` and search.
- Criticality: SESSION.
- Expiration behavior: Refreshes when `time.time() >= token_expires_at`; value resets on process restart.
- Redundancy risks: Separate from user OAuth tokens in `spotify_connections`.
- Architectural smells: Service has two parallel Spotify auth systems: app credentials in memory and user OAuth in SQL.

### SpotifyService.search_cooldown_until

- Purpose: Process-local backoff after Spotify 429 search responses.
- Written by: `_make_request` on rate-limit response.
- Read by: `_make_request` and `search_regional_tracks`.
- Criticality: SESSION.
- Expiration behavior: 60-second cooldown.
- Redundancy risks: None significant.
- Architectural smells: Not coordinated across multiple workers.

### UserProfileEncoder._default_encoder

- Purpose: Module-level singleton that owns an embedding ranker when one is not passed in.
- Written by: `_get_default_encoder`.
- Read by: `get_user_embedding`.
- Criticality: CACHE.
- Expiration behavior: Process lifetime.
- Redundancy risks: May instantiate a separate SentenceTransformer/embedding cache from `SpotifyService.embedding_ranker`.
- Architectural smells: Multiple embedding rankers can coexist with independent caches.

### TrackGraph._default_graph

- Purpose: Optional module-level semantic track graph singleton.
- Written by: `build_default_graph`.
- Read by: `get_default_graph`.
- Criticality: CACHE.
- Expiration behavior: Process lifetime; rebuilt manually.
- Redundancy risks: Duplicates per-request graph construction in playlist exploration flow.
- Architectural smells: No version key tying graph to the track corpus or embedding profile text.

### Per-request TrackGraph in playlist exploration

- Purpose: Temporary graph over selected playlist tracks and exploration candidates.
- Written by: `PlaylistGenerator._inject_controlled_exploration`.
- Read by: `exploration_engine.inject_exploration_tracks`.
- Criticality: CACHE.
- Expiration behavior: Request lifetime.
- Redundancy risks: Recomputes embeddings/graph edges that may already be in ranker and graph caches.
- Architectural smells: Useful for coherence but expensive relative to playlist size if candidate pools grow.

### PlaylistGenerator.recently_served_track_ids

- Purpose: Process-local recent-track memory by region to reduce immediate repetition.
- Written by: `_remember_served_tracks`.
- Read by: `_apply_recent_memory_penalty`.
- Criticality: CACHE.
- Expiration behavior: Keeps a fixed recent window of 20 per region; resets on process restart.
- Redundancy risks: Overlaps with durable playlist history concept but is not tied to users.
- Architectural smells: Global by region, not by user/session; can cross-contaminate recommendations between users in the same process.

### PlaylistGenerator.request_serial_by_region

- Purpose: Process-local counter used to seed request diversity.
- Written by: `_request_seed`.
- Read by: `_apply_request_seeded_diversity`.
- Criticality: SESSION.
- Expiration behavior: Process lifetime; resets on restart.
- Redundancy risks: None significant.
- Architectural smells: Uses time and process-local serial for deterministic-ish diversity; not reproducible across workers.

### CLIP_FEATURES in main.py and _CLIP_FEATURES in engine.py

- Purpose: Process-local copies of `clip_features.json`.
- Written by: module import.
- Read by: clip endpoints and analysis helpers.
- Criticality: CACHE.
- Expiration behavior: Process lifetime; file changes require reload/restart.
- Redundancy risks: Same JSON file loaded twice into separate globals.
- Architectural smells: No consistency check between the two loaders.

### GenomeEngine dataframes and computed cluster_genre_avg

- Purpose: Process-local static data loaded from CSVs and precomputed cluster genre averages.
- Written by: `GenomeEngine.__init__`.
- Read by: `get_profile` and cluster/profile helpers.
- Criticality: CACHE.
- Expiration behavior: Process lifetime; CSV changes require service restart.
- Redundancy risks: Offline dataset can conflict with SQL user identity/timeline data.
- Architectural smells: Static offline data and live SQL state are both treated as user/profile sources.

## Session Artifacts

### Signed SonicDNA session_token

- Purpose: Client-held bearer-like token encoding `user_id` plus HMAC signature.
- Written by: `make_session_token`, `issue_public_session`.
- Read by: `resolve_session_token`, `resolve_payload_user`, most session-scoped endpoints.
- Criticality: SESSION.
- Expiration behavior: None. Token remains valid as long as secret and user row remain valid.
- Redundancy risks: Duplicates `user_id` in API payloads; `resolve_payload_user` falls back to raw `user_id`.
- Architectural smells: No token expiry or rotation metadata. Uses `GROQ_API_KEY` as fallback signing secret if `SESSION_TOKEN_SECRET` is missing, coupling unrelated secret domains.

### Spotify OAuth state parameter

- Purpose: Encodes SonicDNA session token, return URL, timestamp, and nonce during Spotify OAuth.
- Written by: `SpotifyOAuthService.make_state`.
- Read by: `SpotifyOAuthService.parse_state`, Spotify callback.
- Criticality: SESSION.
- Expiration behavior: Timestamp is included, but no expiration check was found in parsed-state usage.
- Redundancy risks: Carries session token through redirect flow.
- Architectural smells: Nonce is not persisted server-side, so replay protection is limited to signed state integrity.

### Frontend localStorage: sonic_session_token

- Purpose: Browser-side persistence of the signed SonicDNA session token.
- Written by: `_ensureSessionUser`, email update/save flows in `frontend/index.html`.
- Read by: frontend session, timeline, Spotify, save, playlist, share flows.
- Criticality: SESSION.
- Expiration behavior: None until manual sign-out/localStorage removal.
- Redundancy risks: Mirrors SQL user identity and server-issued token state.
- Architectural smells: Persistent bearer token in localStorage increases exposure to XSS. No server-side revocation list.

### Frontend localStorage: sonic_display_name, sonic_profile_code, sonic_user_email

- Purpose: Browser-side cached identity display values.
- Written by: frontend session and email update flows.
- Read by: frontend identity panel and display logic.
- Criticality: CACHE.
- Expiration behavior: Manual removal/sign-out.
- Redundancy risks: Mirrors `users` table fields.
- Architectural smells: Can become stale after server-side merge or email/name update elsewhere.

### Frontend in-memory state: _currentSessionToken, _currentResult, _currentResultSaved

- Purpose: Runtime UI session and current quiz/profile state.
- Written by: frontend flow.
- Read by: frontend save/timeline/share/playlist flows.
- Criticality: SESSION.
- Expiration behavior: Browser page lifetime.
- Redundancy risks: Mirrors localStorage and server state.
- Architectural smells: Unsaved profile results can exist only in browser memory until `/user/save_snapshot`.

## Playlist History And Recommendation Traces

### Live playlist response tracks

- Purpose: Generated playlist returned by API.
- Written by: `PlaylistGenerator.generate_regional_genome_playlist`, `generate_pure_discovery_playlist`, trial/session endpoints.
- Read by: frontend immediately; optionally by caller if saved externally.
- Criticality: DERIVED.
- Expiration behavior: Request/response lifetime unless explicitly persisted elsewhere.
- Redundancy risks: Can contain full track objects, recommendation traces, explanation metadata, Spotify URLs, and source tags that overlap multiple stores.
- Architectural smells: Generated playlist is not automatically saved to `generated_playlists`.

### generated_playlists.tracks JSON

- Purpose: Intended durable playlist history.
- Written by: `save_generated_playlist`.
- Read by: `get_user_playlists`.
- Criticality: LEGACY.
- Expiration behavior: None.
- Redundancy risks: Full denormalized track JSON duplicates Spotify cache and live recommendation output.
- Architectural smells: Current code path appears disconnected from primary playlist routes.

### recommendation_trace fields on track dicts

- Purpose: Debug/explanation trace for recommendation scoring contributions.
- Written by: `PlaylistGenerator._score_tracks_by_genome`, `_apply_user_embedding_similarity`, `_apply_graph_flow_reranking`, `_attach_final_trace`.
- Read by: `explanation_engine`.
- Criticality: DERIVED.
- Expiration behavior: Response/request lifetime unless playlist JSON is saved later.
- Redundancy risks: If saved inside generated playlist JSON, it will freeze algorithm-specific internal scores.
- Architectural smells: Trace is embedded into mutable track dictionaries rather than a separate debug envelope.

### exploration_meta and exploration flags

- Purpose: Marks controlled exploration injection and its scoring rationale.
- Written by: `exploration_engine`.
- Read by: `explanation_engine`, API clients if returned.
- Criticality: DERIVED.
- Expiration behavior: Response/request lifetime unless saved.
- Redundancy risks: Duplicates graph/embedding score details.
- Architectural smells: Same mutable-track-dict concern as recommendation traces.

## Spotify Storage

### User OAuth profile data in spotify_connections

- Purpose: Durable per-user authorization to fetch Spotify taste.
- Written by: callback and token refresh.
- Read by: OAuth status, taste loading, token refresh.
- Criticality: SESSION.
- Expiration behavior: Token-level expiration; row-level no expiration.
- Redundancy risks: App also uses client-credentials token in memory for search.
- Architectural smells: Sensitive token persistence and no disconnect/delete flow found.

### User Spotify top tracks in spotify_tracks

- Purpose: Cached taste profile source.
- Written by: `_load_spotify_taste_profile`.
- Read by: fallback taste profile, playlist generation, profile blending.
- Criticality: DERIVED.
- Expiration behavior: Replaced per `time_range` on new import; otherwise indefinite.
- Redundancy risks: External Spotify state, generated playlists, and explanation/taste summaries can all carry overlapping track metadata.
- Architectural smells: Called a cache but used like profile history with no TTL.

### App Spotify search caches

- Purpose: Reduce search API calls and smooth rate limits.
- Written by: `SpotifyService` in-memory caches.
- Read by: discovery search.
- Criticality: CACHE.
- Expiration behavior: 120-300 seconds.
- Redundancy risks: Overlaps with track candidate pools and Spotify tracks.
- Architectural smells: Per-process cache, no shared cooldown across workers.

## User Profile Storage

### users table

- Purpose: Durable identity, display name, email, last seen.
- Criticality: CANONICAL.
- Notes: Serves both anonymous and email-attached identities.

### genome_snapshots table

- Purpose: Durable evolving music genome and archetype timeline.
- Criticality: CANONICAL.
- Notes: Most profile behavior should ultimately anchor here.

### spotify_tracks table

- Purpose: Derived taste profile cache from Spotify.
- Criticality: DERIVED.
- Notes: Feeds profile blending and playlist generation.

### user_locations table

- Purpose: User profile extension for city leaderboard.
- Criticality: CANONICAL.
- Notes: Mutable current location, not historical snapshot location.

### frontend localStorage identity fields

- Purpose: Client-side identity convenience cache.
- Criticality: CACHE.
- Notes: Must not be treated as authoritative.

## Duplicate Persistence Paths

1. User identity exists as SQL `users`, signed session tokens, raw `user_id` payload fallback, frontend localStorage, and profile code display state.
2. Spotify taste exists as live OAuth fetches, `spotify_tracks`, `_cached_spotify_taste_profile`, `spotify_taste_influence` blended result metadata, and playlist track payloads.
3. Playlist state exists as live API responses, `generated_playlists.tracks` JSON, `PlaylistGenerator.recently_served_track_ids`, frontend current playlist UI state, and possible Spotify playlist IDs.
4. Genome/profile state exists as unsaved frontend `_currentResult`, `/user/save_snapshot` payloads, `genome_snapshots`, static `user_genome_clustered.csv`, and derived `spotify_taste_influence`.
5. Graph state exists as process-local `TrackGraph`, per-request exploration graphs, Graphify `graph.json`, Graphify AST cache, and graph reports.
6. Clip metadata is loaded in both `engine.py` and `main.py` from the same `clip_features.json`.
7. Email intent exists as immediate notification helper calls, durable `email_queue` rows, and retention scheduler de-duplication queries.
8. Share link status duplicates temporal state: `status`, `expires_at`, `completed_at`, and `times_accessed`.
9. Location analytics reuse mutable `user_locations` with historical `genome_snapshots`, creating a mixed current-vs-historical view.
10. Legacy root `spotify_service.py` and active `backend/spotify_service_fixed.py` represent two Spotify recommendation service implementations.

## Architectural Risks

1. Sensitive token storage: Spotify refresh/access tokens are persisted in SQL, and secrets are repo-local in `.ENV`; no encryption/rotation boundary is visible.
2. Non-expiring sessions: HMAC session tokens and browser localStorage sessions have no expiry, revocation, or issued-at validation.
3. Core table migration gap: `users` and `genome_snapshots` are assumed but not created by visible migration code.
4. Cache treated as source: `spotify_tracks` is named and operated as a cache but used as fallback profile state with no TTL.
5. Playlist persistence drift: `generated_playlists` exists but current playlist routes do not consistently write to it.
6. Anonymous-user merge fragility: Merge logic manually updates many tables and ignores missing-table errors, risking partial moves if new tables are added.
7. Process-local recommendation memory: recent-track suppression is global by region rather than per user/session.
8. Graph/embedding staleness: semantic profile changes alter embedding text, but old cached embeddings and graph artifacts have no schema/version marker.
9. Denormalized JSON blobs: playlist tracks and comparison details are persisted as opaque JSON, limiting consistency checks and migrations.
10. Mixed identity namespaces: static CSV `user_id` values and SQL user UUIDs coexist in `GenomeEngine`/API concepts.
11. Privacy retention: IP addresses, emails, Spotify tokens, and location data have no visible deletion lifecycle.
12. Generated trace leakage: recommendation/exploration traces can be embedded in returned track dicts and may later be saved as playlist JSON.
13. Duplicate DB connection config: `database.py` and `Email_service.py` each define their own SQL connection setup.
14. Read-with-side-effect: `get_share_link_details` increments `times_accessed`, including internal service reads.
15. Rate-limit cache semantics: empty Spotify results during cooldown are cached regionally, potentially hiding recovery.

## Recommended Cleanup Priorities

1. Document ownership of canonical tables and add a single migration source for `users` and `genome_snapshots`.
2. Separate canonical state from caches: define TTL/refresh policy for `spotify_tracks`, `generated_playlists`, and graph/embedding artifacts.
3. Introduce session expiry and a clear sign-out/revocation path for `session_token`.
4. Create a Spotify disconnect/delete flow and decide whether OAuth tokens require encryption or a secrets manager.
5. Decide whether `generated_playlists` is active product history or legacy; either wire it intentionally or mark it deprecated.
6. Move recent-playlist memory from process-global region memory to user/session-scoped state if it affects product behavior.
7. Version semantic embeddings/track profiles so cache invalidation is explicit after profile-builder changes.
8. Normalize or envelope recommendation traces so debug metadata does not become accidental durable playlist content.
9. Unify database connection configuration through `database.get_conn`; remove the duplicate connection builder in `Email_service.py`.
10. Add data retention policies for emails, IP/location rows, expired share links, failed email queue rows, and anonymous users.
11. Add uniqueness constraints for expected one-row-per-user stores such as `spotify_connections` and `user_locations`.
12. Add audit-safe tooling to list table row counts and stale cache ages without exposing secrets or token values.

