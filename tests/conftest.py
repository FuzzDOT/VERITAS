"""
Pytest configuration and fixtures for the test suite.
"""

import pytest
import sys
from pathlib import Path
from datetime import date

# Add src to path for imports
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))


@pytest.fixture
def sample_claim_content():
    """Provide sample claim content for testing."""
    return "Company ABC has a debt-to-equity ratio of 0.5"


@pytest.fixture
def sample_evidence_content():
    """Provide sample evidence content for testing."""
    return b"Total Debt: $1,000,000\nTotal Equity: $2,000,000"


@pytest.fixture
def sample_financial_data():
    """Provide sample financial data for testing."""
    return {
        "total_assets": 5000000,
        "total_liabilities": 2000000,
        "total_equity": 3000000,
        "current_assets": 1500000,
        "current_liabilities": 500000,
        "revenue": 10000000,
        "net_income": 1000000,
    }
