"""
app/models.py
Re-exports the User ORM model so that new modules can do:
    from app.models import User
"""
from app_database import User

__all__ = ["User"]
