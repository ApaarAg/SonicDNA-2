# SonicDNA Monitoring Infrastructure

Internal-only operational monitoring for the recommendation backend.
Never user-facing. Never persisted to canonical DB state.

---

## Package Layout

```
backend/monitoring/
  __init__.py          # Public re-exports
  metrics_store.py     # Thread-safe rolling metrics collection
  health_report.py     # Structured health snapshot generation
  anomaly_detection.py # Threshold-based anomaly flagging
```

---

## Activation

```bash
SONICDNA_MONITOR=1        # explicit enable
DEBUG_MONITOR=1           # alternative flag
SONICDNA_ENV=development  # dev env auto-enables
```

Default: **disabled** in production. All code paths are gated by `is_monitoring_enabled()`.

---

## Rolling Metrics Strategy

| Category | Storage | Bound | Window |
|---|---|---|---|
| Latency (ms) | `deque(maxlen=500)` | 500 samples | Last 50 by default |
| Cache hit/miss | `deque(maxlen=500)` per cache | 500 entries | Last 100 |
| Operational ratios | `deque(maxlen=500)` | 500 entries | Last 100 |
| Quality scores | `deque(maxlen=500)` | 500 samples | Last 50 |
| Counters | Monotonic int + timestamps deque | 1000 ts entries | Rate over 5 min |
| Session dist. | `deque(maxlen=500)` | 500 entries | Last 100 |

All buffers are **fixed-size circular** — memory is bounded and never grows unbounded.

---

## Metrics Tracked

### Latency Metrics (ms)
| Metric key | What it covers |
|---|---|
| `recommendation_total` | Full playlist generation wall-clock |
| `candidate_retrieval` | Spotify API search + formatting |
| `genome_scoring` | `_score_tracks_by_genome` including embedding + graph |
| `embedding_rerank` | User embedding similarity pass |
| `graph_rerank` | Graph flow bonus pass |
| `exploration_injection` | `inject_exploration_tracks` |
| `flow_sequencing` | `reorder_for_flow` greedy sequencer |
| `flow_evaluation` | Flow evaluator (debug mode) |
| `spotify_api` | Raw Spotify HTTP call duration |

### Cache Metrics
| Cache | Key |
|---|---|
| Spotify search cache | `search` |
| Regional track cache | `regional` |
| Embedding vector cache | `embedding` |

### Operational Ratios
| Ratio | What it means |
|---|---|
| `exploration_injection` | Fraction of playlists with ≥1 exploration track |
| `playlist_success` | Fraction of successful completions |
| `candidate_nonempty` | Fraction where Spotify returned results |

### Quality Scores (0–1)
| Score | How computed |
|---|---|
| `playlist_diversity` | Unique artists / total tracks |
| `flow_quality` | From flow evaluator output |
| `recommendation_stability` | Overlap between consecutive requests |

### Counters
`playlist_generated`, `playlist_failed`, `empty_candidates`, `cache_flush`, `api_errors`

---

## Health Report Structure

```json
{
  "status": {
    "status": "healthy",      // "healthy" | "degraded" | "unhealthy"
    "score": 1.0,             // 0.0 - 1.0 composite score
    "active_anomalies": 0,
    "uptime_seconds": 3600.0,
    "generated_at": "2026-05-09T08:50:49+00:00"
  },
  "latencies": [
    { "stage": "recommendation_total", "mean_ms": 473, "p50_ms": 505, "p95_ms": 689, "max_ms": 783, "sample_count": 20 }
  ],
  "caches": [
    { "name": "regional", "hit_rate": 0.65, "total_lookups": 20, "verdict": "ok" }
  ],
  "quality": [
    { "metric": "playlist_diversity", "mean": 0.71, "min_val": 0.50, "trend": "declining", "sample_count": 20 }
  ],
  "counters": {
    "playlist_generated": { "total": 20, "rate_per_min": 4.0 }
  },
  "session_distribution": {
    "night_drive": 0.35, "workout": 0.30, "default": 0.30, "focus": 0.05
  },
  "anomalies": []
}
```

### Health Score Calculation
| Anomaly severity | Score penalty |
|---|---|
| `critical` | −0.30 |
| `high` | −0.15 |
| `medium` | −0.05 |
| `low` | 0 |

`score ≥ 0.8` → **healthy**, `0.5–0.8` → **degraded**, `< 0.5` → **unhealthy**

---

## Anomaly Detection

All checks are pure observation — no mutations to recommendation state.

| Anomaly type | Trigger | Default threshold | Severity |
|---|---|---|---|
| `latency_spike` | `recommendation_total` p95 > 2000ms | 2000ms | critical |
| `latency_spike` | `candidate_retrieval` p95 > 1500ms | 1500ms | high |
| `latency_spike` | `spotify_api` p95 > 3000ms | 3000ms | high |
| `latency_spike` | `embedding_rerank` p95 > 500ms | 500ms | medium |
| `latency_spike` | `genome_scoring` p95 > 200ms | 200ms | medium |
| `latency_spike` | `flow_sequencing` p95 > 100ms | 100ms | low |
| `cache_collapse` | Regional cache hit rate < 15% | 15% | high |
| `cache_collapse` | Embedding cache hit rate < 30% | 30% | medium |
| `cache_collapse` | Search cache hit rate < 20% | 20% | medium |
| `exploration_gone` | Exploration injection rate < 2% | 2% | high |
| `diversity_collapse` | Playlist diversity mean < 0.25 | 0.25 | high |
| `flow_degradation` | Flow quality mean < 0.35 | 0.35 | medium |
| `instability` | Stability score mean < 0.40 | 0.40 | medium |
| `elevated_failures` | Failures/min > 5.0 | 5.0/min | critical |
| `empty_candidates` | Non-empty candidate rate < 70% | 70% | high |

---

## API Endpoint

```
GET /admin/health
```

- Returns the full health report as JSON.
- Returns **403** when monitoring is disabled (production).
- Returns **501** when the monitoring module failed to import.
- Only available in environments where `is_monitoring_enabled()` is true.

---

## Operational Workflow

```
1. Enable: SONICDNA_MONITOR=1 (dev/staging only)

2. Metrics auto-recorded:
   - Each playlist generation records latency, diversity, session type,
     exploration rate, and candidate availability.
   - Cache events recorded from Spotify service cache checks.

3. Poll health: GET /admin/health (every 30s in dev dashboards)

4. Parse anomalies array — check for:
   - severity=critical → immediate investigation
   - severity=high → review within 15 min
   - severity=medium → track trend

5. Tune thresholds:
   - Edit THRESHOLDS dict in anomaly_detection.py
   - No code changes needed for threshold adjustments

6. Reset for testing:
   from monitoring.metrics_store import get_store
   get_store().reset()
```
