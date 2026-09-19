import json as _json
import os as _os
import re as _re
from pathlib import Path
from pathlib import Path as _Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from groq import Groq
from sklearn.metrics.pairwise import cosine_similarity

load_dotenv()

DATA_DIR  = Path(__file__).parent / "data"
_DATA_DIR = DATA_DIR

_CLIP_FEATURES_PATH = _DATA_DIR / "clip_features.json"
_CLIP_FEATURES: dict = {}
if _CLIP_FEATURES_PATH.exists():
    with open(_CLIP_FEATURES_PATH, encoding="utf-8") as _f:
        _CLIP_FEATURES = _json.load(_f)

# ── Archetype Definitions ────────────────────
ARCHETYPES = {
    0: {
        "name"        : "The Architect of Silence",
        "emoji"       : "🎼",
        "color"       : "#C0392B",
        "tagline"     : "You don't need words. You build worlds with sound.",
        "description" : (
            "Instrumental, dark, and expansive — your playlist is a blueprint "
            "for something no one else can see. While others need lyrics to "
            "feel, you find entire universes in a single note."
        ),
        "traits"      : ["Instrumental", "Dark", "Atmospheric", "Complex"],
        "frontier"    : ["Jazz", "New Age"],
        "frontier_reason": (
            "Same wordless depth — completely different textures "
            "you haven't touched."
        ),
    },
    1: {
        "name"        : "The Storm Chaser",
        "emoji"       : "⚡",
        "color"       : "#E67E22",
        "tagline"     : "You don't listen to music. You collide with it.",
        "description" : (
            "High voltage, zero compromise, nothing soft allowed. "
            "Your genome flatlines at calm. Every track is a controlled "
            "detonation — and you keep striking the match."
        ),
        "traits"      : ["High Energy", "Electric", "Intense", "Focused"],
        "frontier"    : ["Electronic", "Rap"],
        "frontier_reason": (
            "The same raw power — channeled through "
            "entirely different sonic worlds."
        ),
    },
    2: {
        "name"        : "The Midnight Drifter",
        "emoji"       : "🌙",
        "color"       : "#8E44AD",
        "tagline"     : "Always searching. Never settling. Everywhere at once.",
        "description" : (
            "You've been to more musical places than most people — "
            "but never stayed long enough to call any of them home. "
            "Not sad exactly. Just atmospheric. You listen like you're "
            "searching for something you can't name."
        ),
        "traits"      : ["Eclectic", "Atmospheric", "Wandering", "Introspective"],
        "frontier"    : ["Folk", "World"],
        "frontier_reason": (
            "The hidden homes you drifted past but never walked into."
        ),
    },
    3: {
        "name"        : "The Eternal Optimist",
        "emoji"       : "☀️",
        "color"       : "#F39C12",
        "tagline"     : "Your genome is sunlight in audio form.",
        "description" : (
            "You gravitate toward music that moves bodies and lifts spirits — "
            "from Latin rhythms to global beats. You don't just listen to music."
            " You become it. Rooms feel warmer when your playlist plays."
        ),
        "traits"      : ["Danceable", "Joyful", "Global", "Warm"],
        "frontier"    : ["Reggae", "RnB"],
        "frontier_reason": (
            "The same warmth and rhythm — wrapped in textures "
            "your ears haven't felt yet."
        ),
    },
    4: {
        "name"        : "The Cartographer",
        "emoji"       : "🗺️",
        "color"       : "#27AE60",
        "tagline"     : "You didn't explore music. You mapped it.",
        "description" : (
            "While others settled in one genre, you charted the whole continent."
            " Your genome is balanced because you've absorbed everything — "
            "and you're still going. The most well-traveled listener "
            "in the entire musical universe."
        ),
        "traits"      : ["Deep Listener", "Balanced", "Exploratory", "Vast"],
        "frontier"    : ["Jazz", "Classical"],
        "frontier_reason": (
            "The final uncharted territories — "
            "even for someone who's been everywhere."
        ),
    },
    5: {
        "name"        : "The Quiet Storm",
        "emoji"       : "🌧️",
        "color"       : "#2980B9",
        "tagline"     : "Still water. Infinite depth.",
        "description" : (
            "On the surface, your music is gentle — acoustic, slow, unhurried. "
            "But underneath lives a profound emotional depth. "
            "You choose music the way others choose therapy. "
            "Every note is intentional. Every silence, necessary."
        ),
        "traits"      : ["Acoustic", "Melancholic", "Slow", "Emotionally Deep"],
        "frontier"    : ["Blues", "Classical"],
        "frontier_reason": (
            "The same emotional gravity — raw and unfiltered "
            "in ways you've never heard."
        ),
    },
    6: {
        "name"        : "The Wordsmith",
        "emoji"       : "✍️",
        "color"       : "#16A085",
        "tagline"     : "For you, music is literature in motion.",
        "description" : (
            "The beat is the vehicle — but the words are the destination. "
            "You feel lyrics before you feel rhythm. "
            "Your genome is a love letter to human storytelling "
            "across every culture that ever put words to a beat."
        ),
        "traits"      : ["Lyric-Driven", "Rhythmic", "Storytelling", "Verbal"],
        "frontier"    : ["Latin", "Blues"],
        "frontier_reason": (
            "The same storytelling soul — spoken in languages "
            "your ears haven't learned yet."
        ),
    },
}

