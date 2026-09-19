# ============================================
# COMPATIBILITY ENGINE — Phase 2 Viral Loop
# ============================================

import math
from typing import Dict, Tuple, Optional

# Archetype pairing dynamics (0-7 archetypes)
# Higher scores = better natural chemistry
ARCHETYPE_CHEMISTRY = {
    0: {0: 95, 1: 35, 2: 75, 3: 25, 4: 80, 5: 90, 6: 30},  # Architect of Silence
    1: {0: 35, 1: 85, 2: 40, 3: 60, 4: 55, 5: 20, 6: 65},  # Storm Chaser
    2: {0: 75, 1: 40, 2: 88, 3: 50, 4: 92, 5: 70, 6: 45},  # Midnight Drifter
    3: {0: 25, 1: 60, 2: 50, 3: 95, 4: 65, 5: 30, 6: 85},  # Eternal Optimist
    4: {0: 80, 1: 55, 2: 92, 3: 65, 4: 90, 5: 75, 6: 70},  # Cartographer
    5: {0: 90, 1: 20, 2: 70, 3: 30, 4: 75, 5: 93, 6: 35},  # Quiet Storm
    6: {0: 30, 1: 65, 2: 45, 3: 85, 4: 70, 5: 35, 6: 80},  # Wordsmith
}


