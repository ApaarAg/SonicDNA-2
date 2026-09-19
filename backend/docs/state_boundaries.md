# SonicDNA State Boundaries

Date: 2026-05-08

Scope: ownership and persistence boundaries for the existing semantic recommendation backend. This document defines architecture policy only. It does not rewrite schemas, run migrations, add storage engines, add Redis/vector databases, or introduce new product systems.

## Boundary Principles

SonicDNA state is split into three explicit layers:

1. **Canonical identity**: durable facts about who a user is and which completed product events belong to them. The primary source is SQL Server, anchored by `users` and durable child tables.
2. **Derived semantic state**: recomputable representations created from canonical state, static datasets, Spotify APIs, or recommendation algorithms. This state can be cached or persisted for convenience, but it must carry a refresh/invalidation story and must not become the only source of product truth.
3. **Ephemeral recommendation state**: request-scoped scoring, graph bonuses, exploration annotations, embedding intermediates, and debug traces. This state exists to explain or rank a response and must not be persisted as product history.

The owner of a state domain is the subsystem allowed to create, refresh, expire, and interpret that state. Other subsystems may read through owner APIs, but should not treat duplicated copies as authoritative.

## Generated Playlist Decision

`generated_playlists` is **legacy/derived storage under the current architecture**, not canonical product history.

Reasoning:

- Current primary playlist generation paths return live playlist responses and do not consistently call `save_generated_playlist`.
- The table stores full denormalized track JSON, which can accidentally include recommendation traces, exploration metadata, graph scores, source tags, and stale Spotify metadata.
- A generated playlist is recomputable from a genome snapshot, region, request settings, available Spotify catalog data, and the current recommendation algorithm. Because external catalog state and algorithms drift, the existing JSON should be treated as a historical convenience copy rather than an authoritative event log.

If the product later needs canonical playlist history, promote the concept deliberately: persist a user-visible playlist event with stable inputs, user-facing track identifiers, creation settings, and optional Spotify playlist id. Do not persist transient traces, graph scores, temporary embedding artifacts, or raw mutable candidate pools as part of that history.

## Never Persist

The following must never be written to durable SQL rows, local generated artifacts intended for retention, browser storage, or playlist history:

- Transient recommendation traces such as per-track `recommendation_trace`, score breakdowns, `final_rank_score`, `pre_exploration_rank`, and algorithm-specific ranking diagnostics.
- Ephemeral graph scores such as `graph_flow_bonus`, `graph_weight`, temporary adjacency weights, neighbor scores, and flow-rerank internals.
- Temporary embedding artifacts such as raw embedding vectors, request-local candidate embeddings, query embeddings, and sentence-transformer cache entries.
- Request-local exploration working state, including candidate pools, exploration eligibility calculations, and mutable exploration score internals.
- OAuth authorization `state` payloads after callback completion.
- Raw access tokens in frontend storage or URLs.
- Unsaved frontend quiz/profile results beyond the browser page lifetime unless the user explicitly saves a genome snapshot.

## Canonical Ownership Table

