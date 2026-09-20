import os
import uuid
import json
from datetime import datetime
from app_database import SessionLocal, User, GenomeSnapshot
from main import app
from fastapi.testclient import TestClient

client = TestClient(app)

def test_comparison():
    with SessionLocal() as db:
        u1_id = str(uuid.uuid4())
        u2_id = str(uuid.uuid4())
        
        # User 1
        u1 = User(id=u1_id, display_name="Test User A")
        db.add(u1)
        snap1 = GenomeSnapshot(
            id=str(uuid.uuid4()),
            user_id=u1_id,
            genome=json.dumps({"energy": 0.8, "valence": 0.8}),
            archetype_name="Neon Dreamer"
        )
        db.add(snap1)
        
        # User 2
        u2 = User(id=u2_id, display_name="Test User B")
        db.add(u2)
        snap2 = GenomeSnapshot(
            id=str(uuid.uuid4()),
            user_id=u2_id,
            genome=json.dumps({"energy": 0.9, "valence": 0.7}),
            archetype_name="Sonic Explorer"
        )
        db.add(snap2)
        
        db.commit()
        
    print(f"Testing direct compare for {u1_id} and {u2_id}")
    
    # We will need a token to hit /compatibility/compare. Let's create a fake session token
    # Wait, the auth is handled by resolve_payload_user which checks redis or the token.
    # To test without a real token, I can mock it or use the backend function directly.
    from main import compare_internal
    result = compare_internal(u1_id, u2_id)
    print("Comparison Result:", json.dumps(result, indent=2))

if __name__ == "__main__":
    test_comparison()