class CompatibilityEngine:
    """
    Calculate detailed compatibility between two users based on:
    - Genome vector similarity (audio feature alignment)
    - Archetype chemistry (personality dynamics)
    - Dual identity overlap (secondary archetype matches)
    """

    def calculate_compatibility(self, 
                               user_a_snapshot: dict, 
                               user_b_snapshot: dict) -> dict:
        """
        Main compatibility calculation.
        Returns detailed breakdown for frontend display.
        """
        # Extract genome features
        genome_a = user_a_snapshot.get("genome", {})
        genome_b = user_b_snapshot.get("genome", {})
        
        # Extract archetype info
        archetype_a_id = user_a_snapshot.get("archetype_id", 0)
        archetype_b_id = user_b_snapshot.get("archetype_id", 0)
        archetype_a_name = user_a_snapshot.get("archetype_name", "")
        archetype_b_name = user_b_snapshot.get("archetype_name", "")
        
        # Extract dual identity
        secondary_a = user_a_snapshot.get("secondary_name")
        secondary_b = user_b_snapshot.get("secondary_name")
        
        # 1. Calculate genome similarity (40% of total score)
        genome_similarity = self._calculate_genome_similarity(genome_a, genome_b)
        
        # 2. Calculate archetype chemistry (35% of total score)
        archetype_chemistry = self._get_archetype_chemistry(archetype_a_id, archetype_b_id)
        
        # 3. Calculate dual identity bonus (15% of total score)
        dual_bonus = self._calculate_dual_bonus(
            archetype_a_id, archetype_a_name, secondary_a,
            archetype_b_id, archetype_b_name, secondary_b
        )
        
        # 4. Calculate feature-by-feature breakdown (10% of total score)
        feature_breakdown = self._calculate_feature_breakdown(genome_a, genome_b)
        
        # Calculate weighted overall score
        overall_score = (
            genome_similarity * 0.40 +
            archetype_chemistry * 0.35 +
            dual_bonus * 0.15 +
            feature_breakdown["alignment_bonus"] * 0.10
        )
        
        # Ensure score is 0-100
        overall_score = max(0, min(100, overall_score))
        
        # Generate insights
        insights = self._generate_insights(
            overall_score, 
            genome_similarity,
            archetype_chemistry,
            archetype_a_name,
            archetype_b_name,
            feature_breakdown
        )
        
        return {
            "overall_score": round(overall_score, 1),
            "genome_similarity": round(genome_similarity, 1),
            "archetype_chemistry": round(archetype_chemistry, 1),
            "dual_identity_bonus": round(dual_bonus, 1),
            "feature_breakdown": feature_breakdown,
            "insights": insights,
            "compatibility_tier": self._get_compatibility_tier(overall_score),
            "archetype_pairing": {
                "user_a": archetype_a_name,
                "user_b": archetype_b_name,
                "chemistry_description": self._get_chemistry_description(
                    archetype_a_id, archetype_b_id
                )
            }
        }

    def _calculate_genome_similarity(self, genome_a: dict, genome_b: dict) -> float:
        """Calculate cosine similarity between genome vectors."""
        features = ["danceability", "energy", "valence", "acousticness", 
                   "instrumentalness", "speechiness", "tempo"]
        
        # Convert to normalized vectors
        vec_a = [self._feature_value(genome_a, f) for f in features]
        vec_b = [self._feature_value(genome_b, f) for f in features]
        
        if not any(vec_a) or not any(vec_b):
            return 0.0
        
        # Calculate cosine similarity using pure math
        dot = sum(x * y for x, y in zip(vec_a, vec_b))
        norm_a = math.sqrt(sum(x * x for x in vec_a))
        norm_b = math.sqrt(sum(y * y for y in vec_b))
        similarity = (dot / (norm_a * norm_b)) if (norm_a * norm_b) > 1e-9 else 0.0
        
        # Convert to 0-100 scale
        return (similarity + 1) * 50  # cosine similarity is -1 to 1

    def _feature_value(self, genome: dict, feature: str) -> float:
        """Return a comparable feature value in the stored genome scale."""
        value = float(genome.get(feature, 0) or 0)
        if feature == "tempo" and abs(value) > 10:
            # Imported BPM values are converted into an approximate z-like scale;
            # quiz snapshots already store tempo on that scale.
            return (value - 120.0) / 40.0
        return value

    def _get_archetype_chemistry(self, archetype_a: int, archetype_b: int) -> float:
        """Get pre-defined chemistry score between archetypes."""
        return ARCHETYPE_CHEMISTRY.get(archetype_a, {}).get(archetype_b, 50.0)

    def _calculate_dual_bonus(self, 
                             archetype_a_id: int, archetype_a_name: str, secondary_a: str,
                             archetype_b_id: int, archetype_b_name: str, secondary_b: str) -> float:
        """
        Calculate bonus points for dual identity matches:
        - Perfect dual swap: +100 (A's primary = B's secondary AND vice versa)
        - One-way match: +60 (A's primary = B's secondary OR vice versa)
        - Secondary overlap: +40 (both share same secondary)
        - No match: +0
        """
        bonus = 0.0
        
        # Perfect dual swap
        if (secondary_a and secondary_a == archetype_b_name and
            secondary_b and secondary_b == archetype_a_name):
            bonus = 100.0
        # One-way primary-secondary match
        elif (secondary_a and secondary_a == archetype_b_name) or \
             (secondary_b and secondary_b == archetype_a_name):
            bonus = 60.0
        # Shared secondary archetype
        elif secondary_a and secondary_b and secondary_a == secondary_b:
            bonus = 40.0
        
        return bonus

    def _calculate_feature_breakdown(self, genome_a: dict, genome_b: dict) -> dict:
        """
        Calculate alignment on each audio feature.
        Shows where users align perfectly vs differ.
        """
        features = {
            "danceability": "Rhythm & Movement",
            "energy": "Intensity & Power",
            "valence": "Emotional Tone",
            "acousticness": "Sound Texture",
            "instrumentalness": "Vocal vs Instrumental",
            "speechiness": "Lyric Focus",
            "tempo": "Speed & Pace"
        }
        
        breakdown = []
        total_alignment = 0.0
        
        for key, label in features.items():
            val_a = genome_a.get(key, 0)
            val_b = genome_b.get(key, 0)
            val_a = self._feature_value(genome_a, key)
            val_b = self._feature_value(genome_b, key)
            
            # Calculate alignment (0-100)
            diff = abs(val_a - val_b)
            alignment = max(0, (1 - diff / 4) * 100)
            
            total_alignment += alignment
            
            breakdown.append({
                "feature": key,
                "label": label,
                "user_a_value": round(val_a, 2),
                "user_b_value": round(val_b, 2),
                "alignment": round(alignment, 1),
                "status": "match" if alignment >= 70 else "differ" if alignment <= 40 else "neutral"
            })
        
        avg_alignment = total_alignment / len(features)
        
        return {
            "features": breakdown,
            "alignment_bonus": avg_alignment
        }

    def _generate_insights(self, 
                          overall_score: float,
                          genome_similarity: float,
                          archetype_chemistry: float,
                          archetype_a: str,
                          archetype_b: str,
                          feature_breakdown: dict) -> list:
        """Generate human-readable insights about the compatibility."""
        insights = []
        
        # Overall compatibility insight
        if overall_score >= 85:
            insights.append({
                "type": "overall",
                "emoji": "🎯",
                "text": "Exceptional match. Your musical DNA is almost identical — "
                       "you'd finish each other's playlists."
            })
        elif overall_score >= 70:
            insights.append({
                "type": "overall",
                "emoji": "✨",
                "text": "Strong compatibility. You share core musical values "
                       "with room for discovery."
            })
        elif overall_score >= 50:
            insights.append({
                "type": "overall",
                "emoji": "🎵",
                "text": "Moderate compatibility. Some overlap, but you'd each "
                       "introduce the other to new sonic worlds."
            })
        else:
            insights.append({
                "type": "overall",
                "emoji": "🌍",
                "text": "Complementary tastes. You're from different musical universes — "
                       "which could make for interesting discoveries."
            })
        
        # Archetype chemistry insight
        if archetype_chemistry >= 80:
            insights.append({
                "type": "chemistry",
                "emoji": "⚡",
                "text": f"{archetype_a} × {archetype_b} is a natural pairing. "
                       "These archetypes complement each other beautifully."
            })
        elif archetype_chemistry <= 40:
            insights.append({
                "type": "chemistry",
                "emoji": "🔀",
                "text": f"{archetype_a} × {archetype_b} is an unexpected match. "
                       "You approach music from completely different angles."
            })
        
        # Feature-specific insights (highlight biggest matches/differences)
        features = feature_breakdown["features"]
        top_match = max(features, key=lambda x: x["alignment"])
        top_diff = min(features, key=lambda x: x["alignment"])
        
        if top_match["alignment"] >= 85:
            insights.append({
                "type": "match",
                "emoji": "🎼",
                "text": f"Perfect sync on {top_match['label'].lower()}. "
                       "This is where your tastes merge completely."
            })
        
        if top_diff["alignment"] <= 40:
            insights.append({
                "type": "contrast",
                "emoji": "🔄",
                "text": f"Opposite poles on {top_diff['label'].lower()}. "
                       "This is where you'd challenge each other's taste."
            })
        
        return insights

    def _get_compatibility_tier(self, score: float) -> dict:
        """Return tier classification for gamification."""
        if score >= 90:
            return {"tier": "Soulmate", "emoji": "💫", "color": "#FFD700"}
        elif score >= 80:
            return {"tier": "Kindred Spirit", "emoji": "✨", "color": "#C0C0C0"}
        elif score >= 70:
            return {"tier": "Great Match", "emoji": "🎵", "color": "#CD7F32"}
        elif score >= 60:
            return {"tier": "Good Vibes", "emoji": "🎶", "color": "#4A90E2"}
        elif score >= 50:
            return {"tier": "Different Wavelengths", "emoji": "🌊", "color": "#9B59B6"}
        else:
            return {"tier": "Musical Opposites", "emoji": "🌍", "color": "#95A5A6"}

    def _get_chemistry_description(self, archetype_a: int, archetype_b: int) -> str:
        """Return narrative description of archetype pairing."""
        chemistry_narratives = {
            (0, 0): "Two architects building parallel sound universes — silent understanding.",
            (0, 5): "Silence meets stillness. You both know the power of space between notes.",
            (1, 1): "Double lightning strike. You'd blow the speakers together.",
            (1, 6): "Raw energy meets conscious wordplay — fire with direction.",
            (2, 2): "Two wanderers who never stay put. You'd drift in sync.",
            (2, 4): "Explorer meets cartographer — one wanders, one maps the journey.",
            (3, 3): "Pure joy multiplied. Your combined playlists could power a small city.",
            (3, 6): "Optimism meets storytelling — warmth with a message.",
            (4, 4): "Two mapmakers comparing notes. You'd catalog music together.",
            (5, 5): "Quiet power doubled. You both understand the weight of a whisper.",
            (6, 6): "Lyric nerds unite. You'd dissect verses for hours.",
        }
        
        # Try both orderings
        key1 = (archetype_a, archetype_b)
        key2 = (archetype_b, archetype_a)
        
        return (chemistry_narratives.get(key1) or 
                chemistry_narratives.get(key2) or 
                "An interesting dynamic — unexpected but full of potential.")


# ── Compatibility Comparison Helpers ──────────

def format_comparison_for_frontend(comparison_result: dict, 
                                   user_a_name: str,
                                   user_b_name: str) -> dict:
    """
    Format the compatibility engine output for clean frontend consumption.
    """
    return {
        "users": {
            "user_a": user_a_name,
            "user_b": user_b_name
        },
        "score": comparison_result["overall_score"],
        "tier": comparison_result["compatibility_tier"],
        "breakdown": {
            "genome_similarity": comparison_result["genome_similarity"],
            "archetype_chemistry": comparison_result["archetype_chemistry"],
            "dual_identity_bonus": comparison_result["dual_identity_bonus"]
        },
        "pairing": comparison_result["archetype_pairing"],
        "insights": comparison_result["insights"],
        "features": comparison_result["feature_breakdown"]["features"]
    }