| Data domain | Owner subsystem | Canonical source of truth | Derived/recomputable state | Cache-only state | Session-only state | Expiration policy | Persistence policy | Allowed duplication boundaries |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Users | Identity/session subsystem in `database.py` and session routes in `main.py` | `users` SQL row: `id`, email/display fields, anonymous/email identity linkage, `last_seen` | Display labels, profile codes, identity summaries returned to clients | Frontend cached display name/email/profile code | Signed `session_token`, in-memory frontend current user | No current row expiry. Future cleanup may target abandoned anonymous users only after child-state retention is defined. | Persist canonical identity in SQL. Treat raw `user_id` payload fallback as compatibility only, not a second authority. | May duplicate `user_id` inside signed tokens, API responses, and localStorage for convenience. All writes must resolve back to `users.id`. |
| Genome snapshots | Profile/genome subsystem: quiz/clip analysis plus `save_genome_snapshot` | `genome_snapshots` SQL row for completed saved profiles | Archetype labels, primary/secondary percentages, reasoning text, feature visualizations, timeline chart data | Rendered frontend charts and latest-profile UI state | Unsaved `_currentResult` in frontend memory before save | No automatic expiry; snapshots are append-only product history unless user deletion is introduced. | Persist only completed user-saved profile snapshots. Do not persist partial quiz state by default. | Feature vectors may appear in API responses and share cards. Duplicates must reference snapshot id when treated as durable. |
| Spotify OAuth | Spotify account-link subsystem: `spotify_oauth_service.py`, OAuth routes, token helpers | `spotify_connections` SQL row for user account link and refresh capability | Spotify taste summaries built from current top tracks/artists/recent tracks | In-memory access token during a request | OAuth `state` payload; refreshed access token values during request handling | Access token expires at `token_expires_at`; refresh as needed. OAuth state should expire within minutes and be single-flow only. Connection rows currently have no row expiry. | Persist server-side OAuth connection only. Never persist OAuth state after callback. Access/refresh tokens need secret-handling policy before broader retention. | Spotify account id may appear in status responses. Tokens must not be duplicated into frontend localStorage, playlist JSON, logs, or share links. |
| spotify_tracks | Spotify taste cache subsystem: `save_spotify_tracks`, `_load_spotify_taste_profile`, `_cached_spotify_taste_profile` | Spotify API is canonical for the user's Spotify library/taste | Cached top tracks, artist names, genres, audio feature proxies, popularity, time range | In-memory taste profile objects and Spotify API response shaping | None, except request-local fallback profile | Current implementation replaces rows per `user_id` and `time_range`; target policy should treat rows stale after a short taste-cache window, for example 7-30 days. | Persist as derived cache only. Safe to delete and rebuild from Spotify while OAuth remains valid. | May duplicate public track metadata in playlist responses. Must not be the authority for user identity, saved genome, or playlist history. |
| Playlists | Recommendation/playlist subsystem: `playlist_generator.py` and playlist routes | No canonical playlist history under current architecture. Live API response is the immediate product output. | `generated_playlists` rows, if present, are legacy/derived copies; playlist responses are recomputable from snapshot/settings/catalog/algorithm | `recently_served_track_ids`, regional search caches, frontend rendered playlist cards | Request seed counters, request-local candidate pools, trial playlist request body | Live response expires at response end. Recent memory resets by process/window. Legacy rows currently have no expiry but should be considered purgeable after policy is set. | Do not write playlist responses to durable storage unless product explicitly promotes canonical history. If promoted, persist stable user-visible fields only. | Track ids/URLs/images may duplicate Spotify data in responses. Recommendation internals must be stripped before any durable playlist save. |
| Recommendation traces | Explanation/debug subsystem: scoring, graph, and explanation engines | None; traces are not canonical | Explanations can be recomputed from response tracks and scoring context during the request | None durable; may exist in mutable track dicts during generation | `recommendation_trace`, score components, pre/post rank metadata | Request lifetime only. | Never persist. Strip before saving playlist JSON, analytics events, or share payloads. | May be returned in explicit debug/explanation responses if requested, but must remain outside durable product records. |
| Embeddings | Semantic ranking subsystem: `embedding_ranker.py`, `user_profile_encoder.py`, track profile builder | Source text and model/version are canonical inputs; embedding vectors are derived | User/profile text embeddings, track text embeddings, query embeddings | `EmbeddingRanker.cache`, module-level encoder cache | Request-local candidate embeddings | Process lifetime or cache limit; current cache clears at 10,000 entries and resets on restart. | Do not persist raw vectors or temporary embedding artifacts in SQL/files under current architecture. Recompute as needed. | Multiple in-memory rankers may duplicate embeddings. Duplication is allowed only within process caches and must not cross into canonical tables. |
| Graph state | Semantic graph subsystem: `track_graph.py`, exploration engine, Graphify developer tooling | Runtime track/candidate set and source repository files are canonical inputs | Track graph adjacency, graph flow scores, Graphify `graph.json`/reports | `TrackGraph._default_graph`, per-request `TrackGraph`, Graphify AST cache | Per-request exploration graph and neighbor lookups | Runtime graph expires at request/process end. Graphify artifacts expire when source code changes and require manual refresh. | App graph state must not be persisted as product data. Graphify output is developer-derived documentation/tooling only. | Graph structure may duplicate track metadata and embeddings inside memory. Graphify may duplicate repo structure under `graphify-out`, not user/product state. |
| Exploration metadata | Controlled exploration subsystem: `exploration_engine.py`, playlist generator | None; exploration is a per-response recommendation choice | User-facing exploration labels/explanations can be recomputed from request context | None durable | `exploration`, `exploration_meta`, exploration score details on track dicts | Request/response lifetime only. | Do not persist by default. If a user-facing playlist event is later made canonical, persist only a stable `is_exploration_pick` flag if product needs it, not internal scores. | May appear in API response for explanation. Must not leak into legacy `generated_playlists.tracks` as durable algorithm history. |
| Session tokens | Session subsystem in `main.py` plus frontend session helpers | `users.id` is canonical identity; token is proof-of-session only | Decoded user id from signed token | Browser memory copy of current token | Signed `sd1...` token in frontend localStorage/API payloads | Current tokens have no expiry. Target policy should add issued-at/expiry and support rotation/revocation. | Do not persist session tokens in SQL as canonical state. Frontend may store current token until sign-out/expiry. | Token may duplicate user id in localStorage and payloads. Server must verify signature and resolve to `users.id` before writes. |
| Frontend localStorage | Frontend session/UI subsystem | None for product truth; server SQL and API responses are authoritative | Display name, email, profile code, clip-count preference, cached latest share URL | `sonic_display_name`, `sonic_profile_code`, `sonic_user_email`, `sonic_dna_clip_count` | `sonic_session_token` | Manual removal/sign-out today. Target policy should expire token-bearing entries with server token expiry. UI preferences can last indefinitely. | Store convenience data only. Never treat localStorage identity/profile data as authoritative during backend writes. | May mirror server display fields for UI. Backend must ignore client-cached identity facts except verified session token and explicit update requests. |
| Email queue | Notification subsystem: `Email_service.py`, retention scheduler, admin processor | `email_queue` SQL row is canonical queue work item until sent/failed | Rendered HTML body and notification context are denormalized at enqueue time | SMTP connection/runtime send state | Pending/retry workflow state | Pending rows retry while `retry_count < 3`. Target policy: keep sent rows for audit window, keep failed rows for troubleshooting window, then purge/archive. | Persist email work items until terminal status and retention window pass. Do not persist tokens/secrets in email bodies. | Email body may duplicate user names, share URLs, and archetype text at enqueue time. It must not become source of user/profile truth. |
| Share links | Share/social subsystem: `Share_link.py` and share routes | `share_links` SQL row: code, inviter user/snapshot, invitee completion, status, expiry | Share analytics, times accessed summaries, compare result derived from snapshots | Frontend `latestShareResultUrl` and rendered share cards | Incoming share code in URL/query while completing flow | `expires_at` defines active window. Expired pending links should be treated inactive even before cleanup. Completed links can remain for product history if retention allows. | Persist link lifecycle state. `times_accessed` is mutable analytics, not identity. | Share code/full URL may duplicate in frontend, emails, and messages. Snapshot details in share views must resolve from `genome_snapshots`. |
| User locations | Location/leaderboard subsystem | `user_locations` SQL row as current declared/detected location for a user | City leaderboard, archetype strongholds, global/city distributions | Frontend rendered leaderboard state | Request-local IP/geolocation submission | Current row has no expiry. Target policy should expire or anonymize IP address earlier than city/country data. | Persist only current location unless historical location becomes a product feature. Avoid binding mutable current location to old snapshots as historical fact. | City/country may duplicate in leaderboard responses. IP address must not be duplicated into analytics outputs, email bodies, playlist JSON, or share links. |
| Genome comparisons | Compatibility/social comparison subsystem | Source snapshots in `genome_snapshots` are canonical; comparison row is derived | `genome_comparisons` SQL row with score/details generated by current algorithm | In-memory comparison response | None beyond request | No current expiry. Target policy should version or expire comparisons when algorithm changes. | Persist only if needed for recent social history/cache. Recompute from snapshots when correctness matters. | Scores may duplicate in share/email responses. Comparison details must cite snapshot ids and should not overwrite snapshot truth. |
| Static clip/profile datasets | Genome engine/static data subsystem | `backend/data/clip_features.json`, `backend/data/clips/**`, `user_genome_clustered.csv` | `user_genre_similarity.csv`, computed cluster averages, loaded dataframes | `CLIP_FEATURES`, `_CLIP_FEATURES`, `GenomeEngine` dataframes | None | File-version lifetime; changes require restart/reload. | Keep static assets/files as canonical offline inputs. Do not merge static CSV user ids into SQL identity namespace. | Loaded copies may exist in multiple modules. API responses may expose selected clip metadata, not internal file inventory as user state. |

