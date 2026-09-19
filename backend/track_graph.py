"""
track_graph.py  —  Lightweight semantic track neighborhood graph.

Builds a sparse adjacency structure over a track corpus using four
lightweight signals combined via cosine similarity only:

    1. Embedding similarity  (primary, 0.55 weight)
    2. Artist affinity       (exact & partial match, 0.20 weight)
    3. Genre overlap         (Jaccard on genre sets, 0.15 weight)
    4. Regional overlap      (exact region match, 0.10 weight)

NO graph neural networks.  NO external graph databases.
Pure Python + NumPy; the entire module is optional / additive.

Public surface
--------------
TrackGraph
    build(tracks, embeddings)        → mutates self
    get_related_tracks(track_id)     → List[dict]
    get_track_neighbors(embedding)   → List[dict]
    rerank_for_flow(scored_tracks)   → List[dict]   ← integration hook
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from spotify_service_fixed import (
        canonicalize_genres,
        genre_families_for_genres,
        normalize_artist_name,
        region_family_for_region,
        track_fingerprint,
    )
except Exception:  # pragma: no cover
    def canonicalize_genres(genres):  # type: ignore[misc]
        raw = [genres] if isinstance(genres, str) else list(genres or [])
        return [str(g).strip().lower() for g in raw if str(g).strip()]

    def genre_families_for_genres(genres):  # type: ignore[misc]
        return []

    def normalize_artist_name(name: str) -> str:  # type: ignore[misc]
        return str(name or "").split(",")[0].strip().lower()

    def region_family_for_region(region_key: str) -> str:  # type: ignore[misc]
        return str(region_key or "").strip().lower()

    def track_fingerprint(name: str, artist: str) -> str:  # type: ignore[misc]
        return f"{str(name or '').strip().lower()}|{normalize_artist_name(artist)}"


# ---------------------------------------------------------------------------
# Constants — sourced from central config when available
# ---------------------------------------------------------------------------
try:
    from config.scoring_config import GRAPH as _GCFG
    _CONFIG_AVAILABLE = True
except ImportError:
    _CONFIG_AVAILABLE = False

# Minimum combined edge weight to store a neighbor edge at all
_EDGE_THRESHOLD: float = _GCFG.EDGE_THRESHOLD if _CONFIG_AVAILABLE else 0.20

# Maximum neighbors kept per node (top-K)
_DEFAULT_K: int = _GCFG.DEFAULT_K if _CONFIG_AVAILABLE else 10

# Signal blend weights (must sum to 1.0)
_W_EMBED:  float = _GCFG.W_EMBED  if _CONFIG_AVAILABLE else 0.55
_W_ARTIST: float = _GCFG.W_ARTIST if _CONFIG_AVAILABLE else 0.20
_W_GENRE:  float = _GCFG.W_GENRE  if _CONFIG_AVAILABLE else 0.15
_W_REGION: float = _GCFG.W_REGION if _CONFIG_AVAILABLE else 0.10

# Flow-reranking bonus: how strongly neighborhood continuity boosts a track
# that is semantically adjacent to the track ranked just above it.
_FLOW_ALPHA: float = _GCFG.FLOW_ALPHA if _CONFIG_AVAILABLE else 0.08


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cosine(a: Any, b: Any) -> float:
    """Return cosine similarity of two pre-normalised 1-D float32 arrays."""
    import numpy as np
    dot = float(np.dot(a, b))
    return max(-1.0, min(1.0, dot))


def _norm(vec) -> Optional[Any]:
    """Normalise *vec* to unit length; return None on degenerate input."""
    if vec is None:
        return None
    import numpy as np
    arr = np.asarray(vec, dtype=np.float32)
    if arr.ndim != 1 or arr.size == 0:
        return None
    nrm = float(np.linalg.norm(arr))
    if not math.isfinite(nrm) or nrm <= 0:
        return None
    return arr / nrm


def _track_id(track: dict) -> str:
    """Stable, lower-cased string key for a track dict."""
    raw = track.get("track_fingerprint") or track.get("id") or track_fingerprint(track.get("name", ""), track.get("artist", ""))
    return str(raw).strip().lower()


def _genres(track: dict) -> frozenset:
    """Return frozenset of normalised genre strings for a track."""
    raw = track.get("canonical_genres") or track.get("artist_genres") or track.get("genres") or []
    return frozenset(canonicalize_genres(raw))


def _genre_families(track: dict) -> frozenset:
    raw = track.get("genre_families") or []
    if isinstance(raw, str):
        raw = [raw]
    families = [str(item).strip().lower() for item in raw if str(item).strip()]
    if not families:
        families = genre_families_for_genres(_genres(track))
    return frozenset(families)


def _region(track: dict) -> str:
    """Return normalised region key for a track."""
    return str(track.get("region") or track.get("region_key") or "").strip().lower()


def _region_family(track: dict) -> str:
    return str(track.get("region_family") or region_family_for_region(_region(track))).strip().lower()


def _primary_artist(track: dict) -> str:
    """Return lowercase first-listed artist name."""
    return str(track.get("primary_artist_normalized") or normalize_artist_name(track.get("artist", ""))).strip().lower()


def _artist_affinity(a: dict, b: dict) -> float:
    """
    Score in [0, 1] measuring how related the two tracks' artists are.
    Exact match → 1.0, first-word match (e.g. label / group) → 0.5,
    otherwise 0.0.
    """
    pa = _primary_artist(a)
    pb = _primary_artist(b)
    if not pa or not pb:
        return 0.0
    if pa == pb:
        return 1.0
    # first word match: "anirudh ravichander" vs "anirudh"
    if pa.split()[0] == pb.split()[0]:
        return 0.5
    return 0.0


def _genre_overlap(a: dict, b: dict) -> float:
    """Jaccard similarity of genre sets plus a softer family overlap."""
    ga = _genres(a)
    gb = _genres(b)
    exact = 0.0
    if ga or gb:
        intersection = len(ga & gb)
        union = len(ga | gb)
        exact = intersection / union if union else 0.0

    fa = _genre_families(a)
    fb = _genre_families(b)
    family = 0.0
    if fa or fb:
        family = len(fa & fb) / len(fa | fb) if (fa | fb) else 0.0
    return max(exact, family * 0.55)


def _regional_overlap(a: dict, b: dict) -> float:
    """Exact region match scores highest; macro-region crossover is softer."""
    ra = _region(a)
    rb = _region(b)
    if ra and rb and ra == rb:
        return 1.0
    fa = _region_family(a)
    fb = _region_family(b)
    if fa and fb and fa == fb and fa != "global":
        return 0.45
    return 0.0


def _edge_weight(
    embed_sim: float,
    artist_aff: float,
    genre_jac: float,
    region_ov: float,
) -> float:
    """Combine four [0,1] signals into a single edge weight in [0, 1]."""
    raw = (
        _W_EMBED  * ((embed_sim + 1.0) / 2.0)  # cosine → [0,1]
        + _W_ARTIST * artist_aff
        + _W_GENRE  * genre_jac
        + _W_REGION * region_ov
    )
    return max(0.0, min(1.0, raw))


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------

class TrackGraph:
    """
    Lightweight semantic track-neighbor graph.

    Attributes
    ----------
    _adjacency : dict[str, list[tuple[str, float]]]
        Maps track_id → sorted list of (neighbor_id, weight) pairs,
        descending by weight, length ≤ top_k.
    _track_by_id : dict[str, dict]
        Quick track-dict lookup.
    _embed_by_id : dict[str, Any]
        Normalised embedding per track_id.
    """

    def __init__(self, top_k: int = _DEFAULT_K) -> None:
        self.top_k = top_k
        self._adjacency: Dict[str, List[Tuple[str, float]]] = {}
        self._track_by_id: Dict[str, dict] = {}
        self._embed_by_id: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def build(
        self,
        tracks: List[dict],
        embeddings: Iterable,
    ) -> "TrackGraph":
        """
        Populate the graph from *tracks* and their *embeddings*.

        Parameters
        ----------
        tracks : list[dict]
            Track dicts with at least ``name`` / ``artist`` / ``id``.
        embeddings : iterable of array-like
            One embedding per track, in the same order as *tracks*.
            Missing / degenerate embeddings are handled gracefully.

        Returns
        -------
        self  (fluent interface)
        """
        # Reset
        self._adjacency = {}
        self._track_by_id = {}
        self._embed_by_id = {}

        embed_list = list(embeddings)
        if len(embed_list) != len(tracks):
            print(
                f"[track_graph.build] WARNING embed/track count mismatch "
                f"embed={len(embed_list)} tracks={len(tracks)} — truncating to min"
            )
            n = min(len(embed_list), len(tracks))
            tracks = tracks[:n]
            embed_list = embed_list[:n]

        # Normalise embeddings & index tracks
        normed: List[Optional[Any]] = []
        ids: List[str] = []
        for track, raw_embed in zip(tracks, embed_list):
            tid = _track_id(track)
            ids.append(tid)
            self._track_by_id[tid] = track
            nv = _norm(raw_embed)
            self._embed_by_id[tid] = nv  # type: ignore[assignment]
            normed.append(nv)

        # Build pairwise edges (O(n²) — acceptable for corpus sizes < 2 000)
        n = len(ids)
        for i in range(n):
            ti_id = ids[i]
            ti = tracks[i]
            ei = normed[i]
            neighbors: List[Tuple[str, float]] = []

            for j in range(n):
                if i == j:
                    continue
                tj_id = ids[j]
                tj = tracks[j]
                ej = normed[j]

                # Embedding similarity
                if ei is not None and ej is not None:
                    esim = _cosine(ei, ej)
                else:
                    esim = 0.0

                weight = _edge_weight(
                    embed_sim=esim,
                    artist_aff=_artist_affinity(ti, tj),
                    genre_jac=_genre_overlap(ti, tj),
                    region_ov=_regional_overlap(ti, tj),
                )

                if weight >= _EDGE_THRESHOLD:
                    neighbors.append((tj_id, weight))

            # Keep only top-K
            neighbors.sort(key=lambda x: x[1], reverse=True)
            self._adjacency[ti_id] = neighbors[: self.top_k]

        print(
            f"[track_graph.build] nodes={n} "
            f"edges={sum(len(v) for v in self._adjacency.values())} "
            f"top_k={self.top_k}"
        )
        return self

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_related_tracks(
        self,
        track_id: str,
        limit: Optional[int] = None,
    ) -> List[dict]:
        """
        Return tracks that are semantic neighbors of *track_id*.

        Parameters
        ----------
        track_id : str
            The key as stored in the graph (raw or lower-cased string).
        limit : int | None
            Maximum results; defaults to top_k.

        Returns
        -------
        List of track dicts, ordered by descending edge weight.
        Each dict gets an injected ``graph_weight`` float.
        """
        tid = str(track_id).strip().lower()
        neighbors = self._adjacency.get(tid) or []
        limit = limit or self.top_k
        results = []
        for nid, w in neighbors[:limit]:
            track = self._track_by_id.get(nid)
            if track is None:
                continue
            out = dict(track)          # shallow copy; don't mutate original
            out["graph_weight"] = round(w, 4)
            results.append(out)
        return results

    def get_track_neighbors(
        self,
        track_embedding,
        limit: Optional[int] = None,
    ) -> List[dict]:
        """
        Return top-K nearest neighbors of an *arbitrary* query embedding
        (does not have to be a track already in the graph).

        Uses pure cosine similarity against all indexed embeddings.

        Parameters
        ----------
        track_embedding : array-like
            A raw or normalised embedding vector.
        limit : int | None
            Maximum results; defaults to top_k.

        Returns
        -------
        List of track dicts sorted by descending similarity.
        Each dict gets an injected ``embed_similarity`` float.
        """
        qvec = _norm(track_embedding)
        if qvec is None:
            return []
        limit = limit or self.top_k

        scored: List[Tuple[float, str]] = []
        for tid, evec in self._embed_by_id.items():
            if evec is None:
                continue
            sim = _cosine(qvec, evec)
            scored.append((sim, tid))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for sim, tid in scored[:limit]:
            track = self._track_by_id.get(tid)
            if track is None:
                continue
            out = dict(track)
            out["embed_similarity"] = round((sim + 1.0) / 2.0, 4)  # → [0,1]
            results.append(out)
        return results

    # ------------------------------------------------------------------
    # Flow-aware reranking  (integration hook for PlaylistGenerator)
    # ------------------------------------------------------------------

    def rerank_for_flow(
        self,
        scored_tracks: List[dict],
        *,
        flow_alpha: float = _FLOW_ALPHA,
    ) -> List[dict]:
        """
        Softly boost tracks that are semantic neighbors of the track
        ranked just above them, preserving playlist flow.

        This is a *lightweight additive pass*: the primary score from
        the genome / embedding pipeline is preserved; the graph only
        adds a small bonus (≤ *flow_alpha*) for cohesive transitions.

        Parameters
        ----------
        scored_tracks : list[dict]
            Items with keys ``"track"`` and ``"score"`` (from
            ``PlaylistGenerator._score_tracks_by_genome``).
        flow_alpha : float
            Maximum bonus that can be added (default 0.08).

        Returns
        -------
        Reranked list with an extra ``"graph_flow_bonus"`` key on each item.
        """
        if len(scored_tracks) < 2 or not self._adjacency:
            return scored_tracks

        # Single-pass: for each position i, look at what was tentatively
        # placed at i-1 and bonus tracks that neighbor it.
        result: List[dict] = []
        placed_id: Optional[str] = None  # track_id of previous entry

        remaining = list(scored_tracks)

        while remaining:
            if placed_id is None or placed_id not in self._adjacency:
                # First track: just take the best primary score
                best = remaining.pop(0)
                bonus = 0.0
            else:
                neighbor_ids = {nid for nid, _ in self._adjacency[placed_id]}
                neighbor_weights = {
                    nid: w
                    for nid, w in self._adjacency[placed_id]
                }

                # Boost candidates that are neighbors
                best_idx = 0
                best_adj_score = -1.0
                for idx, item in enumerate(remaining):
                    tid = _track_id(item["track"])
                    bonus_here = flow_alpha * neighbor_weights.get(tid, 0.0)
                    adj = item["score"] + bonus_here
                    if adj > best_adj_score:
                        best_adj_score = adj
                        best_idx = idx

                best = remaining.pop(best_idx)
                tid_best = _track_id(best["track"])
                bonus = flow_alpha * neighbor_weights.get(tid_best, 0.0)

            best = dict(best)
            best["graph_flow_bonus"] = round(bonus, 4)
            best["score"] = round(best["score"] + bonus, 6)
            result.append(best)
            placed_id = _track_id(best["track"])

        return result

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        """Return a brief summary dict for logging / debugging."""
        degrees = [len(v) for v in self._adjacency.values()]
        avg_deg = sum(degrees) / len(degrees) if degrees else 0.0
        return {
            "nodes": len(self._adjacency),
            "total_edges": sum(degrees),
            "avg_degree": round(avg_deg, 2),
            "top_k": self.top_k,
            "edge_threshold": _EDGE_THRESHOLD,
        }

    def neighbor_report(self, track_id: str, limit: int = 5) -> str:
        """
        Human-readable neighbor summary — useful for logging / demos.

        Example output
        --------------
        Neighbors of 'vaathi coming::anirudh ravichander' (top 5):
          1. arabic kuthu — anirudh ravichander  [w=0.8743]
          2. rowdy baby — dhanush               [w=0.8102]
          ...
        """
        tid = str(track_id).strip().lower()
        neighbors = self.get_related_tracks(tid, limit=limit)
        if not neighbors:
            return f"Neighbors of '{tid}': (none indexed)"
        lines = [f"Neighbors of '{tid}' (top {limit}):"]
        for i, t in enumerate(neighbors, 1):
            name = t.get("name", "?")
            artist = t.get("artist", "?")
            w = t.get("graph_weight", 0.0)
            lines.append(f"  {i}. {name} — {artist}  [w={w:.4f}]")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level singleton  (optional; avoids rebuild on every request)
# ---------------------------------------------------------------------------

_default_graph: Optional[TrackGraph] = None


def get_default_graph() -> Optional[TrackGraph]:
    """Return the module-level TrackGraph if it has been built."""
    return _default_graph


def build_default_graph(
    tracks: List[dict],
    embeddings: Iterable,
    top_k: int = _DEFAULT_K,
) -> TrackGraph:
    """Build (or rebuild) the module-level singleton and return it."""
    global _default_graph
    _default_graph = TrackGraph(top_k=top_k).build(tracks, embeddings)
    return _default_graph


# ---------------------------------------------------------------------------
# Quick smoke-test  (run as __main__)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import random

    print("=== TrackGraph smoke-test ===\n")

    _rng = random.Random(42)

    def _rand_embed(dim: int = 384):
        import numpy as np
        v = np.array([_rng.gauss(0, 1) for _ in range(dim)], dtype=np.float32)
        return v / np.linalg.norm(v)

    SAMPLE_TRACKS = [
        {
            "id": "t1",
            "name": "Vaathi Coming",
            "artist": "Anirudh Ravichander",
            "genres": ["tamil pop", "kollywood"],
            "region": "india_tamil",
            "popularity": 78,
        },
        {
            "id": "t2",
            "name": "Arabic Kuthu",
            "artist": "Anirudh Ravichander, Jonita Gandhi",
            "genres": ["tamil pop", "kollywood"],
            "region": "india_tamil",
            "popularity": 76,
        },
        {
            "id": "t3",
            "name": "Rowdy Baby",
            "artist": "Dhanush, Dhee",
            "genres": ["tamil pop", "folk"],
            "region": "india_tamil",
            "popularity": 74,
        },
        {
            "id": "t4",
            "name": "Blinding Lights",
            "artist": "The Weeknd",
            "genres": ["synth-pop", "pop"],
            "region": "global_english",
            "popularity": 90,
        },
        {
            "id": "t5",
            "name": "As It Was",
            "artist": "Harry Styles",
            "genres": ["pop", "indie pop"],
            "region": "global_english",
            "popularity": 88,
        },
    ]

    # Give t1 and t2 very similar embeddings to test affinity
    BASE = _rand_embed()
    embeds = [
        BASE + _rand_embed() * 0.05,  # t1
        BASE + _rand_embed() * 0.05,  # t2 — close to t1
        _rand_embed(),                 # t3
        _rand_embed(),                 # t4
        _rand_embed(),                 # t5
    ]

    graph = TrackGraph(top_k=3).build(SAMPLE_TRACKS, embeds)

    print("Graph stats:", graph.stats())
    print()
    print(graph.neighbor_report("t1", limit=3))
    print()
    print(graph.neighbor_report("t4", limit=3))
    print()

    # Test get_track_neighbors with a brand-new vector
    query_vec = BASE + _rand_embed() * 0.08
    nn = graph.get_track_neighbors(query_vec, limit=3)
    print("get_track_neighbors(query ~= t1/t2):")
    for t in nn:
        print(f"  {t['name']} — {t['artist']}  [sim={t['embed_similarity']:.4f}]")

    # Test flow reranking
    print()
    scored = [
        {"track": SAMPLE_TRACKS[0], "score": 0.90},
        {"track": SAMPLE_TRACKS[3], "score": 0.89},  # unrelated
        {"track": SAMPLE_TRACKS[1], "score": 0.88},  # neighbor of t1
        {"track": SAMPLE_TRACKS[2], "score": 0.85},
        {"track": SAMPLE_TRACKS[4], "score": 0.80},
    ]
    reranked = graph.rerank_for_flow(scored)
    print("Flow-reranked playlist:")
    for i, item in enumerate(reranked, 1):
        name = item["track"]["name"]
        score = item["score"]
        bonus = item.get("graph_flow_bonus", 0.0)
        print(f"  {i}. {name}  score={score:.4f}  flow_bonus={bonus:.4f}")
