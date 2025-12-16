"""
Truth Versioning Service
========================

Manages versioned snapshots of truth states for claims.
Enables point-in-time queries and full history tracking.
"""

from services.truth_versioning_service.app import create_app
from services.truth_versioning_service.service import TruthVersioningService

__all__ = ["create_app", "TruthVersioningService"]
