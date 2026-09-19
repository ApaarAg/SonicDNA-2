# ============================================
# ARCHETYPE LEADERBOARD — Phase 2 Shareability
# ============================================

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import desc, func

from app_database import (
    GenomeSnapshot,
    SessionLocal,
    User,
    UserLocation,
    create_new_module_tables,
)

# ── City/Region Mapping ──────────────────────
CITY_REGIONS = {
    # India
    "delhi": {"country": "India", "display": "Delhi"},
    "mumbai": {"country": "India", "display": "Mumbai"},
    "bangalore": {"country": "India", "display": "Bangalore"},
    "hyderabad": {"country": "India", "display": "Hyderabad"},
    "chennai": {"country": "India", "display": "Chennai"},
    "kolkata": {"country": "India", "display": "Kolkata"},
    "pune": {"country": "India", "display": "Pune"},
    "ahmedabad": {"country": "India", "display": "Ahmedabad"},
    # US
    "new york": {"country": "USA", "display": "New York"},
    "los angeles": {"country": "USA", "display": "Los Angeles"},
    "chicago": {"country": "USA", "display": "Chicago"},
    "san francisco": {"country": "USA", "display": "San Francisco"},
    "austin": {"country": "USA", "display": "Austin"},
    "seattle": {"country": "USA", "display": "Seattle"},
    # Europe
    "london": {"country": "UK", "display": "London"},
    "paris": {"country": "France", "display": "Paris"},
    "berlin": {"country": "Germany", "display": "Berlin"},
    "amsterdam": {"country": "Netherlands", "display": "Amsterdam"},
    # Asia
    "tokyo": {"country": "Japan", "display": "Tokyo"},
    "seoul": {"country": "South Korea", "display": "Seoul"},
    "singapore": {"country": "Singapore", "display": "Singapore"},
    "bangkok": {"country": "Thailand", "display": "Bangkok"},
}

# Archetype display names (matching engine.py)
ARCHETYPE_NAMES = {
    0: "Architect of Silence",
    1: "Storm Chaser",
    2: "Midnight Drifter",
    3: "Eternal Optimist",
    4: "Cartographer",
    5: "Quiet Storm",
    6: "Wordsmith",
}

ARCHETYPE_EMOJIS = {
    0: "🎼",
    1: "⚡",
    2: "🌙",
    3: "☀️",
    4: "🗺️",
    5: "🌊",
    6: "📝",
}


# ── Database Schema ──────────────────────────

def create_city_tracking_table() -> None:
    """Create table to track user cities/regions."""
    create_new_module_tables()
    print("✅ User locations table verified")


# ── Location Tracking ────────────────────────

