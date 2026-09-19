import os
import sys
import uuid
import datetime
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(__file__))

import main
import hashlib
import recommendations
recommendations.get_user_spotify_tracks = lambda user_id: []

from app_database import Base, get_db
from genome_evolution import GenomeSnapshot, User
from models.recommendation_models import SpotifySearchCache, RecommendationCache, LocalModelConfig

from sqlalchemy.ext.compiler import compiles
try:
    from sqlalchemy.dialects.mssql import UNIQUEIDENTIFIER
    @compiles(UNIQUEIDENTIFIER, "sqlite")
    def compile_uniqueidentifier(element, compiler, **kw):
        return "VARCHAR(36)"
        
    def safe_bind_processor(self, dialect):
        def process(value):
            if value is None:
                return None
            if hasattr(value, "hex"):
                return str(value)
            return str(value)
        return process
    UNIQUEIDENTIFIER.bind_processor = safe_bind_processor
    
    def safe_result_processor(self, dialect, coltype):
        def process(value):
            if value is None:
                return None
            try:
                import uuid
                return uuid.UUID(value)
            except ValueError:
                return str(value)
        return process
    UNIQUEIDENTIFIER.result_processor = safe_result_processor
except ImportError:
    pass

from sqlalchemy.pool import StaticPool

# Setup a clean test database using SQLite in memory
TEST_DB_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Re-route SQLAlchemy dependency
def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

main.app.dependency_overrides[get_db] = override_get_db

@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    
    # Pre-seed User, Snapshot, and model configs
    db = TestingSessionLocal()
    
    user = User(id="test-user-id", username="Test User", email="test@example.com")
    db.add(user)
    db.commit()
    
    snapshot = GenomeSnapshot(
        id="test-snapshot-id",
        user_id="test-user-id",
        archetype="curator",
        shadow_archetype="rebel",
        genome_data='{"danceability": 0.8, "energy": 0.7, "valence": 0.6, "acousticness": 0.2, "instrumentalness": 0.1, "speechiness": 0.05, "tempo": 120.0}'
    )
    db.add(snapshot)
    
    # Seed local model configs
    db.add(LocalModelConfig(task_name="archetype", model_name="llama3.1:8b", temperature=0.7, max_tokens=768))
    db.add(LocalModelConfig(task_name="candidates", model_name="qwen2.5:8b", temperature=0.85, max_tokens=1024))
    db.add(LocalModelConfig(task_name="narrative", model_name="llama3.1:8b", temperature=0.7, max_tokens=768))
    
    db.commit()
    db.close()
    
    yield
    
    # Cleanup
    Base.metadata.drop_all(bind=engine)

def test_generate_recommendations_workflow():
    client = TestClient(main.app)
    
    # 1. Generate first time (cache miss)
    payload = {
        "user_id": "test-user-id",
        "mood": "chill",
        "intent": "discovery",
        "discovery_ratio": 0.7,
        "exploration_ratio": 0.1,
        "use_cache": True
    }
    
    resp = client.post("/recommendations/generate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    
    assert data["user_id"] == "test-user-id"
    assert data["archetype"] == "curator"
    assert len(data["tracks"]) > 0
    assert not data["cached"]
    rec_id = data["recommendation_id"]
    
    # 2. Generate second time (cache hit)
    resp2 = client.post("/recommendations/generate", json=payload)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["cached"]
    assert data2["recommendation_id"] == rec_id

def test_recommendation_cache_clear():
    client = TestClient(main.app)
    
    payload = {
        "user_id": "test-user-id",
        "mood": "chill",
        "intent": "discovery",
        "use_cache": True
    }
    
    # First generate to make sure it's cached
    client.post("/recommendations/generate", json=payload)
    
    # Evict cache
    clear_resp = client.delete("/recommendations/cache/test-user-id")
    assert clear_resp.status_code == 200
    assert clear_resp.json()["deleted_count"] > 0
    
    # Generate again (should be cache miss now)
    resp = client.post("/recommendations/generate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert not data["cached"]

def test_spotify_search_cache_hits(monkeypatch):
    db = TestingSessionLocal()
    
    # Pre-seed one query in the search cache
    normalized = "sigur rós|svefn-g-englar"
    qh = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    db.add(SpotifySearchCache(
        query_hash=qh,
        search_query="Sigur Rós - Svefn-g-englar",
        spotify_id="spotify-track-id-123",
        spotify_uri="spotify:track:spotify-track-id-123",
        track_name="Svefn-g-englar",
        artist_name="Sigur Rós",
        popularity=62,
        duration_ms=540000,
        audio_features='{"danceability": 0.15, "energy": 0.25, "valence": 0.08}',
        expires_at=datetime.datetime.utcnow() + datetime.timedelta(days=30)
    ))
    db.commit()
    
    # Mock local LLM client candidate generator to return ONLY this track
    from recommendations import RecommendationService
    
    class MockLocalLLM:
        def interpret_archetype(self, genome, archetype, shadow):
            return {"target_moods": ["chill"], "adjacent_genres": ["post-rock"]}
        def generate_candidates(self, archetype, moods, genres, seeds):
            return [{"track_name": "Svefn-g-englar", "artist_name": "Sigur Rós"}]
        def generate_narrative(self, username, archetype, tracks, genome):
            return "Custom post-rock explanation."
            
    # Swap out LocalLLM in service
    def mock_init(self, db):
        self.db = db
        self.local_llm = MockLocalLLM()
        self.spotify = None # No live Spotify API calls
        
    monkeypatch.setattr(RecommendationService, "__init__", mock_init)
    
    client = TestClient(main.app)
    resp = client.post("/recommendations/generate", json={
        "user_id": "test-user-id",
        "mood": "deep-focus",
        "use_cache": False
    })
    
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["tracks"]) == 1
    assert data["tracks"][0]["spotify_uri"] == "spotify:track:spotify-track-id-123"
    assert data["tracks"][0]["track_name"] == "Svefn-g-englar"
    
    db.close()
