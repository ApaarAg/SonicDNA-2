from app_database import engine, Base
from sqlalchemy import text

if __name__ == "__main__":
    print("Dropping all tables with CASCADE...")
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE;"))
        conn.execute(text("CREATE SCHEMA public;"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO postgres;"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO public;"))
        
    print("Creating all tables with new constraints...")
    Base.metadata.create_all(engine)
    print("Database cleared and schema updated.")
