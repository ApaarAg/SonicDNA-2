import datetime
import uuid
from sqlalchemy import Column, String, Integer, DateTime, Text, Float, Boolean, ForeignKey
from sqlalchemy.orm import relationship

try:
    from app.database import Base
    from app.models import User
except ImportError:
    from app_database import Base, User

class SpotifySearchCache(Base):
    __tablename__ = "spotify_search_cache"
    __table_args__ = {"extend_existing": True}
    
    query_hash = Column(String(64), primary_key=True)
    search_query = Column(String(500), nullable=False)
    spotify_id = Column(String(100), nullable=False)
    spotify_uri = Column(String(255), nullable=False)
    track_name = Column(String(500), nullable=False)
    artist_name = Column(String(500), nullable=False)
    popularity = Column(Integer, default=0, nullable=False)
    duration_ms = Column(Integer, default=0, nullable=False)
    preview_url = Column(String(1000), nullable=True)
    audio_features = Column(Text, nullable=True) # JSON string representation
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)

class RecommendationCache(Base):
    __tablename__ = "recommendation_cache"
    __table_args__ = {"extend_existing": True}
    
    id = Column(User.id.type, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(User.id.type, ForeignKey("users.id"), nullable=False)
    genome_snapshot_id = Column(User.id.type, ForeignKey("genome_snapshots.id"), nullable=False)
    context_key = Column(String(255), nullable=False)
    recommendations_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)

    user = relationship("User", foreign_keys=[user_id])

class LocalModelConfig(Base):
    __tablename__ = "local_model_configs"
    __table_args__ = {"extend_existing": True}
    
    task_name = Column(String(100), primary_key=True)
    model_name = Column(String(255), nullable=False)
    temperature = Column(Float, default=0.7, nullable=False)
    max_tokens = Column(Integer, default=512, nullable=False)
    top_p = Column(Float, default=0.9, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
