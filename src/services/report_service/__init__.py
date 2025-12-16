"""
Report Service
==============

Generates formatted reports of truth determinations.
All reports are content-addressed and versioned.
"""

from services.report_service.app import create_app
from services.report_service.service import ReportService

__all__ = ["create_app", "ReportService"]