## Cache Policy Table

| Cache/state | Owner | Type | Current lifetime | Allowed contents | Must not contain | Invalidation trigger |
| --- | --- | --- | --- | --- | --- | --- |
| `EmbeddingRanker.cache` | Semantic ranking | In-memory cache | Process lifetime, cleared when entry limit would exceed 10,000 | Text-to-vector embeddings derived from current model | Durable user/product truth; raw vectors written to SQL/files | Process restart, cache limit, embedding model/profile text changes |
| User profile encoder singleton | Semantic ranking | In-memory cache/singleton | Process lifetime | Encoder/ranker instance | Independent durable profile state | Process restart or explicit ranker replacement |
| Spotify search cache | Spotify discovery | In-memory API cache | 300 seconds | Spotify search result pages by query/market/limit/offset | User OAuth tokens, canonical track ownership | TTL expiry, rate-limit recovery, process restart |
| Spotify regional cache | Spotify discovery | In-memory API cache | 120 seconds | Regional discovery result lists | Durable playlist history, recommendation traces | TTL expiry, process restart, Spotify API recovery |
| Spotify app access token | Spotify discovery | In-memory session token | Until app token expiry | Client-credentials access token | User OAuth refresh token | Token expiry or process restart |
| Spotify top tracks in `spotify_tracks` | Spotify taste | SQL derived cache | Indefinite today; target 7-30 day staleness window | User top track metadata for a time range | Tokens, ranking traces, graph scores | Successful Spotify refresh, user disconnect, stale age, account relink |
| Track graph singleton | Graph/ranking | In-memory graph cache | Process lifetime | Track nodes, adjacency, normalized vectors | Product history or user identity | Track corpus changes, embedding model/profile text changes, process restart |
| Per-request track graph | Graph/ranking | Request cache | Request lifetime | Candidate graph, temporary adjacency and neighbor scores | Anything durable | End of request |
| Recently served track ids | Playlist generator | In-memory repetition cache | Fixed window of 20 per region, process lifetime | Track ids recently returned by region | User-specific canonical history | Process restart or window eviction |
| Graphify AST cache | Developer tooling | File cache | Tool-managed/manual | Parsed source metadata | Runtime user/product state | Source changes or Graphify refresh |
| Frontend localStorage display fields | Frontend UI | Browser cache | Until manual clear/sign-out today | Display name, email, profile code, UI preferences | Canonical identity/profile facts | Sign-out, session expiry, explicit identity update |

