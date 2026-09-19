from typing import Dict, Optional


GENOME_FEATURES = [
    "danceability",
    "energy",
    "valence",
    "acousticness",
    "instrumentalness",
    "speechiness",
    "tempo",
]

DEFAULT_SHIFT_THRESHOLD = 18.0
MAX_FEATURE_DELTA = 4.0


class RetentionEngine:
    """
    Decide whether a user should receive a retention email after their
    SonicDNA genome changes between two snapshots.

    This engine is intentionally provider-agnostic: it returns a decision
    payload only and does not integrate with SMTP or any email service.
    """

    def __init__(self, shift_threshold: float = DEFAULT_SHIFT_THRESHOLD):
        self.shift_threshold = float(shift_threshold)

    def evaluate(
        self,
        previous_snapshot: Optional[dict],
        latest_snapshot: Optional[dict],
    ) -> dict:
        old_archetype = self._archetype_label(previous_snapshot)
        new_archetype = self._archetype_label(latest_snapshot)

        if not previous_snapshot or not latest_snapshot:
            return self._decision(
                should_send=False,
                email_type="insufficient_history",
                shift_score=0.0,
                old_archetype=old_archetype,
                new_archetype=new_archetype,
                dominant_change=None,
            )

        feature_drift = self._feature_drift(
            self._extract_genome(previous_snapshot),
            self._extract_genome(latest_snapshot),
        )
        shift_score = self._overall_shift_score(feature_drift)
        dominant_change = self._dominant_change(feature_drift)
        archetype_changed = self._archetype_changed(previous_snapshot, latest_snapshot)

        should_send = archetype_changed or shift_score > self.shift_threshold
        if archetype_changed:
            email_type = "archetype_change"
        elif shift_score > self.shift_threshold:
            email_type = "genome_shift"
        else:
            email_type = "no_send"

        return self._decision(
            should_send=should_send,
            email_type=email_type,
            shift_score=shift_score,
            old_archetype=old_archetype,
            new_archetype=new_archetype,
            dominant_change=dominant_change,
        )

    def _extract_genome(self, snapshot: Optional[dict]) -> Dict[str, float]:
        if not snapshot:
            return {}

        genome = snapshot.get("genome")
        if isinstance(genome, dict):
            return genome

        return snapshot.get("genome_features", {}) or {}

    def _feature_drift(self, previous_genome: dict, latest_genome: dict) -> Dict[str, dict]:
        drift = {}
        for feature in GENOME_FEATURES:
            previous_value = self._to_float(previous_genome.get(feature, 0.0))
            latest_value = self._to_float(latest_genome.get(feature, 0.0))
            delta = latest_value - previous_value
            percent = min(100.0, abs(delta) / MAX_FEATURE_DELTA * 100)
            drift[feature] = {
                "previous": round(previous_value, 3),
                "latest": round(latest_value, 3),
                "delta": round(delta, 3),
                "shift_pct": round(percent, 1),
                "direction": self._direction(delta),
            }
        return drift

    def _overall_shift_score(self, feature_drift: Dict[str, dict]) -> float:
        if not feature_drift:
            return 0.0

        total = sum(feature["shift_pct"] for feature in feature_drift.values())
        return round(total / len(feature_drift), 1)

    def _dominant_change(self, feature_drift: Dict[str, dict]) -> Optional[dict]:
        if not feature_drift:
            return None

        feature_name, drift = max(
            feature_drift.items(),
            key=lambda item: abs(item[1]["delta"]),
        )
        return {
            "feature": feature_name,
            "previous": drift["previous"],
            "latest": drift["latest"],
            "delta": drift["delta"],
            "shift_pct": drift["shift_pct"],
            "direction": drift["direction"],
        }

    def _archetype_changed(self, previous_snapshot: dict, latest_snapshot: dict) -> bool:
        previous_id = previous_snapshot.get("archetype_id")
        latest_id = latest_snapshot.get("archetype_id")
        if previous_id is not None and latest_id is not None:
            return previous_id != latest_id

        return self._archetype_label(previous_snapshot) != self._archetype_label(latest_snapshot)

    def _archetype_label(self, snapshot: Optional[dict]) -> Optional[str]:
        if not snapshot:
            return None

        name = snapshot.get("archetype_name")
        if name:
            return str(name)

        archetype = snapshot.get("archetype")
        if isinstance(archetype, dict):
            archetype_name = archetype.get("name")
            if archetype_name:
                return str(archetype_name)

        archetype_id = snapshot.get("archetype_id")
        return str(archetype_id) if archetype_id is not None else None

    def _decision(
        self,
        should_send: bool,
        email_type: str,
        shift_score: float,
        old_archetype: Optional[str],
        new_archetype: Optional[str],
        dominant_change: Optional[dict],
    ) -> dict:
        return {
            "should_send": bool(should_send),
            "email_type": email_type,
            "shift_score": round(float(shift_score), 1),
            "old_archetype": old_archetype,
            "new_archetype": new_archetype,
            "dominant_change": dominant_change,
        }

    def _direction(self, delta: float) -> str:
        if delta > 0:
            return "increased"
        if delta < 0:
            return "decreased"
        return "unchanged"

    def _to_float(self, value) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0


def evaluate_retention(
    previous_snapshot: Optional[dict],
    latest_snapshot: Optional[dict],
    shift_threshold: float = DEFAULT_SHIFT_THRESHOLD,
) -> dict:
    return RetentionEngine(shift_threshold=shift_threshold).evaluate(
        previous_snapshot,
        latest_snapshot,
    )