FEATURE_COLS = [
    "danceability", "energy", "valence",
    "acousticness", "instrumentalness",
    "speechiness", "tempo",
    "era_score", "listening_depth", "diversity_score"
]

RADAR_FEATURES = [
    "danceability", "energy", "valence",
    "acousticness", "instrumentalness", "speechiness"
]

RADAR_LABELS = [
    "Dance\n(Still ↔ Groove)",
    "Energy\n(Calm ↔ Electric)",
    "Mood\n(😢 Sad ↔ Happy 😊)",
    "Acoustic\n(Digital ↔ Raw)",
    "Instrumental\n(Vocal ↔ Wordless)",
    "Speech\n(Musical ↔ Spoken)"
]


class GenomeEngine:
    def __init__(self):
        print("Loading genome data...")
        self.genome_df = pd.read_csv(DATA_DIR / "user_genome_clustered.csv")
        self.sim_df    = pd.read_csv(
            DATA_DIR / "user_genre_similarity.csv",
            index_col="user_id"
        )
        self.user_index = set(self.genome_df["user_id"].values)

        # Precompute cluster-level genre averages
        self.cluster_genre_avg = self._compute_cluster_genre_averages()
        print(f"Engine ready — {len(self.genome_df):,} users loaded.")

    def _compute_cluster_genre_averages(self):
        """Precompute average genre similarity per cluster."""
        merged = self.genome_df[["user_id", "cluster"]].merge(
            self.sim_df.reset_index(), on="user_id", how="inner"
        )
        genre_cols = self.sim_df.columns.tolist()
        return merged.groupby("cluster")[genre_cols].mean()

    def get_profile(self, user_id: str) -> dict:
        """Return complete listener identity for a user_id."""

        if user_id not in self.user_index:
            return {"error": f"User '{user_id}' not found in dataset."}

        row       = self.genome_df[self.genome_df["user_id"] == user_id].iloc[0]
        cluster   = int(row["cluster"])
        archetype = ARCHETYPES[cluster]

        radar_vals = []
        for feat in RADAR_FEATURES:
            z = float(row[feat])
            radar_vals.append(round(float(np.clip((z + 3) / 6, 0, 1)), 3))

        cluster_genres = self.cluster_genre_avg.loc[cluster]
        top_genres  = cluster_genres.sort_values(ascending=False).head(3)
        low_genres  = cluster_genres.sort_values().head(2)

        cluster_size = int((self.genome_df["cluster"] == cluster).sum())

        return {
            "user_id"         : user_id,
            "cluster_id"      : cluster,
            "cluster_size"    : cluster_size,
            "archetype"       : {
                "name"            : archetype["name"],
                "emoji"           : archetype["emoji"],
                "color"           : archetype["color"],
                "tagline"         : archetype["tagline"],
                "description"     : archetype["description"],
                "traits"          : archetype["traits"],
                "frontier"        : archetype["frontier"],
                "frontier_reason" : archetype["frontier_reason"],
            },
            "radar"           : {
                "labels": RADAR_LABELS,
                "values": radar_vals,
            },
            "genre_affinities": {
                "top"   : top_genres.round(3).to_dict(),
                "bottom": low_genres.round(3).to_dict(),
            },
            "genome_features" : {
                feat: round(float(row[feat]), 4)
                for feat in FEATURE_COLS
            },
        }


