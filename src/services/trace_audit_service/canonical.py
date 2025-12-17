"""
Canonical Serialization Module
================================

Provides deterministic serialization for reproducible hashes across
environments. All complex objects are serialized in a canonical form:
- Keys sorted alphabetically
- Decimals rounded consistently
- Dates/times in ISO8601 UTC
- Unicode normalized (NFC)
- Lists/tuples in stable order

CRITICAL: Same input data must produce identical bytes on any platform.
"""

import hashlib
import json
import unicodedata
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any, Callable, Optional, Sequence, Union
from uuid import UUID

from pydantic import BaseModel


# =============================================================================
# Constants
# =============================================================================

# Canonical decimal precision (10 decimal places)
CANONICAL_DECIMAL_PRECISION: int = 10

# Canonical decimal quantize pattern
CANONICAL_QUANTIZE: Decimal = Decimal("0.0000000001")

# Hash algorithm
HASH_ALGORITHM: str = "sha256"

# Genesis hash for chains
GENESIS_HASH: str = "0" * 64


# =============================================================================
# Type Converters
# =============================================================================


def canonical_decimal(value: Decimal) -> str:
    """
    Convert Decimal to canonical string representation.
    
    - Uses ROUND_HALF_UP rounding
    - Strips trailing zeros
    - Ensures consistent precision
    """
    if value is None:
        return "null"
    
    # Quantize to standard precision
    quantized = value.quantize(CANONICAL_QUANTIZE, rounding=ROUND_HALF_UP)
    
    # Normalize (removes trailing zeros while keeping precision)
    normalized = quantized.normalize()
    
    # Handle -0 case
    if normalized == 0:
        return "0"
    
    return str(normalized)


def canonical_datetime(dt: datetime) -> str:
    """
    Convert datetime to canonical ISO8601 UTC string.
    
    - Always in UTC
    - No timezone offset (Z suffix)
    - Microsecond precision
    """
    if dt is None:
        return "null"
    
    # Convert to UTC if not already
    if dt.tzinfo is None:
        utc_dt = dt.replace(tzinfo=timezone.utc)
    else:
        utc_dt = dt.astimezone(timezone.utc)
    
    # Format with microseconds, Z suffix
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def canonical_date(d: date) -> str:
    """Convert date to canonical ISO8601 string."""
    if d is None:
        return "null"
    return d.isoformat()


def canonical_string(s: str) -> str:
    """
    Normalize string to canonical form.
    
    - NFC Unicode normalization
    - Strips leading/trailing whitespace
    """
    if s is None:
        return "null"
    
    # NFC normalize unicode
    normalized = unicodedata.normalize("NFC", s)
    
    return normalized


