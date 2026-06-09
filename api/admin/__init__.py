"""
Admin module - Admin/Frontend API endpoints.

These endpoints provide FULL visibility:
- HP values (hidden from agent)
- Agility values (hidden from agent)
- SCM configuration
- Experiment management
"""

from .endpoints import router as admin_router

__all__ = ['admin_router']