# ── Quiz Answer → Genome Vector ──────────────
QUESTION_FEATURE_MAP = [
    "energy",            # Q1
    "instrumentalness",  # Q2
    "valence",           # Q3
    "acousticness",      # Q4
    "speechiness",       # Q5
    "tempo",             # Q6
    "danceability",      # Q7
    "diversity_score",   # Q8
]

# Cluster centroids from our trained model (Z-scored)
CLUSTER_CENTROIDS = {
    0: {"danceability":-0.213,"energy":-0.112,"valence":-0.644,
        "acousticness":-0.090,"instrumentalness": 1.779,
        "speechiness":-0.082,"tempo":-0.122,
        "era_score":-0.212,"listening_depth": 0.054,
        "diversity_score": 0.461},
    1: {"danceability":-0.836,"energy": 1.184,"valence":-0.319,
        "acousticness":-1.024,"instrumentalness":-0.228,
        "speechiness": 0.311,"tempo": 0.776,
        "era_score":-0.064,"listening_depth":-0.210,
        "diversity_score":-0.914},
    2: {"danceability":-0.333,"energy":-0.230,"valence":-0.256,
        "acousticness": 0.218,"instrumentalness":-0.402,
        "speechiness":-0.370,"tempo": 0.331,
        "era_score":-0.070,"listening_depth":-0.380,
        "diversity_score": 0.631},
    3: {"danceability": 0.839,"energy": 0.180,"valence": 0.914,
        "acousticness":-0.212,"instrumentalness":-0.440,
        "speechiness":-0.248,"tempo":-0.316,
        "era_score": 0.213,"listening_depth":-0.474,
        "diversity_score":-0.478},
    4: {"danceability": 0.067,"energy":-0.111,"valence": 0.084,
        "acousticness": 0.119,"instrumentalness": 0.042,
        "speechiness":-0.144,"tempo":-0.057,
        "era_score":-0.006,"listening_depth": 1.515,
        "diversity_score": 0.251},
    5: {"danceability":-0.438,"energy":-1.776,"valence":-0.925,
        "acousticness": 1.845,"instrumentalness": 0.403,
        "speechiness":-0.611,"tempo":-0.803,
        "era_score":-0.072,"listening_depth":-0.177,
        "diversity_score": 0.824},
    6: {"danceability": 1.219,"energy": 0.232,"valence": 0.804,
        "acousticness":-0.328,"instrumentalness":-0.359,
        "speechiness": 2.488,"tempo":-0.295,
        "era_score": 0.122,"listening_depth":-0.478,
        "diversity_score":-0.414},
}

SHARED_FEATURES = [
    "danceability","energy","valence",
    "acousticness","instrumentalness","speechiness","tempo"
]


