import os
import json
import uuid
from datetime import datetime, timedelta

from app_database import SessionLocal, User, GenomeSnapshot, EmailQueue
from genome_evolution import get_timeline
from email_scheduler import trigger_recalibration_reminders

def run_test():
    with SessionLocal() as db:
        # 1. Clear any existing user with this email
        email = "almoraashok@gmail.com"
        existing = db.query(User).filter(User.email == email).all()
        for u in existing:
            db.delete(u)
        db.commit()

        # 2. Create the User
        user = User(
            id=str(uuid.uuid4()),
            email=email,
            display_name="Ashok Almora",
            archetype="Sonic Explorer",
            created_at=datetime.utcnow() - timedelta(days=60)
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"[*] Created user {user.email} (ID: {user.id})")

        # 3. Create 3 Evolution Snapshots for this user
        for i in range(3):
            days_ago = 45 - (i * 15)
            snapshot = GenomeSnapshot(
                id=str(uuid.uuid4()),
                user_id=user.id,
                taken_at=datetime.utcnow() - timedelta(days=days_ago),
                genome=json.dumps({"energy": 0.5 + i*0.1, "valence": 0.6 - i*0.05}),
                archetype_name="Sonic Explorer" if i == 0 else "Midnight Drifter"
            )
            db.add(snapshot)
        db.commit()
        print(f"[*] Created 3 genome snapshots (Evolution data).")
        
        # Extract user_id as a string to use after session closes
        user_id_str = str(user.id)

    # 4. Test Evolution Section
    print("[*] Testing Evolution Timeline endpoint logic...")
    try:
        with SessionLocal() as db:
            timeline = get_timeline(user_id_str, db=db)
            print(f"    -> Successfully fetched timeline. Total snapshots: {len(timeline.snapshots)}")
            for snap in timeline.snapshots:
                print(f"       - {snap.taken_at.date()}: {snap.archetype_name} (Energy: {snap.features.get('energy')})")
    except Exception as e:
        print(f"[!] Evolution Timeline failed: {e}")

    # 5. Test Email Scheduler
    print("[*] Testing Email Scheduler (trigger_recalibration_reminders)...")
    try:
        result = trigger_recalibration_reminders(min_days_since_calibration=7, force=True, limit=5)
        print(f"    -> Scheduler returned: {result}")
        
        with SessionLocal() as db:
            emails = db.query(EmailQueue).filter(EmailQueue.user_id == user_id_str).all()
            print(f"    -> Found {len(emails)} emails queued/sent for {email}.")
            for em in emails:
                print(f"       - Subject: {em.subject.encode('utf-8', 'replace').decode('utf-8')}, Status: {em.status}, Sent at: {em.sent_at}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[!] Email Scheduler failed: {e}")

if __name__ == "__main__":
    run_test()
