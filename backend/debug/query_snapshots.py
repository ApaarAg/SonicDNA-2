import sys
import json
from pathlib import Path

backend_path = Path("c:/Users/apaar/Desktop/SonicDNA/backend")
sys.path.append(str(backend_path))

from app_database import SessionLocal
from sqlalchemy import text

def normalize_feature(val):
    if val is None:
        return 50
    return round((float(val) + 2.0) / 4.0 * 100)

db = SessionLocal()
try:
    user_id = "EC15FB81-13CE-4D27-935F-1D40E783ACEC"
    print(f"DATABASE VALIDATION FOR USER: {user_id}")
    
    # Query snapshots ordered newest first
    query = text("""
        SELECT id, archetype_name, genome, taken_at 
        FROM genome_snapshots 
        WHERE user_id = :user_id 
        ORDER BY COALESCE(created_at, taken_at) DESC, taken_at DESC
    """)
    rows = db.execute(query, {"user_id": user_id}).fetchall()
    
    print(f"Total snapshots: {len(rows)}")
    for i, row in enumerate(rows):
        snap_id, arch_name, genome_str, taken_at = row
        genome = json.loads(genome_str) if genome_str else {}
        print(f"Snapshot {i} (Taken at: {taken_at}):")
        print(f"  Archetype: {arch_name}")
        print(f"  Genome Vector: {genome}")
        
    print("\n--- DELTA CALCULATION (Snapshot N vs Snapshot N-1) ---")
    if len(rows) >= 2:
        snap_n = rows[0]
        snap_n_minus_1 = rows[1]
        
        genome_n = json.loads(snap_n[2]) if snap_n[2] else {}
        genome_n_1 = json.loads(snap_n_minus_1[2]) if snap_n_minus_1[2] else {}
        
        dance_n = normalize_feature(genome_n.get("danceability"))
        dance_n_1 = normalize_feature(genome_n_1.get("danceability"))
        dance_delta = dance_n - dance_n_1
        
        aco_n = normalize_feature(genome_n.get("acousticness"))
        aco_n_1 = normalize_feature(genome_n_1.get("acousticness"))
        aco_delta = aco_n - aco_n_1
        
        print(f"Snapshot N (Latest):")
        print(f"  Danceability: {dance_n}% (raw: {genome_n.get('danceability')})")
        print(f"  Acousticness: {aco_n}% (raw: {genome_n.get('acousticness')})")
        
        print(f"Snapshot N-1 (Previous):")
        print(f"  Danceability: {dance_n_1}% (raw: {genome_n_1.get('danceability')})")
        print(f"  Acousticness: {aco_n_1}% (raw: {genome_n_1.get('acousticness')})")
        
        print(f"Deltas (N - (N-1)):")
        print(f"  Danceability Delta: {dance_delta:+}%")
        print(f"  Acousticness Delta: {aco_delta:+}%")
        
        # Calculate archetype transitions
        transitions = []
        for i in range(len(rows) - 1):
            if rows[i][1] != rows[i+1][1]:
                transitions.append((rows[i+1][1], rows[i][1], rows[i][3]))
                
        print(f"\nArchetype Transitions (Total: {len(transitions)}):")
        for t in transitions:
            print(f"  From '{t[0]}' to '{t[1]}' at {t[2]}")
            
finally:
    db.close()
