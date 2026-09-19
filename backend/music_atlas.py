"""
music_atlas.py
==============
SonicDNA — Music Atlas Module

Powers the Atlas section of SonicDNA: an interactive globe and flow-map
that visualises how users discover music across regions, cultures, and
countries.

Assumptions about the existing SonicDNA codebase
-------------------------------------------------
* A shared SQLAlchemy `Base`, `SessionLocal`, and `get_db` already exist
  (imported from `app.database`).
* A `User` ORM model already exists with at least:
    - id              : int (primary key)
    - username        : str
    - archetype       : str | None
    - country         : str | None  (ISO-3166-1 alpha-2 or full name)
* Environment variable DATABASE_URL is already configured.

New database objects introduced here
--------------------------------------
* CountryNode     — one row per country present in the atlas
* DiscoveryPath   — one row per user music-discovery event
* CountryLink     — aggregated flow between two countries (materialised cache)

Frontend consumers
------------------
* Interactive globe  → /atlas/countries  (lat/lon + listener_count)
* Flow map           → /atlas/flows      (source → destination + strength)
* Country network    → /atlas/countries + /atlas/flows combined
* Archetype heat-map → /atlas/archetype-map
"""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    desc,
    func,
    text,
)
from sqlalchemy.orm import Session, relationship

# ---------------------------------------------------------------------------
# Shared database objects
# ---------------------------------------------------------------------------
try:
    from app.database import Base, SessionLocal, get_db  # type: ignore
    from app.models import User  # type: ignore
except ImportError:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import declarative_base, sessionmaker

    _DB_URL = os.getenv("DATABASE_URL", "sqlite:///./sonic_dna_dev.db")
    _engine = create_engine(
        _DB_URL,
        connect_args={"check_same_thread": False} if "sqlite" in _DB_URL else {},
    )
    Base = declarative_base()
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

    def get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    class User(Base):  # type: ignore[no-redef]
        __tablename__ = "users"
        id       = Column(Integer, primary_key=True, index=True)
        username = Column(String(120), unique=True, nullable=False)
        archetype = Column(String(80), nullable=True)
        country  = Column(String(120), nullable=True)


USER_ID_TYPE = User.id.type

# ---------------------------------------------------------------------------
# Geographic reference data
# ---------------------------------------------------------------------------

