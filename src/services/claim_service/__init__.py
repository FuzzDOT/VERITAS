"""
Claim Service
=============

Manages claims throughout their lifecycle.
Provides CRUD operations and claim state management.
"""

from services.claim_service.app import create_app
from services.claim_service.service import ClaimService

__all__ = ["create_app", "ClaimService"]
