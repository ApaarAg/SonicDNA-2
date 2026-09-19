"""
app/database.py
Re-exports from app_database so that new modules can do:
    from app.database import Base, SessionLocal, get_db
"""
from app_database import Base, SessionLocal, get_db, engine, User, create_new_module_tables

__all__ = ["Base", "SessionLocal", "get_db", "engine", "User", "create_new_module_tables"]