def analyze_quiz(answers: list) -> dict:
    """
    Convert quiz answers (1-5 scale) into a genome vector,
    find closest archetype via cosine similarity,
    return full identity profile.
    """
    raw_genome = {}
    for i, feat in enumerate(QUESTION_FEATURE_MAP):
        answer = answers[i]  # 1-5
        z_score = (answer - 3.0)  # maps 1→-2, 3→0, 5→+2
        raw_genome[feat] = z_score

    for feat in SHARED_FEATURES:
        if feat not in raw_genome:
            raw_genome[feat] = 0.0

    user_vec = np.array([raw_genome[f] for f in SHARED_FEATURES])
    centroid_matrix = np.array([
        [CLUSTER_CENTROIDS[c][f] for f in SHARED_FEATURES]
        for c in range(7)
    ])

    sims = cosine_similarity([user_vec], centroid_matrix)[0]

    sorted_sims       = sorted(enumerate(sims), key=lambda x: x[1], reverse=True)
    primary_cluster   = sorted_sims[0][0]
    secondary_cluster = sorted_sims[1][0]
    primary_conf      = float(sims[primary_cluster])
    secondary_conf    = float(sims[secondary_cluster])

    total         = sum(max(0, s) for _, s in sorted_sims)
    primary_pct   = round(max(0, primary_conf)   / total * 100, 1)
    secondary_pct = round(max(0, secondary_conf) / total * 100, 1)

    best_cluster = int(np.argmax(sims))
    archetype    = ARCHETYPES[best_cluster]

    radar_vals = []
    for feat in RADAR_FEATURES:
        z = raw_genome.get(feat, 0.0)
        radar_vals.append(round(float(np.clip((z + 3) / 6, 0, 1)), 3))

    archetype_scores = {
        ARCHETYPES[i]["name"]: round(float(sims[i]), 3)
        for i in range(7)
    }

    return {
        "source"          : "quiz",
        "cluster_id"      : best_cluster,
        "cluster_size"    : 0,
        "archetype_scores": archetype_scores,
        "archetype"       : {
            "name"           : archetype["name"],
            "emoji"          : archetype["emoji"],
            "color"          : archetype["color"],
            "tagline"        : archetype["tagline"],
            "description"    : archetype["description"],
            "traits"         : archetype["traits"],
            "frontier"       : archetype["frontier"],
            "frontier_reason": archetype["frontier_reason"],
        },
        "radar"           : {
            "labels": RADAR_LABELS,
            "values": radar_vals,
        },
        "genre_affinities": {"top": {}, "bottom": {}},
        "genome_features" : raw_genome,
        "dual_identity"   : {
            "primary_pct"        : primary_pct,
            "secondary_pct"      : secondary_pct,
            "secondary_cluster"  : secondary_cluster,
            "secondary_archetype": {
                "name" : ARCHETYPES[secondary_cluster]["name"],
                "emoji": ARCHETYPES[secondary_cluster]["emoji"],
                "color": ARCHETYPES[secondary_cluster]["color"],
            }
        }
    }