# ISO-3166-1 alpha-2 → (country name, latitude, longitude, region, subregion)
GEO_REFERENCE: Dict[str, Tuple[str, float, float, str, str]] = {
    "AF": ("Afghanistan",          33.93, 67.71, "Asia",    "Southern Asia"),
    "AL": ("Albania",              41.15, 20.17, "Europe",  "Southern Europe"),
    "DZ": ("Algeria",              28.03,  1.66, "Africa",  "Northern Africa"),
    "AO": ("Angola",              -11.20, 17.87, "Africa",  "Middle Africa"),
    "AR": ("Argentina",           -38.42,-63.62, "Americas","South America"),
    "AU": ("Australia",           -25.27,133.77, "Oceania", "Australia and NZ"),
    "AT": ("Austria",              47.52, 14.55, "Europe",  "Western Europe"),
    "AZ": ("Azerbaijan",           40.14, 47.58, "Asia",    "Western Asia"),
    "BH": ("Bahrain",              26.00, 50.55, "Asia",    "Western Asia"),
    "BD": ("Bangladesh",           23.68, 90.36, "Asia",    "Southern Asia"),
    "BY": ("Belarus",              53.71, 27.95, "Europe",  "Eastern Europe"),
    "BE": ("Belgium",              50.50,  4.47, "Europe",  "Western Europe"),
    "BO": ("Bolivia",             -16.29,-63.59, "Americas","South America"),
    "BA": ("Bosnia and Herzegovina",43.92,17.68, "Europe",  "Southern Europe"),
    "BR": ("Brazil",              -14.24,-51.93, "Americas","South America"),
    "BG": ("Bulgaria",             42.73, 25.49, "Europe",  "Eastern Europe"),
    "KH": ("Cambodia",             12.57,104.99, "Asia",    "South-Eastern Asia"),
    "CM": ("Cameroon",              3.85, 11.50, "Africa",  "Middle Africa"),
    "CA": ("Canada",               56.13,-106.35,"Americas","Northern America"),
    "CL": ("Chile",               -35.68,-71.54, "Americas","South America"),
    "CN": ("China",                35.86,104.20, "Asia",    "Eastern Asia"),
    "CO": ("Colombia",              4.57,-74.30, "Americas","South America"),
    "CR": ("Costa Rica",            9.75,-83.75, "Americas","Central America"),
    "HR": ("Croatia",              45.10, 15.20, "Europe",  "Southern Europe"),
    "CU": ("Cuba",                 21.52,-77.78, "Americas","Caribbean"),
    "CY": ("Cyprus",               35.13, 33.43, "Asia",    "Western Asia"),
    "CZ": ("Czech Republic",       49.82, 15.47, "Europe",  "Eastern Europe"),
    "DK": ("Denmark",              56.26,  9.50, "Europe",  "Northern Europe"),
    "EC": ("Ecuador",              -1.83,-78.18, "Americas","South America"),
    "EG": ("Egypt",                26.82, 30.80, "Africa",  "Northern Africa"),
    "EE": ("Estonia",              58.60, 25.01, "Europe",  "Northern Europe"),
    "ET": ("Ethiopia",              9.15, 40.49, "Africa",  "Eastern Africa"),
    "FI": ("Finland",              61.92, 25.75, "Europe",  "Northern Europe"),
    "FR": ("France",               46.23,  2.21, "Europe",  "Western Europe"),
    "GE": ("Georgia",              42.32, 43.36, "Asia",    "Western Asia"),
    "DE": ("Germany",              51.17, 10.45, "Europe",  "Western Europe"),
    "GH": ("Ghana",                 7.95, -1.02, "Africa",  "Western Africa"),
    "GR": ("Greece",               39.07, 21.82, "Europe",  "Southern Europe"),
    "GT": ("Guatemala",            15.78,-90.23, "Americas","Central America"),
    "HN": ("Honduras",             15.20,-86.24, "Americas","Central America"),
    "HK": ("Hong Kong",            22.39,114.11, "Asia",    "Eastern Asia"),
    "HU": ("Hungary",              47.16, 19.50, "Europe",  "Eastern Europe"),
    "IN": ("India",                20.59, 78.96, "Asia",    "Southern Asia"),
    "ID": ("Indonesia",            -0.79,113.92, "Asia",    "South-Eastern Asia"),
    "IR": ("Iran",                 32.43, 53.69, "Asia",    "Southern Asia"),
    "IQ": ("Iraq",                 33.22, 43.68, "Asia",    "Western Asia"),
    "IE": ("Ireland",              53.41, -8.24, "Europe",  "Northern Europe"),
    "IL": ("Israel",               31.05, 34.85, "Asia",    "Western Asia"),
    "IT": ("Italy",                41.87, 12.57, "Europe",  "Southern Europe"),
    "CI": ("Ivory Coast",           7.54, -5.55, "Africa",  "Western Africa"),
    "JP": ("Japan",                36.20,138.25, "Asia",    "Eastern Asia"),
    "JO": ("Jordan",               30.59, 36.24, "Asia",    "Western Asia"),
    "KZ": ("Kazakhstan",           48.02, 66.92, "Asia",    "Central Asia"),
    "KE": ("Kenya",                -0.02, 37.91, "Africa",  "Eastern Africa"),
    "KW": ("Kuwait",               29.31, 47.49, "Asia",    "Western Asia"),
    "LB": ("Lebanon",              33.85, 35.86, "Asia",    "Western Asia"),
    "LY": ("Libya",                26.34, 17.23, "Africa",  "Northern Africa"),
    "LT": ("Lithuania",            55.17, 23.88, "Europe",  "Northern Europe"),
    "LU": ("Luxembourg",           49.82,  6.13, "Europe",  "Western Europe"),
    "MY": ("Malaysia",              4.21,108.05, "Asia",    "South-Eastern Asia"),
    "MX": ("Mexico",               23.63,-102.55,"Americas","Central America"),
    "MA": ("Morocco",              31.79, -7.09, "Africa",  "Northern Africa"),
    "NL": ("Netherlands",          52.13,  5.29, "Europe",  "Western Europe"),
    "NZ": ("New Zealand",         -40.90,174.89, "Oceania", "Australia and NZ"),
    "NG": ("Nigeria",               9.08,  8.68, "Africa",  "Western Africa"),
    "MK": ("North Macedonia",      41.61, 21.75, "Europe",  "Southern Europe"),
    "NO": ("Norway",               60.47,  8.47, "Europe",  "Northern Europe"),
    "PK": ("Pakistan",             30.38, 69.35, "Asia",    "Southern Asia"),
    "PA": ("Panama",                8.54,-80.78, "Americas","Central America"),
    "PY": ("Paraguay",            -23.44,-58.44, "Americas","South America"),
    "PE": ("Peru",                 -9.19,-75.02, "Americas","South America"),
    "PH": ("Philippines",          12.88,121.77, "Asia",    "South-Eastern Asia"),
    "PL": ("Poland",               51.92, 19.15, "Europe",  "Eastern Europe"),
    "PT": ("Portugal",             39.40, -8.22, "Europe",  "Southern Europe"),
    "QA": ("Qatar",                25.35, 51.18, "Asia",    "Western Asia"),
    "RO": ("Romania",              45.94, 24.97, "Europe",  "Eastern Europe"),
    "RU": ("Russia",               61.52,105.32, "Europe",  "Eastern Europe"),
    "SA": ("Saudi Arabia",         23.89, 45.08, "Asia",    "Western Asia"),
    "SN": ("Senegal",              14.50,-14.45, "Africa",  "Western Africa"),
    "RS": ("Serbia",               44.02, 21.01, "Europe",  "Southern Europe"),
    "SG": ("Singapore",             1.35,103.82, "Asia",    "South-Eastern Asia"),
    "SK": ("Slovakia",             48.67, 19.70, "Europe",  "Eastern Europe"),
    "SI": ("Slovenia",             46.15, 14.99, "Europe",  "Southern Europe"),
    "ZA": ("South Africa",        -30.56, 22.94, "Africa",  "Southern Africa"),
    "KR": ("South Korea",          35.91,127.77, "Asia",    "Eastern Asia"),
    "ES": ("Spain",                40.46, -3.75, "Europe",  "Southern Europe"),
    "LK": ("Sri Lanka",             7.87, 80.77, "Asia",    "Southern Asia"),
    "SE": ("Sweden",               60.13, 18.64, "Europe",  "Northern Europe"),
    "CH": ("Switzerland",          46.82,  8.23, "Europe",  "Western Europe"),
    "SY": ("Syria",                34.80, 38.99, "Asia",    "Western Asia"),
    "TW": ("Taiwan",               23.70,121.00, "Asia",    "Eastern Asia"),
    "TZ": ("Tanzania",             -6.37, 34.89, "Africa",  "Eastern Africa"),
    "TH": ("Thailand",             15.87,100.99, "Asia",    "South-Eastern Asia"),
    "TN": ("Tunisia",              33.89,  9.54, "Africa",  "Northern Africa"),
    "TR": ("Turkey",               38.96, 35.24, "Asia",    "Western Asia"),
    "UA": ("Ukraine",              48.38, 31.17, "Europe",  "Eastern Europe"),
    "AE": ("United Arab Emirates", 23.42, 53.85, "Asia",    "Western Asia"),
    "GB": ("United Kingdom",       55.38, -3.44, "Europe",  "Northern Europe"),
    "US": ("United States",        37.09,-95.71, "Americas","Northern America"),
    "UY": ("Uruguay",             -32.52,-55.77, "Americas","South America"),
    "UZ": ("Uzbekistan",           41.38, 64.59, "Asia",    "Central Asia"),
    "VE": ("Venezuela",             6.42,-66.59, "Americas","South America"),
    "VN": ("Vietnam",              14.06,108.28, "Asia",    "South-Eastern Asia"),
    "YE": ("Yemen",                15.55, 48.52, "Asia",    "Western Asia"),
    "ZM": ("Zambia",              -13.13, 27.85, "Africa",  "Eastern Africa"),
    "ZW": ("Zimbabwe",            -19.02, 29.15, "Africa",  "Eastern Africa"),
}


