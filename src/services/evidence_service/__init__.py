"""
Evidence Service
================

Manages evidence collection and storage for claims.
All evidence is content-addressed and immutable.
"""

from services.evidence_service.app import create_app
from services.evidence_service.service import EvidenceService

__all__ = ["create_app", "EvidenceService"]