def save_user_location(
    user_id: str,
    city: str,
    country: Optional[str] = None,
    region: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> None:
    """Save or update user's detected location."""
    with SessionLocal() as db:
        loc = db.query(UserLocation).filter(UserLocation.user_id == user_id).first()
        if loc:
            loc.city = city
            loc.country = country
            loc.region = region
            loc.ip_address = ip_address
            loc.detected_at = datetime.utcnow()
        else:
            loc = UserLocation(
                id=str(uuid.uuid4()),
                user_id=user_id,
                city=city,
                country=country,
                region=region,
                ip_address=ip_address,
                detected_at=datetime.utcnow(),
            )
            db.add(loc)
        db.commit()


# ── Leaderboard Calculations ─────────────────

def get_city_archetype_distribution(city: str, min_users: int = 5) -> Optional[dict]:
    """Get archetype distribution for a specific city."""
    normalized_city = (city or "").strip().lower()
    with SessionLocal() as db:
        # Get latest snapshot per user
        latest_subq = (
            db.query(
                GenomeSnapshot.user_id,
                func.max(GenomeSnapshot.taken_at).label("max_taken")
            )
            .group_by(GenomeSnapshot.user_id)
            .subquery()
        )

        rows = (
            db.query(
                GenomeSnapshot.archetype_id,
                GenomeSnapshot.archetype_name,
                func.count(UserLocation.user_id).label("user_count"),
            )
            .join(UserLocation, UserLocation.user_id == GenomeSnapshot.user_id)
            .join(
                latest_subq,
                (GenomeSnapshot.user_id == latest_subq.c.user_id)
                & (GenomeSnapshot.taken_at == latest_subq.c.max_taken)
            )
            .filter(func.lower(UserLocation.city) == normalized_city)
            .group_by(GenomeSnapshot.archetype_id, GenomeSnapshot.archetype_name)
            .order_by(desc("user_count"))
            .all()
        )

        if not rows:
            return None

        total_users = sum(r[2] for r in rows)
        if total_users < min_users:
            return {
                "city": city,
                "total_users": total_users,
                "insufficient_data": True,
                "message": f"Need at least {min_users} users to show city stats",
            }

        distribution = []
        for r in rows:
            arch_id = r[0] or 0
            arch_name = r[1] or ARCHETYPE_NAMES.get(arch_id, "Unknown")
            cnt = r[2]
            pct = (cnt / total_users) * 100 if total_users > 0 else 0
            distribution.append({
                "archetype_id": arch_id,
                "archetype_name": arch_name,
                "emoji": ARCHETYPE_EMOJIS.get(arch_id, "🎵"),
                "count": cnt,
                "percentage": round(pct, 1),
                "is_dominant": pct >= 20,
            })

        distribution.sort(key=lambda x: x["percentage"], reverse=True)
        return {
            "city": city,
            "total_users": total_users,
            "distribution": distribution,
            "dominant_archetype": distribution[0] if distribution else None,
            "insufficient_data": False,
        }


def get_top_cities_leaderboard(limit: int = 20, min_users_per_city: int = 5) -> List[dict]:
    """Get leaderboard of cities with most users."""
    with SessionLocal() as db:
        city_counts = (
            db.query(
                UserLocation.city,
                UserLocation.country,
                func.count(func.distinct(UserLocation.user_id)).label("u_cnt"),
            )
            .filter(UserLocation.city.isnot(None))
            .group_by(UserLocation.city, UserLocation.country)
            .having(func.count(func.distinct(UserLocation.user_id)) >= min_users_per_city)
            .order_by(desc("u_cnt"))
            .limit(limit)
            .all()
        )

        cities = []
        for row in city_counts:
            city_name = row[0]
            country_name = row[1]
            user_cnt = row[2]
            dist = get_city_archetype_distribution(city_name, min_users=min_users_per_city)
            if dist and not dist.get("insufficient_data"):
                cities.append({
                    "city": city_name,
                    "country": country_name,
                    "user_count": user_cnt,
                    "dominant_archetype": dist["dominant_archetype"],
                    "distribution": dist["distribution"],
                })
        return cities


def get_archetype_strongholds(archetype_id: int, limit: int = 10) -> List[dict]:
    """Find cities where a specific archetype is most dominant."""
    with SessionLocal() as db:
        latest_subq = (
            db.query(
                GenomeSnapshot.user_id,
                func.max(GenomeSnapshot.taken_at).label("max_taken")
            )
            .group_by(GenomeSnapshot.user_id)
            .subquery()
        )

        city_users = (
            db.query(
                UserLocation.city,
                UserLocation.country,
                GenomeSnapshot.archetype_id,
                func.count(UserLocation.user_id).label("arch_cnt"),
            )
            .join(
                latest_subq,
                (GenomeSnapshot.user_id == latest_subq.c.user_id)
                & (GenomeSnapshot.taken_at == latest_subq.c.max_taken)
            )
            .join(UserLocation, UserLocation.user_id == GenomeSnapshot.user_id)
            .filter(GenomeSnapshot.archetype_id == archetype_id, UserLocation.city.isnot(None))
            .group_by(UserLocation.city, UserLocation.country, GenomeSnapshot.archetype_id)
            .having(func.count(UserLocation.user_id) >= 3)
            .all()
        )

        strongholds = []
        for c in city_users:
            city_name = c[0]
            country_name = c[1]
            arch_cnt = c[3]
            total_city = db.query(func.count(func.distinct(UserLocation.user_id))).filter(UserLocation.city == city_name).scalar() or 1
            if total_city >= 5:
                pct = (arch_cnt / total_city) * 100
                strongholds.append({
                    "city": city_name,
                    "country": country_name,
                    "archetype_count": arch_cnt,
                    "total_city_users": total_city,
                    "percentage": round(pct, 1),
                    "archetype_id": archetype_id,
                    "archetype_name": ARCHETYPE_NAMES.get(archetype_id, "Unknown"),
                })

        strongholds.sort(key=lambda s: (s["percentage"], s["archetype_count"]), reverse=True)
        return strongholds[:limit]


def get_global_archetype_distribution() -> dict:
    """Get platform-wide archetype distribution."""
    with SessionLocal() as db:
        latest_subq = (
            db.query(
                GenomeSnapshot.user_id,
                func.max(GenomeSnapshot.taken_at).label("max_taken")
            )
            .group_by(GenomeSnapshot.user_id)
            .subquery()
        )

        rows = (
            db.query(
                GenomeSnapshot.archetype_id,
                GenomeSnapshot.archetype_name,
                func.count(GenomeSnapshot.user_id).label("cnt"),
            )
            .join(
                latest_subq,
                (GenomeSnapshot.user_id == latest_subq.c.user_id)
                & (GenomeSnapshot.taken_at == latest_subq.c.max_taken)
            )
            .group_by(GenomeSnapshot.archetype_id, GenomeSnapshot.archetype_name)
            .order_by(desc("cnt"))
            .all()
        )

        total_users = sum(r[2] for r in rows)
        distribution = []
        for r in rows:
            arch_id = r[0] or 0
            arch_name = r[1] or ARCHETYPE_NAMES.get(arch_id, "Unknown")
            cnt = r[2]
            pct = (cnt / total_users) * 100 if total_users > 0 else 0
            distribution.append({
                "archetype_id": arch_id,
                "archetype_name": arch_name,
                "emoji": ARCHETYPE_EMOJIS.get(arch_id, "🎵"),
                "count": cnt,
                "percentage": round(pct, 1),
            })

        return {
            "total_users": total_users,
            "distribution": distribution,
        }


def compare_city_vs_global(city: str) -> dict:
    """Compare a city's archetype distribution vs global average."""
    city_dist = get_city_archetype_distribution(city)
    global_dist = get_global_archetype_distribution()

    if not city_dist or city_dist.get("insufficient_data"):
        return {
            "error": "Insufficient data for this city",
            "city": city,
        }

    global_percentages = {
        item["archetype_id"]: item["percentage"]
        for item in global_dist["distribution"]
    }

    comparisons = []
    for city_item in city_dist["distribution"]:
        arch_id = city_item["archetype_id"]
        city_pct = city_item["percentage"]
        global_pct = global_percentages.get(arch_id, 0.0)
        diff = city_pct - global_pct

        comparisons.append({
            "archetype_id": arch_id,
            "archetype_name": city_item["archetype_name"],
            "emoji": city_item["emoji"],
            "city_percentage": city_pct,
            "global_percentage": round(global_pct, 1),
            "difference": round(diff, 1),
            "status": "overrepresented" if diff > 5 else "underrepresented" if diff < -5 else "normal",
        })

    comparisons.sort(key=lambda x: abs(x["difference"]), reverse=True)
    return {
        "city": city,
        "total_users": city_dist["total_users"],
        "comparisons": comparisons,
        "dominant_archetype": city_dist["dominant_archetype"],
        "unique_characteristics": [
            comp for comp in comparisons[:3]
            if abs(comp["difference"]) > 5
        ],
    }


def generate_city_shareable_text(city: str) -> str:
    """Generate shareable social media text about a city's music taste."""
    city_dist = get_city_archetype_distribution(city)
    if not city_dist or city_dist.get("insufficient_data"):
        return f"{city}'s music genome is still being decoded... Be the first to map it! 🎵"

    dominant = city_dist["dominant_archetype"]
    second = city_dist["distribution"][1] if len(city_dist["distribution"]) > 1 else None
    text = f"{city} is {dominant['percentage']}% {dominant['archetype_name']}s {dominant['emoji']}"
    if second:
        text += f" and {second['percentage']}% {second['archetype_name']}s {second['emoji']}"
    text += f". {city_dist['total_users']} people mapped."
    return text


def get_city_comparison_headline(city_a: str, city_b: str) -> Optional[dict]:
    """Generate comparison headline between two cities."""
    dist_a = get_city_archetype_distribution(city_a)
    dist_b = get_city_archetype_distribution(city_b)
    if not dist_a or not dist_b or dist_a.get("insufficient_data") or dist_b.get("insufficient_data"):
        return None

    dom_a = dist_a["dominant_archetype"]
    dom_b = dist_b["dominant_archetype"]
    return {
        "city_a": city_a,
        "city_b": city_b,
        "headline": f"{city_a} ({dom_a['percentage']}% {dom_a['archetype_name']}) vs {city_b} ({dom_b['percentage']}% {dom_b['archetype_name']})",
        "winner": city_a if dom_a["percentage"] > dom_b["percentage"] else city_b,
        "archetype_a": dom_a,
        "archetype_b": dom_b,
    }