# ---------------------------------------------------------------------------
# ORM Models
# ---------------------------------------------------------------------------

class CountryNode(Base):
    """
    One row per country represented in the Atlas.
    `listener_count` is updated incrementally as discovery paths are added.
    """
    __tablename__ = "atlas_country_nodes"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    country_code   = Column(String(8),   nullable=False, unique=True, index=True)
    country_name   = Column(String(120), nullable=False)
    region         = Column(String(80),  nullable=True)
    subregion      = Column(String(80),  nullable=True)
    latitude       = Column(Float,       nullable=True)
    longitude      = Column(Float,       nullable=True)
    listener_count = Column(Integer,     nullable=False, default=0)
    influence_score = Column(Float,      nullable=False, default=0.0)
    updated_at     = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_atlas_country_listeners", "listener_count"),
        Index("ix_atlas_country_influence", "influence_score"),
        Index("ix_atlas_country_region",    "region"),
    )


class DiscoveryPath(Base):
    """
    One row per cross-cultural music discovery event.
    Represents a user consuming music that originated in a country
    different from their own.
    """
    __tablename__ = "atlas_discovery_paths"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    user_id             = Column(USER_ID_TYPE, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source_country      = Column(String(8), nullable=False)   # ISO-3166-1 alpha-2
    destination_country = Column(String(8), nullable=False)   # ISO-3166-1 alpha-2
    archetype           = Column(String(80), nullable=True)
    genre               = Column(String(80), nullable=True)   # optional enrichment
    confidence          = Column(Float, nullable=False, default=1.0)  # 0–1 signal quality
    timestamp           = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        Index("ix_dp_user_id",          "user_id"),
        Index("ix_dp_source",           "source_country"),
        Index("ix_dp_destination",      "destination_country"),
        Index("ix_dp_archetype",        "archetype"),
        Index("ix_dp_source_dest",      "source_country", "destination_country"),
        Index("ix_dp_timestamp",        "timestamp"),
    )


class CountryLink(Base):
    """
    Materialised aggregation of DiscoveryPath flows between country pairs.
    Rebuilt on demand by POST /atlas/rebuild-flows or incrementally updated.
    Drives the flow-map and globe visualisations.
    """
    __tablename__ = "atlas_country_links"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    source_country      = Column(String(8), nullable=False)
    destination_country = Column(String(8), nullable=False)
    flow_count          = Column(Integer, nullable=False, default=0)
    unique_users        = Column(Integer, nullable=False, default=0)
    avg_confidence      = Column(Float,   nullable=False, default=1.0)
    dominant_archetype  = Column(String(80), nullable=True)
    updated_at          = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("source_country", "destination_country", name="uq_country_link"),
        Index("ix_cl_source",      "source_country"),
        Index("ix_cl_destination", "destination_country"),
        Index("ix_cl_flow_count",  "flow_count"),
    )


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------

# --- Sub-schemas ---

class GeoCoordinate(BaseModel):
    lat: float
    lon: float


class CountryNodeOut(BaseModel):
    country_code:   str
    country_name:   str
    region:         Optional[str]
    subregion:      Optional[str]
    coordinates:    Optional[GeoCoordinate]
    listener_count: int
    influence_score: float
    updated_at:     datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_node(cls, node: CountryNode) -> "CountryNodeOut":
        coords = None
        if node.latitude is not None and node.longitude is not None:
            coords = GeoCoordinate(lat=node.latitude, lon=node.longitude)
        return cls(
            country_code    = node.country_code,
            country_name    = node.country_name,
            region          = node.region,
            subregion       = node.subregion,
            coordinates     = coords,
            listener_count  = node.listener_count,
            influence_score = node.influence_score,
            updated_at      = node.updated_at,
        )