def _build_profile_from_genome(raw_genome: dict, source: str, extra: dict = None) -> dict:
    """
    Shared helper: given a raw genome dict (feature→z-score-like value),
    compute cosine similarity to centroids and return the full profile JSON.
    """
    user_vec = np.array([raw_genome.get(f, 0.0) for f in SHARED_FEATURES])
    centroid_matrix = np.array([
        [CLUSTER_CENTROIDS[c][f] for f in SHARED_FEATURES]
        for c in range(7)
    ])
    sims = cosine_similarity([user_vec], centroid_matrix)[0]

    sorted_sims       = sorted(enumerate(sims), key=lambda x: x[1], reverse=True)
    primary_cluster   = sorted_sims[0][0]
    secondary_cluster = sorted_sims[1][0]
    primary_conf      = float(sims[primary_cluster])
    secondary_conf    = float(sims[secondary_cluster])

    total         = sum(max(0, s) for _, s in sorted_sims)
    primary_pct   = round(max(0, primary_conf)   / (total or 1) * 100, 1)
    secondary_pct = round(max(0, secondary_conf) / (total or 1) * 100, 1)

    archetype = ARCHETYPES[primary_cluster]

    radar_vals = []
    for feat in RADAR_FEATURES:
        z = raw_genome.get(feat, 0.0)
        radar_vals.append(round(float(np.clip((z + 3) / 6, 0, 1)), 3))

    archetype_scores = {
        ARCHETYPES[i]["name"]: round(float(sims[i]), 3)
        for i in range(7)
    }

    result = {
        "source"          : source,
        "cluster_id"      : primary_cluster,
        "cluster_size"    : 0,
        "archetype_scores": archetype_scores,
        "archetype"       : {
            "name"           : archetype["name"],
            "emoji"          : archetype["emoji"],
            "color"          : archetype["color"],
            "tagline"        : archetype["tagline"],
            "description"    : archetype["description"],
            "traits"         : archetype["traits"],
            "frontier"       : archetype["frontier"],
            "frontier_reason": archetype["frontier_reason"],
        },
        "radar"           : {
            "labels": RADAR_LABELS,
            "values": radar_vals,
        },
        "genre_affinities": {"top": {}, "bottom": {}},
        "genome_features" : raw_genome,
        "dual_identity"   : {
            "primary_pct"        : primary_pct,
            "secondary_pct"      : secondary_pct,
            "secondary_cluster"  : secondary_cluster,
            "secondary_archetype": {
                "name" : ARCHETYPES[secondary_cluster]["name"],
                "emoji": ARCHETYPES[secondary_cluster]["emoji"],
                "color": ARCHETYPES[secondary_cluster]["color"],
            }
        }
    }
    if extra:
        result.update(extra)
    return result


def analyze_clips_ratings(clip_ratings) -> dict:
    """
    Convert clip ratings (list of ClipRating objects) into a genome vector.
    User ratings (1-5) are used as weights for weighted averaging.
    """
    FEATURE_KEYS = ["danceability", "energy", "valence",
                    "acousticness", "instrumentalness", "speechiness", "tempo"]

    TEMPO_MEAN, TEMPO_STD = 120.0, 35.0

    weighted_sum    = {f: 0.0 for f in FEATURE_KEYS}
    total_weight    = 0.0
    rated_clip_info = []

    for cr in clip_ratings:
        clip_data = _CLIP_FEATURES.get(cr.clip_id)
        if not clip_data:
            continue
        weight   = cr.rating
        features = clip_data["features"]
        for feat in FEATURE_KEYS:
            weighted_sum[feat] += features.get(feat, 0.5) * weight
        total_weight += weight
        rated_clip_info.append({
            "clip_id": cr.clip_id,
            "title"  : clip_data["title"],
            "rating" : cr.rating,
        })

    if total_weight == 0:
        raise ValueError("No valid clip ratings provided")

    raw_genome = {}
    for feat in FEATURE_KEYS:
        avg = weighted_sum[feat] / total_weight
        if feat == "tempo":
            raw_genome[feat] = (avg - TEMPO_MEAN) / TEMPO_STD
        else:
            raw_genome[feat] = (avg - 0.5) * 4.0

    extra = {"rated_clips": rated_clip_info}
    return _build_profile_from_genome(raw_genome, "audio_clips", extra)