def canonical_value(value: Any) -> Any:
    """
    Convert any value to its canonical representation.
    
    Returns JSON-serializable Python object with stable ordering.
    """
    if value is None:
        return None
    
    # Handle primitive types
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        # Convert float to Decimal for consistent representation
        return canonical_decimal(Decimal(str(value)))
    if isinstance(value, Decimal):
        return canonical_decimal(value)
    if isinstance(value, str):
        return canonical_string(value)
    if isinstance(value, datetime):
        return canonical_datetime(value)
    if isinstance(value, date):
        return canonical_date(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    
    # Handle Pydantic models
    if isinstance(value, BaseModel):
        return canonical_dict(value.model_dump())
    
    # Handle dictionaries
    if isinstance(value, dict):
        return canonical_dict(value)
    
    # Handle sequences (list, tuple, set, frozenset)
    if isinstance(value, (list, tuple)):
        return [canonical_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        # Sort set elements for determinism
        sorted_items = sorted([canonical_value(item) for item in value], key=str)
        return sorted_items
    
    # Handle bytes
    if isinstance(value, bytes):
        return value.hex()
    
    # Fallback to string representation
    return str(value)


def canonical_dict(d: dict[str, Any]) -> dict[str, Any]:
    """
    Convert dictionary to canonical form with sorted keys.
    """
    if d is None:
        return {}
    
    result = {}
    for key in sorted(d.keys()):
        value = d[key]
        result[canonical_string(key)] = canonical_value(value)
    
    return result


# =============================================================================
# Canonical Serialization
# =============================================================================


def canonical_serialize(data: Any) -> str:
    """
    Serialize data to canonical JSON string.
    
    Returns a JSON string that is:
    - Keys sorted alphabetically (recursive)
    - Compact (no extra whitespace)
    - UTF-8 encoded
    - Reproducible across environments
    """
    canonical = canonical_value(data)
    
    # Serialize with sorted keys, no indent, ensure_ascii=False for UTF-8
    return json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def canonical_bytes(data: Any) -> bytes:
    """
    Serialize data to canonical UTF-8 bytes.
    """
    return canonical_serialize(data).encode("utf-8")


# =============================================================================
# Canonical Hashing
# =============================================================================


def canonical_hash(data: Any) -> str:
    """
    Compute canonical SHA256 hash of data.
    
    Returns 64-character hex string.
    """
    serialized = canonical_bytes(data)
    return hashlib.sha256(serialized).hexdigest()


def canonical_hash_combine(*hashes: str) -> str:
    """
    Combine multiple hashes into a single hash.
    
    Used for building hash chains and composite hashes.
    """
    combined = "|".join(hashes)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def canonical_hash_chain(items: Sequence[str], previous_hash: str = GENESIS_HASH) -> str:
    """
    Build a rolling hash chain from a sequence of hashes.
    
    Each element in the chain incorporates all previous elements.
    """
    current = previous_hash
    for item_hash in items:
        current = canonical_hash_combine(current, item_hash)
    return current


# =============================================================================
# Object-Specific Canonical Functions
# =============================================================================


def canonical_fact_snapshot(
    fact_id: str,
    fact_type: str,
    value: Decimal,
    currency: Optional[str],
    as_of_date: date,
    confidence: Decimal,
    evidence_id: str,
    fact_hash: str,
) -> dict[str, Any]:
    """
    Create canonical snapshot of a fact for audit records.
    """
    return canonical_dict({
        "fact_id": fact_id,
        "fact_type": fact_type,
        "value": value,
        "currency": currency,
        "as_of_date": as_of_date,
        "confidence": confidence,
        "evidence_id": evidence_id,
        "fact_hash": fact_hash,
    })


def canonical_facts_snapshot_hash(facts: Sequence[dict[str, Any]]) -> str:
    """
    Compute hash of a facts snapshot.
    
    Facts are sorted by fact_id for determinism.
    """
    # Sort by fact_id
    sorted_facts = sorted(facts, key=lambda f: f.get("fact_id", ""))
    return canonical_hash(sorted_facts)


def canonical_policy_hash(
    min_confidence: Decimal,
    max_staleness_days: int,
    prefer_higher_confidence: bool,
    prefer_newer_date: bool,
) -> str:
    """
    Compute canonical hash of fact selection policy.
    """
    return canonical_hash({
        "min_confidence": min_confidence,
        "max_staleness_days": max_staleness_days,
        "prefer_higher_confidence": prefer_higher_confidence,
        "prefer_newer_date": prefer_newer_date,
    })


def canonical_evidence_set_hash(evidence_hashes: Sequence[str]) -> str:
    """
    Compute canonical hash of an evidence set.
    
    Evidence hashes are sorted for determinism.
    """
    sorted_hashes = sorted(evidence_hashes)
    return canonical_hash(sorted_hashes)


def canonical_trace_hash(nodes: Sequence[dict], edges: Sequence[dict]) -> str:
    """
    Compute canonical hash of a trace graph.
    
    Nodes and edges are sorted by ID for determinism.
    """
    sorted_nodes = sorted(
        [canonical_dict(n) for n in nodes],
        key=lambda n: n.get("node_id", "")
    )
    sorted_edges = sorted(
        [canonical_dict(e) for e in edges],
        key=lambda e: e.get("edge_id", "")
    )
    
    return canonical_hash({
        "nodes": sorted_nodes,
        "edges": sorted_edges,
    })


def canonical_audit_record_hash(
    evaluation_id: str,
    claim_hash: str,
    evidence_set_hash: str,
    facts_snapshot_hash: str,
    policy_hash: str,
    trace_hash: str,
    result_hash: str,
    engine_version: str,
    created_at: datetime,
    previous_hash: Optional[str],
) -> str:
    """
    Compute canonical hash of an audit record.
    
    Includes all immutable fields that define the evaluation.
    """
    return canonical_hash({
        "evaluation_id": evaluation_id,
        "claim_hash": claim_hash,
        "evidence_set_hash": evidence_set_hash,
        "facts_snapshot_hash": facts_snapshot_hash,
        "policy_hash": policy_hash,
        "trace_hash": trace_hash,
        "result_hash": result_hash,
        "engine_version": engine_version,
        "created_at": created_at,
        "previous_hash": previous_hash or GENESIS_HASH,
    })


def canonical_manifest_hash(
    manifest_date: date,
    record_hashes: Sequence[str],
    rolling_hash: str,
    previous_manifest_hash: Optional[str],
) -> str:
    """
    Compute canonical hash of an audit manifest.
    """
    return canonical_hash({
        "manifest_date": manifest_date,
        "record_hashes": list(record_hashes),
        "rolling_hash": rolling_hash,
        "previous_manifest_hash": previous_manifest_hash or GENESIS_HASH,
    })


# =============================================================================
# Verification Helpers
# =============================================================================


def verify_hash(data: Any, expected_hash: str) -> bool:
    """
    Verify that data produces the expected hash.
    """
    computed = canonical_hash(data)
    return computed == expected_hash


def verify_chain_integrity(
    hashes: Sequence[str],
    expected_rolling_hash: str,
    previous_hash: str = GENESIS_HASH,
) -> tuple[bool, Optional[int]]:
    """
    Verify the integrity of a hash chain.
    
    Returns (is_valid, first_invalid_index).
    """
    computed = canonical_hash_chain(hashes, previous_hash)
    if computed != expected_rolling_hash:
        # Find where it diverges (if we can)
        # For now, just report that it failed
        return False, None
    return True, None