class FlowOut(BaseModel):
    """A directed flow between two countries — maps directly to globe arc data."""
    source_country:      str
    source_name:         Optional[str]
    source_coords:       Optional[GeoCoordinate]
    destination_country: str
    destination_name:    Optional[str]
    destination_coords:  Optional[GeoCoordinate]
    flow_count:          int
    unique_users:        int
    strength:            float   # normalised 0–1 for arc thickness
    dominant_archetype:  Optional[str]


class DiscoveryPathOut(BaseModel):
    id:                  int
    user_id:             int
    source_country:      str
    destination_country: str
    archetype:           Optional[str]
    genre:               Optional[str]
    confidence:          float
    timestamp:           datetime

    model_config = {"from_attributes": True}


class TrendingRoute(BaseModel):
    source_country:      str
    source_name:         Optional[str]
    destination_country: str
    destination_name:    Optional[str]
    flow_count:          int
    unique_users:        int
    dominant_archetype:  Optional[str]
    velocity:            float   # recent_count / historical_avg — growth rate


class ArchetypeCountryEntry(BaseModel):
    country_code:  str
    country_name:  Optional[str]
    archetype:     str
    discovery_count: int
    share:         float   # fraction of all discoveries from this country


class ArchetypeMapEntry(BaseModel):
    archetype:   str
    countries:   List[ArchetypeCountryEntry]
    total_paths: int


# --- Endpoint responses ---

class CountriesResponse(BaseModel):
    total:     int
    countries: List[CountryNodeOut]


class FlowsResponse(BaseModel):
    total_flows:    int
    max_flow_count: int
    flows:          List[FlowOut]


class DiscoveryPathsResponse(BaseModel):
    user_id: int
    total:   int
    paths:   List[DiscoveryPathOut]


class TrendingRoutesResponse(BaseModel):
    window_days: int
    total:       int
    routes:      List[TrendingRoute]


class ArchetypeMapResponse(BaseModel):
    archetypes:        List[ArchetypeMapEntry]
    total_archetypes:  int
    total_paths:       int


class CountryInfluenceEntry(BaseModel):
    rank:           int
    country_code:   str
    country_name:   Optional[str]
    influence_score: float
    outbound_flows:  int
    inbound_flows:   int
    unique_listeners: int


class AtlasStats(BaseModel):
    total_countries:        int
    total_discovery_paths:  int
    total_unique_routes:    int
    most_influential_country: Optional[str]
    most_discovered_country:  Optional[str]
    top_archetype_explorer:   Optional[str]
    cross_regional_ratio:     float   # paths crossing region boundaries / total
    region_breakdown:         Dict[str, int]
    archetype_breakdown:      Dict[str, int]
    computed_at:              datetime


# --- Request for recording a new path ---