def analyze_open_questions(q1: str, q2: str, q3: str) -> dict:
    """
    Use Groq AI to extract a musical genome from 3 open-ended text answers.
    Returns a JSON genome vector which is then cosine-matched to centroids.
    """
    client = Groq(api_key=_os.getenv("GROQ_API_KEY"))

    prompt = f"""You are a music taste analyst. Extract a musical genome vector from these answers.

Q1 (Perfect song description): {q1}
Q2 (Artists they're embarrassed to love): {q2}
Q3 (Last song that made them feel something): {q3}

Return ONLY a valid JSON object with exactly these keys and float values from -2.0 to +2.0:
{{
  "danceability": <float>,       // -2=not danceable, +2=very danceable
  "energy": <float>,             // -2=calm/ambient, +2=intense/electric
  "valence": <float>,            // -2=dark/melancholic, +2=joyful/positive
  "acousticness": <float>,       // -2=fully electronic, +2=fully acoustic
  "instrumentalness": <float>,   // -2=very vocal/lyric-driven, +2=purely instrumental
  "speechiness": <float>,        // -2=pure music, +2=spoken word/rap
  "tempo": <float>,              // -2=very slow, +2=very fast
  "reasoning": "<1-2 sentence explanation of your analysis>"
}}

No markdown, no extra text. Just the JSON."""

    message = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}]
    )

    raw_text = message.choices[0].message.content.strip()

    try:
        genome_data = _json.loads(raw_text)
    except _json.JSONDecodeError:
        match = _re.search(r'\{.*\}', raw_text, _re.DOTALL)
        if match:
            genome_data = _json.loads(match.group())
        else:
            raise ValueError(f"Groq returned invalid JSON: {raw_text[:300]}")

    reasoning = genome_data.pop("reasoning", "Your musical genome has been decoded.")

    raw_genome = {}
    for feat in ["danceability", "energy", "valence", "acousticness",
                 "instrumentalness", "speechiness", "tempo"]:
        val = genome_data.get(feat, 0.0)
        raw_genome[feat] = float(max(-2.0, min(2.0, val)))

    extra = {"claude_reasoning": reasoning, "raw_answers": {"q1": q1, "q2": q2, "q3": q3}}
    return _build_profile_from_genome(raw_genome, "claude_open", extra)

# ════════════════════════════════════════════
# ADAPTIVE CLIP SELECTION ENGINE
# ════════════════════════════════════════════

import itertools
from clip_rotation import select_adaptive_clip_ids, select_round_clip_ids

def _clip_feature_distance(clip_a: dict, clip_b: dict) -> float:
    """Euclidean distance between two clip feature vectors."""
    keys = ["danceability","energy","valence",
            "acousticness","instrumentalness","speechiness"]
    fa = clip_a["features"]
    fb = clip_b["features"]
    return float(np.sqrt(sum((fa[k]-fb[k])**2 for k in keys)))


def get_calibration_clips(n: int = 3, session_key: str = "") -> list:
    """
    Return n maximally diverse clips for round 1.
    Diversity = maximize minimum pairwise distance.
    """
    all_ids = list(_CLIP_FEATURES.keys())
    if n <= 1:
        return select_round_clip_ids(_CLIP_FEATURES, max(0, n), session_key=session_key)

    cal_ids = [c for c in all_ids if c.startswith("cal_")]
    preferred = cal_ids if len(cal_ids) >= n else all_ids

    best_combo = None
    best_score = -1

    # Keep the existing feature-distance diversity, then rotate ties/categories
    # through the explicit session key so repeated browser sessions cover more
    # of the library without hidden server state.
    for combo in itertools.combinations(preferred, n):
        clips  = [_CLIP_FEATURES[c] for c in combo]
        # Min pairwise distance (bottleneck diversity)
        dists  = [
            _clip_feature_distance(clips[i], clips[j])
            for i in range(len(clips))
            for j in range(i+1, len(clips))
        ]
        score  = min(dists)
        if score > best_score:
            best_score  = score
            best_combo  = combo

    if not best_combo:
        return select_round_clip_ids(_CLIP_FEATURES, n, session_key=session_key, preferred_ids=preferred)

    return select_round_clip_ids(
        _CLIP_FEATURES,
        n,
        session_key=session_key,
        preferred_ids=list(best_combo),
    )