## Expiration Policy Table

| Domain | Current expiration behavior | Target boundary policy |
| --- | --- | --- |
| `users` | None | Keep durable while the user has saved snapshots, share links, OAuth links, or email history. Define later cleanup for abandoned anonymous users only after dependent rows are handled. |
| `genome_snapshots` | None | Retain as canonical product history unless user deletion/export policy says otherwise. |
| `spotify_connections` | Access token expiry only; row persists | Refresh access token before use. Delete or disable row on disconnect, revoked refresh, or user deletion. |
| Spotify OAuth state | Timestamp included but no durable nonce lifecycle | Treat as minutes-long redirect state. Validate age and consume once when implemented. |
| `spotify_tracks` | Replaced on import per user/time range; no stale-age check | Treat as stale cache after a defined window, for example 7-30 days, and refresh from Spotify when OAuth is valid. |
| Live playlist responses | Response lifetime | Request/response only unless product explicitly saves canonical history. |
| `generated_playlists` | None | Treat existing rows as legacy/derived. If retained, purge by age or migrate conceptually to canonical history later. |
| Recommendation traces | Request lifetime unless accidentally saved in JSON | Request lifetime only. Strip before persistence. |
| Embedding caches/artifacts | Process lifetime or cache-limit clear | Process/request lifetime only. Recompute after model, text-builder, or corpus changes. |
| Graph state | Process/request lifetime; Graphify manual refresh | Runtime graph expires with request/process. Graphify output expires when code changes. |
| Exploration metadata | Request/response lifetime | Do not persist. Keep only visible labels in response if needed. |
| Session tokens | No expiry | Add explicit issued-at/expiry and server-side invalidation policy before treating sessions as mature auth. |
| Frontend localStorage | Until manual clear | Clear on sign-out, token expiry, account merge conflict, or server rejection. |
| `email_queue` | Pending retries below 3; sent/failed stay forever | Keep pending until terminal. Retain sent/failed for a fixed audit/troubleshooting window, then purge/archive. |
| `share_links` | `expires_at` checked on reads; rows remain | Pending links inactive after `expires_at`. Completed links may be retained as social history; expired unused links can be purged after analytics window. |
| `user_locations` | One mutable current row per user, no deletion | City/country may persist as current profile extension. IP address should expire/anonymize on a shorter privacy window. |
| `genome_comparisons` | None | Recompute or version when comparison algorithm changes. Retain only if social history requires it. |