class DiscoveryPathCreate(BaseModel):
    user_id:             int
    source_country:      str = Field(..., min_length=2, max_length=8)
    destination_country: str = Field(..., min_length=2, max_length=8)
    archetype:           Optional[str] = None
    genre:               Optional[str] = None
    confidence:          float = Field(1.0, ge=0.0, le=1.0)
    timestamp:           Optional[datetime] = None

    @field_validator("source_country", "destination_country", mode="before")
    @classmethod
    def upper_country(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("timestamp", mode="before")
    @classmethod
    def default_ts(cls, v: Optional[datetime]) -> datetime:
        return v or datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Service Layer
# ---------------------------------------------------------------------------

class AtlasService:
    """
    All business logic for the Music Atlas.
    Read queries are served from the materialised CountryLink and CountryNode
    tables for performance.  DiscoveryPath is the source of truth for all
    per-user and trend queries.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_user_or_404(self, user_id: int) -> User:
        user = self.db.get(User, user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User {user_id} not found.",
            )
        return user

    def _get_or_create_country_node(self, code: str) -> CountryNode:
        node = (
            self.db.query(CountryNode)
            .filter(CountryNode.country_code == code)
            .first()
        )
        if node:
            return node

        ref = GEO_REFERENCE.get(code)
        node = CountryNode(
            country_code   = code,
            country_name   = ref[0] if ref else code,
            region         = ref[3] if ref else None,
            subregion      = ref[4] if ref else None,
            latitude       = ref[1] if ref else None,
            longitude      = ref[2] if ref else None,
            listener_count = 0,
            influence_score = 0.0,
        )
        self.db.add(node)
        self.db.flush()
        return node

    def _country_name(self, code: str) -> Optional[str]:
        ref = GEO_REFERENCE.get(code)
        if ref:
            return ref[0]
        node = (
            self.db.query(CountryNode.country_name)
            .filter(CountryNode.country_code == code)
            .scalar()
        )
        return node

    def _country_coords(self, code: str) -> Optional[GeoCoordinate]:
        ref = GEO_REFERENCE.get(code)
        if ref:
            return GeoCoordinate(lat=ref[1], lon=ref[2])
        row = (
            self.db.query(CountryNode.latitude, CountryNode.longitude)
            .filter(CountryNode.country_code == code)
            .first()
        )
        if row and row.latitude is not None:
            return GeoCoordinate(lat=row.latitude, lon=row.longitude)
        return None

    def _country_region(self, code: str) -> Optional[str]:
        ref = GEO_REFERENCE.get(code)
        return ref[3] if ref else None

    def _normalise_flows(self, flows: List[CountryLink]) -> Dict[int, float]:
        """Normalises flow_count to [0, 1] keyed by CountryLink.id."""
        if not flows:
            return {}
        max_count = max(f.flow_count for f in flows) or 1
        return {f.id: round(f.flow_count / max_count, 6) for f in flows}

    def _upsert_country_link(
        self,
        source: str,
        destination: str,
        dominant_archetype: Optional[str],
        confidence: float,
    ) -> None:
        link = (
            self.db.query(CountryLink)
            .filter(
                CountryLink.source_country      == source,
                CountryLink.destination_country == destination,
            )
            .first()
        )
        if link:
            link.flow_count   += 1
            link.avg_confidence = round(
                (link.avg_confidence * (link.flow_count - 1) + confidence)
                / link.flow_count, 6
            )
            if dominant_archetype:
                link.dominant_archetype = dominant_archetype
            link.updated_at = datetime.now(timezone.utc)
        else:
            link = CountryLink(
                source_country      = source,
                destination_country = destination,
                flow_count          = 1,
                unique_users        = 1,
                avg_confidence      = confidence,
                dominant_archetype  = dominant_archetype,
            )
            self.db.add(link)
        self.db.flush()

    def _recompute_influence_scores(self) -> None:
        """
        Influence score = (outbound_flows × 0.6) + (inbound_flows × 0.4)
        normalised to [0, 1000].
        """
        outbound = dict(
            self.db.query(
                CountryLink.source_country,
                func.sum(CountryLink.flow_count).label("total"),
            )
            .group_by(CountryLink.source_country)
            .all()
        )
        inbound = dict(
            self.db.query(
                CountryLink.destination_country,
                func.sum(CountryLink.flow_count).label("total"),
            )
            .group_by(CountryLink.destination_country)
            .all()
        )
        all_codes = set(outbound.keys()) | set(inbound.keys())
        raw: Dict[str, float] = {
            code: (outbound.get(code, 0) * 0.6 + inbound.get(code, 0) * 0.4)
            for code in all_codes
        }
        max_raw = max(raw.values(), default=1.0) or 1.0

        for code, score in raw.items():
            normalised = round((score / max_raw) * 1000, 4)
            self.db.query(CountryNode).filter(
                CountryNode.country_code == code
            ).update({"influence_score": normalised}, synchronize_session=False)

        self.db.flush()

    # ------------------------------------------------------------------
    # Public service methods
    # ------------------------------------------------------------------

    def record_discovery_path(self, payload: DiscoveryPathCreate) -> DiscoveryPath:
        """
        Persists a new discovery path and incrementally updates:
        - CountryNode listener counts
        - CountryLink flow aggregation
        """
        self._get_user_or_404(payload.user_id)

        path = DiscoveryPath(
            user_id             = payload.user_id,
            source_country      = payload.source_country,
            destination_country = payload.destination_country,
            archetype           = payload.archetype,
            genre               = payload.genre,
            confidence          = payload.confidence,
            timestamp           = payload.timestamp,
        )
        self.db.add(path)

        # Ensure country nodes exist
        src_node  = self._get_or_create_country_node(payload.source_country)
        dest_node = self._get_or_create_country_node(payload.destination_country)

        # Increment destination listener count
        dest_node.listener_count += 1

        # Upsert the country link
        self._upsert_country_link(
            payload.source_country,
            payload.destination_country,
            payload.archetype,
            payload.confidence,
        )

        self.db.commit()
        self.db.refresh(path)
        return path

    def get_countries(
        self,
        region: Optional[str] = None,
        min_listeners: int = 0,
        limit: int = 300,
    ) -> CountriesResponse:
        q = self.db.query(CountryNode)
        if region:
            q = q.filter(func.lower(CountryNode.region) == region.lower())
        if min_listeners > 0:
            q = q.filter(CountryNode.listener_count >= min_listeners)
        q = q.order_by(desc(CountryNode.listener_count)).limit(limit)
        nodes: List[CountryNode] = q.all()

        return CountriesResponse(
            total     = len(nodes),
            countries = [CountryNodeOut.from_orm_node(n) for n in nodes],
        )

    def get_flows(
        self,
        limit: int = 200,
        min_flow: int = 1,
        source_country: Optional[str] = None,
    ) -> FlowsResponse:
        q = (
            self.db.query(CountryLink)
            .filter(CountryLink.flow_count >= min_flow)
        )
        if source_country:
            q = q.filter(
                func.upper(CountryLink.source_country) == source_country.upper()
            )
        q = q.order_by(desc(CountryLink.flow_count)).limit(limit)
        links: List[CountryLink] = q.all()

        if not links:
            return FlowsResponse(total_flows=0, max_flow_count=0, flows=[])

        strength_map = self._normalise_flows(links)
        max_count    = max(lnk.flow_count for lnk in links)

        flows = [
            FlowOut(
                source_country      = lnk.source_country,
                source_name         = self._country_name(lnk.source_country),
                source_coords       = self._country_coords(lnk.source_country),
                destination_country = lnk.destination_country,
                destination_name    = self._country_name(lnk.destination_country),
                destination_coords  = self._country_coords(lnk.destination_country),
                flow_count          = lnk.flow_count,
                unique_users        = lnk.unique_users,
                strength            = strength_map.get(lnk.id, 0.0),
                dominant_archetype  = lnk.dominant_archetype,
            )
            for lnk in links
        ]

        return FlowsResponse(
            total_flows    = len(flows),
            max_flow_count = max_count,
            flows          = flows,
        )

    def get_discovery_paths(
        self,
        user_id: int,
        limit: int = 100,
        since: Optional[datetime] = None,
    ) -> DiscoveryPathsResponse:
        self._get_user_or_404(user_id)

        q = (
            self.db.query(DiscoveryPath)
            .filter(DiscoveryPath.user_id == user_id)
        )
        if since:
            q = q.filter(DiscoveryPath.timestamp >= since)
        q = q.order_by(desc(DiscoveryPath.timestamp)).limit(limit)

        paths: List[DiscoveryPath] = q.all()
        return DiscoveryPathsResponse(
            user_id = user_id,
            total   = len(paths),
            paths   = [DiscoveryPathOut.model_validate(p) for p in paths],
        )

    def get_trending_routes(
        self,
        window_days: int = 7,
        limit: int = 20,
    ) -> TrendingRoutesResponse:
        """
        Routes are ranked by velocity: (flows in window) / (historical avg per window).
        Routes with no historical baseline are treated as velocity = flow_count.
        """
        from datetime import timedelta

        now        = datetime.now(timezone.utc)
        window_ago = now - timedelta(days=window_days)
        baseline_days = max(window_days * 4, 28)   # compare against 4× the window
        baseline_ago  = now - timedelta(days=baseline_days)

        # Flows within the recent window
        recent_rows = (
            self.db.query(
                DiscoveryPath.source_country,
                DiscoveryPath.destination_country,
                func.count(DiscoveryPath.id).label("recent_count"),
                func.count(func.distinct(DiscoveryPath.user_id)).label("unique_users"),
                func.max(DiscoveryPath.archetype).label("top_archetype"),
            )
            .filter(DiscoveryPath.timestamp >= window_ago)
            .group_by(DiscoveryPath.source_country, DiscoveryPath.destination_country)
            .order_by(desc("recent_count"))
            .limit(limit * 2)
            .all()
        )

        # Historical baseline counts for the same pairs
        baseline_counts: Dict[Tuple[str, str], int] = {}
        if recent_rows:
            pairs = [
                (row.source_country, row.destination_country)
                for row in recent_rows
            ]
            for src, dst in pairs:
                count = (
                    self.db.query(func.count(DiscoveryPath.id))
                    .filter(
                        DiscoveryPath.source_country      == src,
                        DiscoveryPath.destination_country == dst,
                        DiscoveryPath.timestamp           >= baseline_ago,
                        DiscoveryPath.timestamp           < window_ago,
                    )
                    .scalar()
                    or 0
                )
                baseline_counts[(src, dst)] = count

        routes: List[TrendingRoute] = []
        for row in recent_rows:
            key = (row.source_country, row.destination_country)
            historical = baseline_counts.get(key, 0)
            periods    = baseline_days / window_days
            avg_historical = historical / periods if periods > 0 else 0

            if avg_historical > 0:
                velocity = round(row.recent_count / avg_historical, 4)
            else:
                velocity = float(row.recent_count)

            routes.append(
                TrendingRoute(
                    source_country      = row.source_country,
                    source_name         = self._country_name(row.source_country),
                    destination_country = row.destination_country,
                    destination_name    = self._country_name(row.destination_country),
                    flow_count          = row.recent_count,
                    unique_users        = row.unique_users,
                    dominant_archetype  = row.top_archetype,
                    velocity            = velocity,
                )
            )

        # Re-sort by velocity and cap
        routes.sort(key=lambda r: r.velocity, reverse=True)
        routes = routes[:limit]

        return TrendingRoutesResponse(
            window_days = window_days,
            total       = len(routes),
            routes      = routes,
        )

    def get_archetype_map(self) -> ArchetypeMapResponse:
        """
        For each archetype, returns which countries its listeners most
        commonly discover music from (destination country perspective).
        """
        rows = (
            self.db.query(
                DiscoveryPath.archetype,
                DiscoveryPath.destination_country,
                func.count(DiscoveryPath.id).label("discovery_count"),
            )
            .filter(DiscoveryPath.archetype.isnot(None))
            .group_by(DiscoveryPath.archetype, DiscoveryPath.destination_country)
            .order_by(DiscoveryPath.archetype, desc("discovery_count"))
            .all()
        )

        # Aggregate by archetype
        by_archetype: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
        for row in rows:
            by_archetype[row.archetype].append(
                (row.destination_country, row.discovery_count)
            )

        total_paths = sum(len(v) for v in by_archetype.values())

        archetype_entries: List[ArchetypeMapEntry] = []
        for archetype, country_counts in by_archetype.items():
            arch_total = sum(c for _, c in country_counts)
            countries  = [
                ArchetypeCountryEntry(
                    country_code    = code,
                    country_name    = self._country_name(code),
                    archetype       = archetype,
                    discovery_count = count,
                    share           = round(count / arch_total, 4) if arch_total else 0.0,
                )
                for code, count in country_counts
            ]
            archetype_entries.append(
                ArchetypeMapEntry(
                    archetype   = archetype,
                    countries   = countries,
                    total_paths = arch_total,
                )
            )

        # Sort by total_paths descending
        archetype_entries.sort(key=lambda e: e.total_paths, reverse=True)

        return ArchetypeMapResponse(
            archetypes       = archetype_entries,
            total_archetypes = len(archetype_entries),
            total_paths      = sum(e.total_paths for e in archetype_entries),
        )

    def get_stats(self) -> AtlasStats:
        total_countries = self.db.query(func.count(CountryNode.id)).scalar() or 0
        total_paths     = self.db.query(func.count(DiscoveryPath.id)).scalar() or 0
        total_routes    = self.db.query(func.count(CountryLink.id)).scalar() or 0

        most_influential = (
            self.db.query(CountryNode.country_code)
            .order_by(desc(CountryNode.influence_score))
            .first()
        )
        most_discovered = (
            self.db.query(CountryNode.country_code)
            .order_by(desc(CountryNode.listener_count))
            .first()
        )
        top_archetype_row = (
            self.db.query(
                DiscoveryPath.archetype,
                func.count(DiscoveryPath.id).label("cnt"),
            )
            .filter(DiscoveryPath.archetype.isnot(None))
            .group_by(DiscoveryPath.archetype)
            .order_by(desc("cnt"))
            .first()
        )

        # Cross-regional ratio
        cross_regional = 0
        if total_paths > 0:
            cross_paths = (
                self.db.query(func.count(DiscoveryPath.id))
                .join(
                    CountryNode,
                    CountryNode.country_code == DiscoveryPath.source_country,
                )
                .filter(
                    DiscoveryPath.destination_country != DiscoveryPath.source_country
                )
                .scalar()
                or 0
            )
            cross_regional = round(cross_paths / total_paths, 4)

        # Region breakdown
        region_rows = (
            self.db.query(
                CountryNode.region,
                func.sum(CountryNode.listener_count).label("total"),
            )
            .filter(CountryNode.region.isnot(None))
            .group_by(CountryNode.region)
            .all()
        )
        region_breakdown = {
            row.region: int(row.total or 0) for row in region_rows
        }

        # Archetype breakdown
        arch_rows = (
            self.db.query(
                DiscoveryPath.archetype,
                func.count(DiscoveryPath.id).label("cnt"),
            )
            .filter(DiscoveryPath.archetype.isnot(None))
            .group_by(DiscoveryPath.archetype)
            .all()
        )
        archetype_breakdown = {row.archetype: row.cnt for row in arch_rows}

        return AtlasStats(
            total_countries         = total_countries,
            total_discovery_paths   = total_paths,
            total_unique_routes     = total_routes,
            most_influential_country = most_influential[0] if most_influential else None,
            most_discovered_country  = most_discovered[0]  if most_discovered  else None,
            top_archetype_explorer   = top_archetype_row[0] if top_archetype_row else None,
            cross_regional_ratio     = cross_regional,
            region_breakdown         = region_breakdown,
            archetype_breakdown      = archetype_breakdown,
            computed_at              = datetime.now(timezone.utc),
        )

    def rebuild_flows(self) -> Dict[str, Any]:
        """
        Full rebuild of CountryLink and CountryNode influence scores
        from raw DiscoveryPath data.  Called by POST /atlas/rebuild-flows.
        Intended for periodic maintenance (e.g. nightly cron).
        """
        import time
        started = time.monotonic()

        # Truncate and rebuild CountryLink
        self.db.query(CountryLink).delete()
        self.db.flush()

        rows = (
            self.db.query(
                DiscoveryPath.source_country,
                DiscoveryPath.destination_country,
                func.count(DiscoveryPath.id).label("flow_count"),
                func.count(func.distinct(DiscoveryPath.user_id)).label("unique_users"),
                func.avg(DiscoveryPath.confidence).label("avg_confidence"),
                func.max(DiscoveryPath.archetype).label("dominant_archetype"),
            )
            .group_by(
                DiscoveryPath.source_country,
                DiscoveryPath.destination_country,
            )
            .all()
        )

        for row in rows:
            link = CountryLink(
                source_country      = row.source_country,
                destination_country = row.destination_country,
                flow_count          = row.flow_count,
                unique_users        = row.unique_users,
                avg_confidence      = round(float(row.avg_confidence or 1.0), 6),
                dominant_archetype  = row.dominant_archetype,
            )
            self.db.add(link)

        # Rebuild CountryNode listener counts
        dest_counts = dict(
            self.db.query(
                DiscoveryPath.destination_country,
                func.count(DiscoveryPath.id).label("cnt"),
            )
            .group_by(DiscoveryPath.destination_country)
            .all()
        )
        for code, cnt in dest_counts.items():
            node = self._get_or_create_country_node(code)
            node.listener_count = cnt

        # Ensure all source countries have nodes too
        src_codes = {row.source_country for row in rows}
        for code in src_codes:
            self._get_or_create_country_node(code)

        self.db.flush()
        self._recompute_influence_scores()
        self.db.commit()

        duration_ms = round((time.monotonic() - started) * 1000, 1)
        return {
            "status":        "completed",
            "links_rebuilt": len(rows),
            "duration_ms":   duration_ms,
            "rebuilt_at":    datetime.now(timezone.utc).isoformat(),
        }


# ---------------------------------------------------------------------------
# FastAPI Router
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/atlas",
    tags=["Music Atlas"],
    responses={
        404: {"description": "Resource not found"},
        422: {"description": "Validation error"},
        500: {"description": "Internal server error"},
    },
)


@router.get(
    "/countries",
    response_model=CountriesResponse,
    summary="Get all countries in the Atlas",
    description=(
        "Returns every CountryNode with listener count, influence score, and "
        "coordinates ready for globe rendering. "
        "Filter by `region` or `min_listeners`. "
        "Recommended cache TTL: 300 s."
    ),
)
def get_countries(
    region:        Optional[str] = Query(None, description="Filter by geographic region."),
    min_listeners: int           = Query(0,    ge=0, description="Minimum listener count."),
    limit:         int           = Query(300,  ge=1, le=500),
    db: Session = Depends(get_db),
) -> CountriesResponse:
    return AtlasService(db).get_countries(
        region=region, min_listeners=min_listeners, limit=limit
    )


@router.get(
    "/flows",
    response_model=FlowsResponse,
    summary="Get music discovery flows between countries",
    description=(
        "Returns directed country-to-country flow data with normalised strength "
        "values [0, 1] for arc thickness on the globe / flow map. "
        "Filter by `source_country` for egocentric views. "
        "Recommended cache TTL: 300 s."
    ),
)
def get_flows(
    limit:          int           = Query(200, ge=1, le=500),
    min_flow:       int           = Query(1,   ge=1, description="Minimum flow count."),
    source_country: Optional[str] = Query(None, description="ISO-3166-1 alpha-2 source filter."),
    db: Session = Depends(get_db),
) -> FlowsResponse:
    return AtlasService(db).get_flows(
        limit=limit, min_flow=min_flow, source_country=source_country
    )


@router.get(
    "/discovery-paths/{user_id}",
    response_model=DiscoveryPathsResponse,
    summary="Get a user's personal discovery paths",
    description=(
        "Returns all cross-cultural discovery events for a specific user, "
        "newest first. Optional `since` timestamp for incremental sync."
    ),
)
def get_discovery_paths(
    user_id: int,
    limit:   int               = Query(100, ge=1, le=1000),
    since:   Optional[datetime] = Query(None, description="Return paths at or after this ISO-8601 timestamp."),
    db: Session = Depends(get_db),
) -> DiscoveryPathsResponse:
    return AtlasService(db).get_discovery_paths(user_id=user_id, limit=limit, since=since)


@router.get(
    "/trending-routes",
    response_model=TrendingRoutesResponse,
    summary="Get trending music discovery routes",
    description=(
        "Returns routes ranked by velocity: recent flow count relative to "
        "historical average over the same window length. "
        "Use `window_days` to adjust the recency window (default 7 days). "
        "Recommended cache TTL: 300 s."
    ),
)
def get_trending_routes(
    window_days: int = Query(7,  ge=1, le=90,  description="Recency window in days."),
    limit:       int = Query(20, ge=1, le=100, description="Number of routes to return."),
    db: Session = Depends(get_db),
) -> TrendingRoutesResponse:
    return AtlasService(db).get_trending_routes(window_days=window_days, limit=limit)


@router.get(
    "/archetype-map",
    response_model=ArchetypeMapResponse,
    summary="Get archetype-to-country discovery mapping",
    description=(
        "For each SonicDNA archetype, returns which countries its listeners most "
        "commonly discover music from, with share percentages. "
        "Powers archetype heat-map overlays on the globe. "
        "Recommended cache TTL: 600 s."
    ),
)
def get_archetype_map(
    db: Session = Depends(get_db),
) -> ArchetypeMapResponse:
    return AtlasService(db).get_archetype_map()


@router.get(
    "/stats",
    response_model=AtlasStats,
    summary="Get Atlas network statistics",
    description=(
        "Returns aggregate Atlas metrics: total countries, discovery paths, "
        "unique routes, most influential country, cross-regional ratio, "
        "region breakdown, and archetype breakdown. "
        "Recommended cache TTL: 600 s."
    ),
)
def get_atlas_stats(
    db: Session = Depends(get_db),
) -> AtlasStats:
    return AtlasService(db).get_stats()


@router.post(
    "/discovery-paths",
    response_model=DiscoveryPathOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record a new discovery path",
    description=(
        "Persists a cross-cultural music discovery event and incrementally "
        "updates CountryNode listener counts and CountryLink flow aggregations. "
        "Call this whenever a user plays music from a different country."
    ),
)
def record_discovery_path(
    payload: DiscoveryPathCreate,
    db: Session = Depends(get_db),
) -> DiscoveryPathOut:
    path = AtlasService(db).record_discovery_path(payload)
    return DiscoveryPathOut.model_validate(path)


@router.post(
    "/rebuild-flows",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Rebuild all flow aggregations from raw paths",
    description=(
        "Full rebuild of CountryLink and influence scores from raw DiscoveryPath data. "
        "Intended for periodic maintenance (nightly cron or after bulk imports). "
        "Invalidate all atlas caches after calling this endpoint."
    ),
)
def rebuild_flows(
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return AtlasService(db).rebuild_flows()


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------

def include_router(app: Any) -> None:
    """
    Call this from your main FastAPI app file:

        from music_atlas import include_router
        include_router(app)
    """
    app.include_router(router)