def get_adaptive_clips(
    existing_ratings: list,
    n: int = 3,
    exclude_ids: list = None,
    session_key: str = "",
) -> list:
    """
    Given existing clip ratings, select next n clips that:
    1. Probe toward highest-rated sonic territory
    2. Are diverse from each other
    3. Haven't been shown yet

    existing_ratings: list of {clip_id, rating}
    """
    rotated = select_adaptive_clip_ids(
        _CLIP_FEATURES,
        existing_ratings,
        count=n,
        session_key=session_key,
        exclude_ids=exclude_ids,
    )
    if rotated:
        return rotated

    exclude = set(exclude_ids or [])
    exclude.update(r["clip_id"] for r in existing_ratings)

    if not existing_ratings:
        return get_calibration_clips(n)

    # Build partial genome from existing ratings
    FEAT_KEYS = ["danceability","energy","valence",
                 "acousticness","instrumentalness","speechiness"]

    weighted_sum   = {f: 0.0 for f in FEAT_KEYS}
    total_weight   = 0.0

    for r in existing_ratings:
        clip = _CLIP_FEATURES.get(r["clip_id"])
        if not clip:
            continue
        w = r["rating"]
        for f in FEAT_KEYS:
            weighted_sum[f] += clip["features"].get(f, 0.5) * w
        total_weight += w

    if total_weight == 0:
        return get_calibration_clips(n)

    target = {f: weighted_sum[f]/total_weight for f in FEAT_KEYS}

    # Score available clips: closer to target = higher score
    available = [
        cid for cid in _CLIP_FEATURES
        if cid not in exclude
    ]

    if not available:
        return []

    def proximity_score(clip_id):
        feat = _CLIP_FEATURES[clip_id]["features"]
        dist = np.sqrt(sum(
            (feat.get(f,0.5) - target[f])**2
            for f in FEAT_KEYS
        ))
        return -dist  # negative because we want minimum distance

    # Get top candidates by proximity
    candidates = sorted(available, key=proximity_score, reverse=True)
    top_pool   = candidates[:min(20, len(candidates))]

    # From top pool, pick n most diverse from each other
    if len(top_pool) <= n:
        return top_pool

    best_combo = None
    best_score = -1
    for combo in itertools.combinations(top_pool[:12], n):
        clips  = [_CLIP_FEATURES[c] for c in combo]
        dists  = [
            _clip_feature_distance(clips[i], clips[j])
            for i in range(len(clips))
            for j in range(i+1, len(clips))
        ]
        score  = min(dists) if dists else 0
        if score > best_score:
            best_score = score
            best_combo = combo

    return list(best_combo) if best_combo else top_pool[:n]


def get_disambiguation_clips(
    existing_ratings: list,
    n: int = 2
) -> list:
    """
    Final round: pick clips that best separate the top 2 archetypes.
    These are clips whose features differ most between the two archetypes.
    """
    exclude = set(r["clip_id"] for r in existing_ratings)

    # Find top 2 archetypes from current ratings
    partial = analyze_clips_ratings(
        [type('CR', (), r)() for r in existing_ratings]
        if False else
        [_MockRating(r["clip_id"], r["rating"]) for r in existing_ratings]
    )

    scores   = partial["archetype_scores"]
    top2     = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:2]
    arch1_name, arch2_name = top2[0][0], top2[1][0]

    # Find archetype IDs
    arch1_id = next(i for i,a in ARCHETYPES.items() if a["name"]==arch1_name)
    arch2_id = next(i for i,a in ARCHETYPES.items() if a["name"]==arch2_name)

    cent1 = CLUSTER_CENTROIDS[arch1_id]
    cent2 = CLUSTER_CENTROIDS[arch2_id]

    FEAT_KEYS = ["danceability","energy","valence",
                 "acousticness","instrumentalness","speechiness"]

    # Find clips that maximize difference between archetypes
    available = [c for c in _CLIP_FEATURES if c not in exclude]

    def disambiguation_score(clip_id):
        feat  = _CLIP_FEATURES[clip_id]["features"]
        # How much does this clip align with arch1 vs arch2
        sim1  = sum(feat.get(f,0.5) * cent1.get(f,0) for f in FEAT_KEYS)
        sim2  = sum(feat.get(f,0.5) * cent2.get(f,0) for f in FEAT_KEYS)
        return abs(sim1 - sim2)  # higher = more discriminating

    ranked = sorted(available, key=disambiguation_score, reverse=True)
    return ranked[:n]


class _MockRating:
    def __init__(self, clip_id, rating):
        self.clip_id = clip_id
        self.rating  = rating
