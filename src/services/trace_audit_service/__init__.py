"""
Trace & Audit Service (A7)
===========================

Provides comprehensive trace graph building and audit logging.

Key Components:
- TraceGraph: Immutable directed graph of reasoning steps
- AuditRecord: Tamper-evident audit log entries
- AuditManifest: Daily signed manifests with hash chains
- ReplayResult: Verification of deterministic replay

All traces and audit records are:
- Immutable: Cannot be modified after creation
- Tamper-evident: Hash chains detect any modification
- Reproducible: Same inputs produce identical hashes
"""

from services.trace_audit_service.app import create_app
from services.trace_audit_service.service import TraceAuditService

# A7 schemas
from services.trace_audit_service.schemas import (
    TRACE_SERVICE_VERSION,
    TraceNodeType,
    TraceEdgeType,
    TraceNode,
    TraceEdge,
    TraceGraph,
    AuditRecord,
    AuditRecordType,
    AuditManifest,
    ReplayResult,
    ReplayStatus,
    BuildTraceRequest,
    BuildTraceResponse,
    GetTraceResponse,
    GetAuditResponse,
    GetManifestResponse,
    ReplayVerificationRequest,
    ReplayVerificationResponse,
)

# A7 canonical serialization
from services.trace_audit_service.canonical import (
    GENESIS_HASH,
    canonical_serialize,
    canonical_bytes,
    canonical_hash,
    canonical_hash_chain,
    canonical_facts_snapshot_hash,
    canonical_policy_hash,
    canonical_evidence_set_hash,
    canonical_trace_hash,
    canonical_audit_record_hash,
    canonical_manifest_hash,
    verify_hash,
    verify_chain_integrity,
)

# A7 trace builder
from services.trace_audit_service.builder import (
    build_trace_graph,
    build_refusal_trace_graph,
)

# A7 stores and services
from services.trace_audit_service.stores import (
    TraceStore,
    AuditStore,
    ManifestService,
    ReplayService,
    TraceAuditServiceV2,
)

__all__ = [
    # App
    "create_app",
    "TraceAuditService",
    # Version
    "TRACE_SERVICE_VERSION",
    # Schemas - Enums
    "TraceNodeType",
    "TraceEdgeType",
    "AuditRecordType",
    "ReplayStatus",
    # Schemas - Core
    "TraceNode",
    "TraceEdge",
    "TraceGraph",
    "AuditRecord",
    "AuditManifest",
    "ReplayResult",
    # Schemas - API
    "BuildTraceRequest",
    "BuildTraceResponse",
    "GetTraceResponse",
    "GetAuditResponse",
    "GetManifestResponse",
    "ReplayVerificationRequest",
    "ReplayVerificationResponse",
    # Canonical
    "GENESIS_HASH",
    "canonical_serialize",
    "canonical_bytes",
    "canonical_hash",
    "canonical_hash_chain",
    "canonical_facts_snapshot_hash",
    "canonical_policy_hash",
    "canonical_evidence_set_hash",
    "canonical_trace_hash",
    "canonical_audit_record_hash",
    "canonical_manifest_hash",
    "verify_hash",
    "verify_chain_integrity",
    # Builder
    "build_trace_graph",
    "build_refusal_trace_graph",
    # Stores
    "TraceStore",
    "AuditStore",
    "ManifestService",
    "ReplayService",
    "TraceAuditServiceV2",
]