## Allowed Duplication Boundaries

| Canonical owner | Allowed duplicate copies | Boundary rule |
| --- | --- | --- |
| `users.id` | Signed session token, API payloads, frontend localStorage | Duplicates only identify the user for lookup. SQL `users` remains authoritative. |
| `genome_snapshots` | API result payloads, timeline charts, share cards, comparison inputs | Durable references must carry `snapshot_id`; copied feature values are display/cache only. |
| Spotify API/account | `spotify_connections`, `spotify_tracks`, taste summaries, playlist response metadata | OAuth tokens stay server-side. Spotify track metadata may be cached but Spotify remains canonical for catalog/account state. |
| Live recommendation response | Frontend playlist cards, explanation response | Request-scoped details may duplicate scoring context. Debug traces and graph scores cannot cross into durable stores. |
| Share link lifecycle | Email body, frontend URL, social messages | `share_links.share_code` is authoritative; copied URLs are delivery mechanisms. |
| Email queue | SMTP message body, sent status | Queue row owns delivery lifecycle; email content is not source of user/profile/share truth. |
| Location current row | Leaderboard response, analytics summaries | `user_locations` owns current location. Analytics must not reinterpret it as historical snapshot location. |
| Static datasets | Process-loaded dataframes/globals | Files own static inputs. Runtime copies are invalid after file replacement until restart/reload. |

## Cleanup Recommendations

These recommendations follow from ownership conflicts only. They are intentionally not migrations.

1. Mark `generated_playlists` as legacy/derived in code comments and docs until a product decision promotes playlist history. Any future save path should strip `recommendation_trace`, `exploration_meta`, graph scores, temporary embeddings, and mutable candidate fields.
2. Define a stale-cache policy for `spotify_tracks`. It is currently a SQL cache used like fallback profile storage; make reads treat old rows as cache misses once a max age is chosen.
3. Add a session-token lifecycle design before changing auth behavior: issued-at, expiry, secret rotation, sign-out semantics, and what happens to localStorage after expiry.
4. Separate Spotify app auth from user OAuth in documentation and future code comments. App client-credentials tokens are process-local; user OAuth connections are server-side account links.
5. Treat recommendation traces and exploration metadata as response/debug envelopes rather than fields embedded into track dictionaries that might later be serialized into playlist JSON.
6. Version semantic algorithms conceptually: embedding model, track profile text builder, graph construction, and comparison algorithm. Persisted derived rows should be invalidated or recomputed when those versions change.
7. Keep Graphify output and app graph state in separate mental buckets. `graphify-out` is developer tooling; `TrackGraph` is runtime recommendation support; neither owns product data.
8. Add a privacy retention policy for `user_locations.ip_address`, email queue bodies, Spotify tokens, and anonymous users before adding more durable analytics.
9. Stop treating frontend localStorage fields as identity facts. Backend writes should continue to resolve through verified session tokens and SQL user rows.
10. Clarify current-vs-historical semantics for locations in leaderboard code. Current `user_locations` should not be described as the location at the time of an old genome snapshot.
11. Keep email queue ownership narrow: delivery lifecycle only. Do not use queued HTML bodies as a source for user names, archetypes, links, or comparison state.
12. Document that `genome_comparisons` is derived from snapshots and algorithm version, not canonical compatibility truth. When correctness matters, recompute from source snapshots.
