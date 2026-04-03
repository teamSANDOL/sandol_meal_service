"""This module contains utility functions for the application."""
from .db import get_db
from .lifespan import sync_meal_types

__all__ = ["get_db", "sync_meal_types"]
