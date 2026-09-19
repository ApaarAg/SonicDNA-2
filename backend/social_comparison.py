# ============================================
# SONIC DNA — Social Comparison Engine
# ============================================

import numpy as np
from typing import Dict, List, Tuple, Optional
from sklearn.metrics.pairwise import cosine_similarity


class SocialComparisonEngine:
    """Compare music taste between two users."""
    
    def compare_genomes(
        self,
        user_a_snapshot: dict,
        user_b_snapshot: dict,
        user_a_tracks: List[dict] = None,
        user_b_tracks: List[dict] = None
    ) -> dict:
        """
        Complete comparison between two users' music genomes.
        
        Args:
            user_a_snapshot: User A's genome snapshot
            user_b_snapshot: User B's genome snapshot
            user_a_tracks: Optional - User A's Spotify tracks for deeper analysis
            user_b_tracks: Optional - User B's Spotify tracks for deeper analysis
        
        Returns:
            Comprehensive comparison report
        """
        
        # 1. Genome Feature Similarity
        genome_similarity = self._compare_genome_features(
            user_a_snapshot["genome"],
            user_b_snapshot["genome"]
        )
        
        # 2. Archetype Match
        archetype_match = self._compare_archetypes(
            user_a_snapshot,
            user_b_snapshot
        )
        
        # 3. Track-level comparison (if available)
        track_comparison = None
        if user_a_tracks and user_b_tracks:
            track_comparison = self._compare_track_libraries(
                user_a_tracks,
                user_b_tracks
            )
        
        # 4. Calculate overall similarity
        overall_similarity = self._calculate_overall_similarity(
            genome_similarity,
            archetype_match,
            track_comparison
        )
        
        # 5. Generate insights
        insights = self._generate_comparison_insights(
            overall_similarity,
            genome_similarity,
            archetype_match,
            user_a_snapshot,
            user_b_snapshot,
            track_comparison
        )
        
        # 6. Compatibility score and relationship type
        compatibility = self._calculate_compatibility(overall_similarity)
        
        return {
            "overall_similarity": overall_similarity,
            "compatibility": compatibility,
            "genome_similarity": genome_similarity,
            "archetype_match": archetype_match,
            "track_comparison": track_comparison,
            "insights": insights,
            "detailed_comparison": {
                "user_a": {
                    "archetype": user_a_snapshot["archetype_name"],
                    "genome": user_a_snapshot["genome"],
                },
                "user_b": {
                    "archetype": user_b_snapshot["archetype_name"],
                    "genome": user_b_snapshot["genome"],
                },
            },
        }
    
    def _compare_genome_features(self, genome_a: dict, genome_b: dict) -> dict:
        """Compare individual genome features."""
        features = ["danceability", "energy", "valence", "acousticness",
                   "instrumentalness", "speechiness", "tempo"]
        
        similarities = {}
        differences = {}
        
        for feature in features:
            val_a = genome_a.get(feature, 0)
            val_b = genome_b.get(feature, 0)
            
            # Calculate similarity (0-100%)
            # Max difference is 4 (-2 to +2)
            diff = abs(val_a - val_b)
            similarity = max(0, (1 - diff / 4) * 100)
            
            similarities[feature] = round(similarity, 1)
            differences[feature] = round(diff, 2)
        
        # Overall genome similarity
        avg_similarity = sum(similarities.values()) / len(similarities)
        
        # Find most similar and most different features
        most_similar = max(similarities.items(), key=lambda x: x[1])
        most_different = min(similarities.items(), key=lambda x: x[1])
        
        return {
            "overall": round(avg_similarity, 1),
            "by_feature": similarities,
            "differences": differences,
            "most_similar_feature": {
                "name": most_similar[0],
                "similarity": most_similar[1],
            },
            "most_different_feature": {
                "name": most_different[0],
                "similarity": most_different[1],
            },
        }
    
    def _compare_archetypes(self, snapshot_a: dict, snapshot_b: dict) -> dict:
        """Compare archetype alignment."""
        archetype_a = snapshot_a["archetype_name"]
        archetype_b = snapshot_b["archetype_name"]
        
        same_archetype = archetype_a == archetype_b
        
        # Check if one user's secondary matches the other's primary
        secondary_a = snapshot_a.get("secondary_name")
        secondary_b = snapshot_b.get("secondary_name")
        
        cross_match = (
            archetype_a == secondary_b or
            archetype_b == secondary_a or
            (secondary_a and secondary_b and secondary_a == secondary_b)
        )
        
        # Calculate archetype match score
        if same_archetype:
            match_score = 100.0
        elif cross_match:
            match_score = 70.0
        else:
            # Partial match based on archetype proximity
            # Some archetypes are more similar than others
            match_score = self._calculate_archetype_distance(archetype_a, archetype_b)
        
        return {
            "score": round(match_score, 1),
            "same_primary": same_archetype,
            "cross_match": cross_match,
            "user_a_archetype": archetype_a,
            "user_b_archetype": archetype_b,
            "user_a_secondary": secondary_a,
            "user_b_secondary": secondary_b,
        }
    
    def _calculate_archetype_distance(self, arch_a: str, arch_b: str) -> float:
        """
        Calculate similarity between different archetypes.
        Based on their characteristic features.
        """
        # Archetype similarity matrix (simplified)
        # Higher score = more similar archetypes
        similarity_map = {
            ("The Architect of Silence", "The Quiet Storm"): 60,
            ("The Storm Chaser", "The Wordsmith"): 50,
            ("The Midnight Drifter", "The Cartographer"): 70,
            ("The Eternal Optimist", "The Wordsmith"): 55,
            ("The Cartographer", "The Quiet Storm"): 50,
        }
        
        # Check both directions
        key1 = (arch_a, arch_b)
        key2 = (arch_b, arch_a)
        
        return similarity_map.get(key1, similarity_map.get(key2, 40.0))
    
    def _compare_track_libraries(
        self,
        tracks_a: List[dict],
        tracks_b: List[dict]
    ) -> dict:
        """Compare actual track libraries for shared artists/genres."""
        
        # Extract artists
        artists_a = set()
        artists_b = set()
        
        for track in tracks_a:
            if track.get("artist"):
                artists_a.add(track["artist"].lower())
        
        for track in tracks_b:
            if track.get("artist"):
                artists_b.add(track["artist"].lower())
        
        # Find shared artists
        shared_artists = artists_a.intersection(artists_b)
        unique_to_a = artists_a - artists_b
        unique_to_b = artists_b - artists_a
        
        # Calculate artist overlap
        total_unique_artists = len(artists_a.union(artists_b))
        artist_overlap = (len(shared_artists) / total_unique_artists * 100) if total_unique_artists > 0 else 0
        
        # Extract track IDs for exact matches
        track_ids_a = {t["id"] for t in tracks_a if t.get("id")}
        track_ids_b = {t["id"] for t in tracks_b if t.get("id")}
        
        shared_tracks = track_ids_a.intersection(track_ids_b)
        
        return {
            "shared_artists_count": len(shared_artists),
            "shared_artists": list(shared_artists)[:20],  # Top 20
            "unique_to_a_count": len(unique_to_a),
            "unique_to_b_count": len(unique_to_b),
            "artist_overlap_pct": round(artist_overlap, 1),
            "shared_tracks_count": len(shared_tracks),
            "total_artists_a": len(artists_a),
            "total_artists_b": len(artists_b),
        }
    
    def _calculate_overall_similarity(
        self,
        genome_sim: dict,
        archetype_match: dict,
        track_comparison: Optional[dict]
    ) -> float:
        """
        Calculate weighted overall similarity score.
        
        Weights:
        - Genome features: 50%
        - Archetype match: 30%
        - Track overlap: 20% (if available)
        """
        genome_score = genome_sim["overall"]
        archetype_score = archetype_match["score"]
        
        if track_comparison:
            track_score = track_comparison["artist_overlap_pct"]
            overall = (
                genome_score * 0.5 +
                archetype_score * 0.3 +
                track_score * 0.2
            )
        else:
            # If no track data, reweight
            overall = (
                genome_score * 0.65 +
                archetype_score * 0.35
            )
        
        return round(overall, 1)
    
    def _calculate_compatibility(self, similarity_score: float) -> dict:
        """
        Determine compatibility tier and relationship type.
        """
        if similarity_score >= 85:
            tier = "Musical Soulmates"
            description = "You share an almost identical sonic DNA. Rare connection!"
            emoji = "🎵✨"
        elif similarity_score >= 70:
            tier = "Harmonic Twins"
            description = "Your music taste overlaps significantly. Perfect playlist swap partners!"
            emoji = "🎶🤝"
        elif similarity_score >= 55:
            tier = "Compatible Listeners"
            description = "Good overlap with interesting differences. Great for discovery!"
            emoji = "🎧💫"
        elif similarity_score >= 40:
            tier = "Complementary Tastes"
            description = "Different but not opposites. You'll expand each other's horizons."
            emoji = "🌊🔥"
        else:
            tier = "Sonic Opposites"
            description = "Completely different musical worlds. Could make for interesting debates!"
            emoji = "⚡❄️"
        
        return {
            "tier": tier,
            "description": description,
            "emoji": emoji,
            "score": similarity_score,
        }
    
    def _generate_comparison_insights(
        self,
        overall_sim: float,
        genome_sim: dict,
        archetype_match: dict,
        snapshot_a: dict,
        snapshot_b: dict,
        track_comparison: Optional[dict]
    ) -> List[str]:
        """Generate natural language insights about the comparison."""
        insights = []
        
        # Overall similarity insight
        if overall_sim >= 80:
            insights.append(f"You're {round(overall_sim)}% musically aligned — that's incredibly rare!")
        elif overall_sim >= 60:
            insights.append(f"With {round(overall_sim)}% similarity, you share a strong musical bond.")
        else:
            insights.append(f"At {round(overall_sim)}% similarity, you bring different flavors to the table.")
        
        # Archetype insight
        if archetype_match["same_primary"]:
            insights.append(
                f"Both of you are '{snapshot_a['archetype_name']}' — "
                "you speak the same musical language."
            )
        elif archetype_match["cross_match"]:
            insights.append(
                "Your secondary archetypes align — you understand each other's edges."
            )
        else:
            insights.append(
                f"'{snapshot_a['archetype_name']}' meets '{snapshot_b['archetype_name']}' — "
                "a fascinating contrast."
            )
        
        # Feature-specific insights
        most_similar = genome_sim["most_similar_feature"]
        most_different = genome_sim["most_different_feature"]
        
        feature_names = {
            "danceability": "groove preferences",
            "energy": "energy levels",
            "valence": "emotional tone",
            "acousticness": "production style",
            "instrumentalness": "vocal vs instrumental balance",
            "speechiness": "lyrical focus",
            "tempo": "pace preferences",
        }
        
        if most_similar["similarity"] >= 90:
            feat_name = feature_names.get(most_similar["name"], most_similar["name"])
            insights.append(f"You're nearly identical in {feat_name} ({round(most_similar['similarity'])}%).")
        
        if most_different["similarity"] <= 50:
            feat_name = feature_names.get(most_different["name"], most_different["name"])
            insights.append(f"Your {feat_name} couldn't be more different — complementary opposites.")
        
        # Track-based insight
        if track_comparison and track_comparison["shared_artists_count"] > 0:
            count = track_comparison["shared_artists_count"]
            if count >= 10:
                insights.append(f"You share {count} favorite artists — serious overlap!")
            else:
                insights.append(f"You have {count} artists in common — a good starting point.")
        
        return insights
    
    def generate_shared_playlist_recommendations(
        self,
        user_a_tracks: List[dict],
        user_b_tracks: List[dict],
        comparison: dict,
        playlist_size: int = 30
    ) -> dict:
        """
        Generate a collaborative playlist that both users would enjoy.
        Balances both genomes.
        """
        # Find the "middle ground" genome
        genome_a = comparison["detailed_comparison"]["user_a"]["genome"]
        genome_b = comparison["detailed_comparison"]["user_b"]["genome"]
        
        middle_genome = {}
        for feature in genome_a:
            middle_genome[feature] = (genome_a[feature] + genome_b[feature]) / 2
        
        # Collect all tracks
        all_tracks = user_a_tracks + user_b_tracks
        
        # Remove duplicates by ID
        unique_tracks = {t["id"]: t for t in all_tracks if t.get("id")}
        tracks_list = list(unique_tracks.values())
        
        # Score tracks based on how well they match the middle ground
        scored_tracks = []
        
        for track in tracks_list:
            if not all(track.get(f) is not None for f in [
                "danceability", "energy", "valence", "acousticness"
            ]):
                continue
            
            # Calculate match to middle genome
            track_genome = {
                "danceability": (track.get("danceability", 0.5) - 0.5) * 4,
                "energy": (track.get("energy", 0.5) - 0.5) * 4,
                "valence": (track.get("valence", 0.5) - 0.5) * 4,
                "acousticness": (track.get("acousticness", 0.5) - 0.5) * 4,
                "instrumentalness": (track.get("instrumentalness", 0.5) - 0.5) * 4,
                "speechiness": (track.get("speechiness", 0.5) - 0.5) * 4,
            }
            
            distance = sum(
                (track_genome.get(f, 0) - middle_genome.get(f, 0)) ** 2
                for f in ["danceability", "energy", "valence", "acousticness",
                         "instrumentalness", "speechiness"]
            ) ** 0.5
            
            score = 1 / (1 + distance)  # Convert distance to similarity
            
            scored_tracks.append({
                "track": track,
                "score": score,
            })
        
        # Sort and select top tracks
        scored_tracks.sort(key=lambda x: x["score"], reverse=True)
        selected = scored_tracks[:playlist_size]
        
        playlist_tracks = [s["track"] for s in selected]
        
        return {
            "name": "Our Shared Wavelength",
            "tracks": playlist_tracks,
            "size": len(playlist_tracks),
            "type": "collaborative",
            "description": (
                f"A playlist that balances both your genomes — "
                f"{len(playlist_tracks)} tracks you'll both love."
            ),
        }
    
    def find_discovery_bridge(
        self,
        user_a_tracks: List[dict],
        user_b_tracks: List[dict],
        comparison: dict,
        for_user: str = "a"
    ) -> dict:
        """
        Find tracks from the other user's library that would expand this user's taste.
        
        Args:
            for_user: "a" or "b" - which user to generate recommendations for
        """
        if for_user == "a":
            source_tracks = user_b_tracks
            target_genome = comparison["detailed_comparison"]["user_a"]["genome"]
            user_name = "User B"
        else:
            source_tracks = user_a_tracks
            target_genome = comparison["detailed_comparison"]["user_b"]["genome"]
            user_name = "User A"
        
        # Find tracks from source that are "close but different" from target genome
        # Not too similar (boring) but not too different (jarring)
        
        scored_tracks = []
        
        for track in source_tracks:
            if not all(track.get(f) is not None for f in [
                "danceability", "energy", "valence", "acousticness"
            ]):
                continue
            
            track_genome = {
                "danceability": (track.get("danceability", 0.5) - 0.5) * 4,
                "energy": (track.get("energy", 0.5) - 0.5) * 4,
                "valence": (track.get("valence", 0.5) - 0.5) * 4,
                "acousticness": (track.get("acousticness", 0.5) - 0.5) * 4,
                "instrumentalness": (track.get("instrumentalness", 0.5) - 0.5) * 4,
                "speechiness": (track.get("speechiness", 0.5) - 0.5) * 4,
            }
            
            distance = sum(
                (track_genome.get(f, 0) - target_genome.get(f, 0)) ** 2
                for f in ["danceability", "energy", "valence", "acousticness",
                         "instrumentalness", "speechiness"]
            ) ** 0.5
            
            # Sweet spot: distance between 1.5 and 3.5 (moderate difference)
            if 1.5 <= distance <= 3.5:
                score = 1 / (1 + abs(distance - 2.5))  # Peak at 2.5
                scored_tracks.append({
                    "track": track,
                    "score": score,
                    "distance": distance,
                })
        
        # Sort by score
        scored_tracks.sort(key=lambda x: x["score"], reverse=True)
        selected = scored_tracks[:25]
        
        playlist_tracks = [s["track"] for s in selected]
        
        return {
            "name": f"Bridge from {user_name}",
            "tracks": playlist_tracks,
            "size": len(playlist_tracks),
            "type": "discovery_bridge",
            "description": (
                f"Tracks from {user_name}'s library that will expand your taste "
                "without taking you too far from your comfort zone."
            ),
        }
