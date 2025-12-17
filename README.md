# Financial Solvency Truth Engine

> **A0-A9 Complete** — The First Domain of the Global Truth Engine

An institutional-grade backend system for deterministic truth verification of financial solvency claims. This system provides auditable, reproducible solvency determinations with complete provenance tracking.

---

## Table of Contents

1. [Overview](#overview)
2. [Architectural Guarantees](#architectural-guarantees)
3. [System Architecture](#system-architecture)
4. [Requirements](#requirements)
5. [Installation](#installation)
6. [Quick Start](#quick-start)
7. [API Reference](#api-reference)
8. [Service Details](#service-details)
9. [Data Models](#data-models)
10. [Outputs](#outputs)
11. [Configuration](#configuration)
12. [Development](#development)
13. [Testing](#testing)
14. [Project Structure](#project-structure)

---

## Overview

The Financial Solvency Truth Engine evaluates claims about entity solvency (e.g., "Is Company X solvent over the next 12 months?") using:

- **Evidence Collection**: Financial statements, regulatory filings, market data
- **Fact Extraction**: Structured extraction of financial metrics from documents
- **Deterministic Reasoning**: Pure-function evaluation with probability intervals
- **Audit Trail**: Complete provenance with tamper-evident hash chains
- **Report Generation**: Byte-for-byte reproducible HTML/PDF reports

### What It Does

Given a solvency claim like:

```json
{
  "entity_id": "US0378331005",
  "entity_id_type": "ISIN",
  "scenario_name": "going_concern",
  "jurisdiction": "US",
  "horizon_months": 12,
  "as_of_date": "2024-01-15"
}
```

The system:
1. **Registers** the claim with a canonical ID
2. **Collects** evidence (10-K filings, financial statements, etc.)
3. **Extracts** structured facts (revenue, liabilities, cash flow)
4. **Evaluates** solvency using deterministic reasoning rules
5. **Produces** a probability interval: P(solvent) ∈ [p_low, p_high]
6. **Generates** an auditable report with full provenance
7. **Versions** the truth determination for historical tracking

---

## Architectural Guarantees

### Determinism
All operations are deterministic. Given the same inputs, the system produces identical outputs:
- Same evidence → Same extracted facts
- Same facts → Same probability interval
- Same truth version → Same report (byte-for-byte)

### Auditability
Every action is traced with:
- Immutable audit entries with SHA-256 hash chains
- Complete before/after state capture
- Correlation IDs across all services
- Replay capability for any evaluation

### Refusal-First Behavior
The system explicitly refuses to proceed when preconditions are not met:
- Missing required evidence → `REFUSED` with specific missing items
- Insufficient fact coverage → `REFUSED` with explanation
- Policy violations → `REFUSED` with policy reference

### Reproducibility
Any truth determination can be replayed:
```bash
POST /v1/trace/replay
{
  "evaluation_id": "eval_01HXY...",
  "expected_trace_hash": "sha256:abc...",
  "expected_result_hash": "sha256:def..."
}
```

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              API Gateway (A1)                                │
│                          FastAPI - Port 8000                                 │
│              Entry point, validation, routing, authentication               │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Truth Orchestrator (A2)                              │
│                      Workflow Coordination - Port 8001                       │
│              Deterministic execution, saga patterns, retries                │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
            ┌─────────────────────────┼─────────────────────────┐
            │                         │                         │
            ▼                         ▼                         ▼
┌─────────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐
│   Claim Service     │   │  Evidence Service   │   │ Extraction Service  │
│   (A3) Port 8002    │   │   (A4) Port 8003    │   │   (A5) Port 8004    │
│                     │   │                     │   │                     │
│ • Claim lifecycle   │   │ • Document storage  │   │ • PDF/XBRL parsing  │
│ • Canonical IDs     │   │ • Metadata index    │   │ • Fact extraction   │
│ • Status tracking   │   │ • Provenance        │   │ • Confidence scores │
└─────────────────────┘   └─────────────────────┘   └─────────────────────┘
            │                         │                         │
            └─────────────────────────┼─────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Reasoning Engine (A6)                                │
│                      Pure Functions - No Side Effects                        │
│                                                                              │
│  • Solvency evaluation with probability intervals                           │
│  • Fragility analysis and sensitivity scoring                               │
│  • Risk identification and categorization                                   │
│  • Policy enforcement and refusal logic                                     │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
            ┌─────────────────────────┼─────────────────────────┐
            │                         │                         │
            ▼                         ▼                         ▼
┌─────────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐
│ Trace & Audit Svc   │   │Truth Versioning Svc │   │   Report Service    │
│   (A7) Port 8005    │   │   (A8) Port 8006    │   │   (A9) Port 8007    │
│                     │   │                     │   │                     │
│ • Hash chains       │   │ • Version history   │   │ • Jinja2 HTML       │
│ • Replay support    │   │ • Current truth     │   │ • WeasyPrint PDF    │
│ • Tamper detection  │   │ • Promotion rules   │   │ • Deterministic     │
└─────────────────────┘   └─────────────────────┘   └─────────────────────┘
```

### Service Summary

| Service | Port | Phase | Description |
|---------|------|-------|-------------|
| API Gateway | 8000 | A1 | REST API entry point, request validation |
| Truth Orchestrator | 8001 | A2 | Workflow coordination, saga patterns |
| Claim Service | 8002 | A3 | Claim registration and lifecycle |
| Evidence Service | 8003 | A4 | Evidence collection and storage |
| Extraction Service | 8004 | A5 | Fact extraction from documents |
| Reasoning Engine | — | A6 | Pure functions (library, not a service) |
| Trace & Audit Service | 8005 | A7 | Immutable audit logging |
| Truth Versioning Service | 8006 | A8 | Truth state management |
| Report Service | 8007 | A9 | Report generation |

---

## Requirements

### System Requirements

- **Python**: 3.11 or higher (developed with 3.14)
- **Docker**: 20.10+ with Docker Compose v2
- **Memory**: 4GB minimum, 8GB recommended
- **Disk**: 10GB for containers and data

### Python Dependencies

Core dependencies (from `pyproject.toml`):

```
fastapi>=0.104.0          # Web framework
uvicorn[standard]>=0.24.0 # ASGI server
pydantic>=2.5.0           # Data validation
pydantic-settings>=2.1.0  # Configuration
sqlalchemy>=2.0.23        # ORM (async)
asyncpg>=0.29.0           # PostgreSQL driver
alembic>=1.13.0           # Database migrations
structlog>=23.2.0         # Structured logging
python-ulid>=2.2.0        # Canonical IDs
boto3>=1.34.0             # S3-compatible storage
httpx>=0.25.0             # HTTP client
tenacity>=8.2.0           # Retry logic
jinja2>=3.1.0             # HTML templating
```

Optional dependencies:

```
weasyprint>=62.3          # PDF generation (optional)
```

### Infrastructure

| Component | Purpose | Docker Image |
|-----------|---------|--------------|
| PostgreSQL 15 | Primary database | `postgres:15-alpine` |
| MinIO | S3-compatible object storage | `minio/minio:latest` |

---

## Installation

### Option 1: Docker (Recommended)

```bash
# Clone the repository
git clone https://github.com/your-org/truth-engine.git
cd truth-engine

# Start all services
docker-compose up -d

# Verify health
curl http://localhost:8000/health
```

### Option 2: Local Development

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install package with dev dependencies
pip install -e ".[dev]"

# Start infrastructure only
docker-compose up -d postgres minio minio-init

# Set environment variables
export DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/truth_engine"
export S3_ENDPOINT_URL="http://localhost:9000"
export S3_ACCESS_KEY="minioadmin"
export S3_SECRET_KEY="minioadmin"

# Run API Gateway
cd src && uvicorn services.api_gateway.app:app --reload --port 8000
```

### Option 3: Install WeasyPrint for PDF Support

```bash
# macOS
brew install pango libffi
pip install weasyprint

# Ubuntu/Debian
apt-get install libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0
pip install weasyprint

# Verify installation
python -c "import weasyprint; print('PDF support enabled')"
```

---

## Quick Start

### 1. Start the System

```bash
docker-compose up -d
```

### 2. Create a Solvency Claim

```bash
curl -X POST http://localhost:8000/v1/claims \
  -H "Content-Type: application/json" \
  -d '{
    "entity_id": "US0378331005",
    "entity_id_type": "ISIN",
    "scenario_name": "going_concern",
    "jurisdiction": "US",
    "horizon_months": 12,
    "as_of_date": "2024-01-15"
  }'
```

Response:
```json
{
  "success": true,
  "data": {
    "claim_id": "clm_01HXY2ABC123...",
    "claim_class_key": "going_concern:US0378331005:ISIN:US:12:2024-01",
    "status": "pending",
    "canonical_claim_summary": "going_concern solvency of ISIN:US0378331005 in US jurisdiction over 12-month horizon as of 2024-01"
  }
}
```

### 3. Check Health

```bash
# All services
for port in 8000 8001 8002 8003 8004 8005 8006 8007; do
  echo "Port $port: $(curl -s http://localhost:$port/health | jq -r .status)"
done
```

---

## API Reference

### API Gateway Endpoints (Port 8000)

#### Claims

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/v1/claims` | Create a new solvency claim |
| `GET` | `/v1/claims/{claim_id}` | Get claim by ID |
| `GET` | `/v1/claims` | List claims (paginated) |
| `GET` | `/v1/claims/{claim_id}/status` | Get claim status |
| `POST` | `/v1/claims/{claim_id}/evaluate` | Trigger evaluation |

#### Evidence

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/v1/claims/{claim_id}/evidence` | List evidence for claim |
| `POST` | `/v1/evidence` | Submit new evidence |

#### Reports

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/v1/reports` | Generate a report |
| `GET` | `/v1/reports/{report_id}` | Get report metadata |

#### Truth

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/v1/truth/{claim_class_key}/current` | Get current truth version |
| `GET` | `/v1/truth/{claim_class_key}/history` | Get truth version history |

### Report Service Endpoints (Port 8007)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/v1/reports/generate` | Generate report for truth version |
| `GET` | `/v1/reports/{report_id}` | Get report metadata |
| `GET` | `/v1/reports/{report_id}/html` | Download HTML artifact |
| `GET` | `/v1/reports/{report_id}/pdf` | Download PDF artifact |
| `GET` | `/v1/reports/by-truth/{truth_version_id}` | List reports for truth version |
| `GET` | `/v1/reports/version` | Get service version info |

### Truth Versioning Endpoints (Port 8006)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/v1/truth-versions` | Create new truth version |
| `GET` | `/v1/truth-versions/{id}` | Get truth version by ID |
| `GET` | `/v1/truth-versions/current/{claim_class_key}` | Get current truth |
| `GET` | `/v1/truth-versions/history/{claim_class_key}` | Get version history |
| `POST` | `/v1/truth-versions/{id}/promote` | Promote to current |

### Trace & Audit Endpoints (Port 8005)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/v1/traces` | Record a trace entry |
| `GET` | `/v1/traces/{trace_id}` | Get trace by ID |
| `POST` | `/v1/traces/replay` | Replay an evaluation |
| `GET` | `/v1/audit/{entity_id}` | Get audit entries for entity |

### Documentation

Interactive API documentation available at:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

---

## Service Details

### A1: API Gateway

The central entry point for all external requests.

**Responsibilities:**
- Request validation with Pydantic
- Rate limiting and authentication context
- Request routing to downstream services
- Error standardization

**Key Schemas:**
```python
CreateClaimRequest(
    entity_id: str,           # e.g., "US0378331005"
    entity_id_type: str,      # ISIN, LEI, DUNS, etc.
    scenario_name: str,       # going_concern, liquidity, etc.
    jurisdiction: str,        # US, EU, UK, etc.
    horizon_months: int,      # 6, 12, 24, 36
    as_of_date: date          # Reference date
)
```

### A3: Claim Service

Manages the lifecycle of solvency claims.

**Claim States:**
- `pending` → Initial state
- `processing` → Evaluation in progress
- `evaluated` → Determination complete
- `refused` → Cannot evaluate (missing data)
- `superseded` → Replaced by newer version

**Canonical ID Format:**
```
clm_01HXY2ABC123DEF456GHI789JKL0
    ├── Entity type prefix
    └── ULID (time-sortable, unique)
```

### A4: Evidence Service

Collects and stores evidence documents.

**Supported Evidence Types:**
- `10-K` / `10-Q` — SEC annual/quarterly filings
- `Financial_Statement` — Balance sheet, income statement
- `Regulatory_Filing` — Other regulatory documents
- `Market_Data` — Stock prices, credit ratings

**Storage:**
- Metadata in PostgreSQL
- Documents in MinIO (S3-compatible)
- Content-addressed by SHA-256 hash

### A5: Extraction Service

Extracts structured facts from evidence documents.

**Fact Types:**
- `total_revenue`, `net_income`, `total_assets`
- `total_liabilities`, `cash_and_equivalents`
- `current_ratio`, `debt_to_equity`
- `operating_cash_flow`, `working_capital`

**Fact Schema:**
```python
ExtractedFact(
    fact_id: str,
    fact_type: str,
    value: Decimal,
    unit: str,              # USD, EUR, ratio
    currency: str | None,
    as_of_date: date,
    period_end: date | None,
    confidence: Decimal,    # 0.0 - 1.0
    extraction_method: str, # llm, regex, xbrl
    evidence_id: str        # Source evidence
)
```

### A6: Reasoning Engine

**Pure functions only — no side effects.**

**Evaluation Output:**
```python
EvaluationResult(
    conclusion: str,           # "solvent", "insolvent", "refused"
    probability_interval: ProbabilityInterval(
        p_low: Decimal,        # Lower bound
        p_mid: Decimal,        # Best estimate
        p_high: Decimal        # Upper bound
    ),
    fragility_score: Decimal,  # 0.0 - 1.0 (stability)
    top_sensitivity_driver: str,
    key_risks: list[KeyRisk],
    trace_hash: str,           # Reproducibility hash
    result_hash: str
)
```

**Refusal Codes:**
- `MISSING_EVIDENCE` — Required documents not found
- `INSUFFICIENT_FACTS` — Cannot extract needed metrics
- `CONFLICTING_DATA` — Irreconcilable evidence conflict
- `POLICY_VIOLATION` — Evaluation blocked by policy

### A7: Trace & Audit Service

Provides tamper-evident audit logging.

**Hash Chain:**
```
Entry[n].hash = SHA256(
    Entry[n].data +
    Entry[n-1].hash
)
```

**Audit Entry:**
```python
AuditEntry(
    audit_id: str,
    entity_type: str,
    entity_id: str,
    action: str,              # CREATE, UPDATE, DELETE
    before_state: dict | None,
    after_state: dict | None,
    actor_id: str,
    timestamp: datetime,
    previous_hash: str,
    entry_hash: str
)
```

### A8: Truth Versioning Service

Manages the version history of truth determinations.

**Truth Version:**
```python
TruthVersion(
    truth_version_id: str,
    claim_class_key: str,
    evaluation_id: str,
    version_number: int,
    is_current: bool,
    conclusion: str,
    probability_interval: ProbabilityInterval,
    facts_snapshot_hash: str,
    evidence_set_hash: str,
    policy_hash: str,
    trace_hash: str,
    result_hash: str,
    created_at: datetime
)
```

**Promotion Rules:**
- Only verified evaluations can be promoted
- Previous current version is marked `is_current=False`
- All promotions are audited

### A9: Report Service

Generates deterministic, reproducible reports.

**Determinism Guarantees:**
- Fixed numeric precision (4 decimal places for probabilities)
- Sorted lists (evidence by ID, facts by ID, risks by type)
- Canonical timestamp format (ISO 8601 UTC)
- UTF-8 encoding with normalized line endings

**Report Sections:**
1. Claim Summary
2. Evaluation Metadata
3. Policy Configuration
4. Conclusion (Solvent/Insolvent/Refused)
5. Probability Interval
6. Risk Analysis & Fragility
7. Intermediate Metrics
8. Integrity & Reproducibility (hashes)
9. Appendix A: Evidence Provenance
10. Appendix B: Fact Provenance

---

## Data Models

### Core Entities

```
┌─────────────┐       ┌──────────────┐       ┌─────────────────┐
│    Claim    │──────▶│   Evidence   │──────▶│ Extracted Facts │
└─────────────┘  1:N  └──────────────┘  1:N  └─────────────────┘
       │                                              │
       │                                              │
       ▼                                              ▼
┌─────────────┐       ┌──────────────┐       ┌─────────────────┐
│ Evaluation  │◀──────│   Trace      │◀──────│   Reasoning     │
└─────────────┘       └──────────────┘       └─────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│                     Truth Version                            │
│  (Immutable snapshot of evaluation at point in time)        │
└─────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│                         Report                               │
│  (Deterministic HTML/PDF with full provenance)              │
└─────────────────────────────────────────────────────────────┘
```

### Database Tables (PostgreSQL)

| Table | Description |
|-------|-------------|
| `claims` | Solvency claim definitions |
| `evidence` | Evidence document metadata |
| `extracted_facts` | Facts extracted from evidence |
| `evaluations` | Evaluation records |
| `truth_versions` | Truth version history |
| `audit_entries` | Immutable audit log |
| `traces` | Execution traces |
| `reports` | Report metadata |

---

## Outputs

### 1. Evaluation Result

```json
{
  "evaluation_id": "eval_01HXY...",
  "claim_id": "clm_01HXY...",
  "conclusion": "solvent",
  "probability_interval": {
    "p_low": "0.7234",
    "p_mid": "0.8456",
    "p_high": "0.9123"
  },
  "fragility_score": "0.2341",
  "top_sensitivity_driver": "cash_and_equivalents",
  "key_risks": [
    {
      "risk_type": "liquidity_risk",
      "description": "Cash reserves below 3-month operating expenses",
      "severity": "medium"
    }
  ],
  "trace_hash": "sha256:abc123...",
  "result_hash": "sha256:def456..."
}
```

### 2. Truth Version

```json
{
  "truth_version_id": "tv_01HXY...",
  "claim_class_key": "going_concern:US0378331005:ISIN:US:12:2024-01",
  "version_number": 3,
  "is_current": true,
  "conclusion": "solvent",
  "probability_interval": {
    "p_low": "0.7234",
    "p_mid": "0.8456",
    "p_high": "0.9123"
  },
  "facts_snapshot_hash": "sha256:...",
  "evidence_set_hash": "sha256:...",
  "policy_hash": "sha256:...",
  "created_at": "2024-01-15T10:30:00Z"
}
```

### 3. HTML Report

Deterministic HTML document containing:
- Full claim details and evaluation metadata
- Probability interval with visual representation
- Risk analysis and fragility interpretation
- Complete evidence and fact provenance
- Integrity hashes for verification
- Replay instructions

### 4. PDF Report (Optional)

WeasyPrint-generated PDF from HTML. Note: PDF is not byte-for-byte deterministic due to font rendering. The **HTML hash is authoritative**.

---

## Configuration

### Environment Variables

```bash
# Database
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20

# Object Storage (S3-compatible)
S3_ENDPOINT_URL=http://minio:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_BUCKET_EVIDENCE=evidence
S3_BUCKET_REPORTS=reports

# Service URLs (for inter-service communication)
CLAIM_SERVICE_URL=http://claim-service:8002
EVIDENCE_SERVICE_URL=http://evidence-service:8003
EXTRACTION_SERVICE_URL=http://extraction-service:8004
TRACE_SERVICE_URL=http://trace-service:8005
TRUTH_VERSION_SERVICE_URL=http://truth-version-service:8006
REPORT_SERVICE_URL=http://report-service:8007

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json

# Optional
WEASYPRINT_AVAILABLE=true  # Set to false to disable PDF
```

### Docker Compose Services

```yaml
services:
  api-gateway:
    ports: ["8000:8000"]
  truth-orchestrator:
    ports: ["8001:8001"]
  claim-service:
    ports: ["8002:8002"]
  evidence-service:
    ports: ["8003:8003"]
  extraction-service:
    ports: ["8004:8004"]
  trace-audit-service:
    ports: ["8005:8005"]
  truth-versioning-service:
    ports: ["8006:8006"]
  report-service:
    ports: ["8007:8007"]
  postgres:
    ports: ["5432:5432"]
  minio:
    ports: ["9000:9000", "9001:9001"]
```

---

## Development

### Code Style

- **Type Hints**: All functions must have complete type annotations
- **Immutable Data**: Use `frozen=True` Pydantic models
- **Pure Functions**: Reasoning Engine has no side effects
- **Extension Points**: Mark with `# EXTENSION_POINT:` comments

### Running Locally

```bash
# Activate virtual environment
source .venv/bin/activate

# Start infrastructure
docker-compose up -d postgres minio minio-init

# Run individual service
cd src && uvicorn services.api_gateway.app:app --reload --port 8000

# Run with auto-reload
uvicorn services.report_service.app:app --reload --port 8007
```

### Adding a New Service

1. Create directory in `src/services/your_service/`
2. Add `__init__.py`, `app.py`, `schemas.py`, `routes.py`
3. Implement health check at `/health`
4. Add to `docker-compose.yml`
5. Create tests in `tests/test_your_service.py`

---

## Testing

### Run All Tests

```bash
# Full test suite (427 tests)
pytest tests/ -v

# With coverage report
pytest tests/ --cov=src --cov-report=term-missing

# Specific service
pytest tests/test_report_service_a9.py -v
```

### Test Coverage

Current coverage: **71%** (427 tests passing)

| Component | Coverage |
|-----------|----------|
| Models | 100% |
| Schemas | 97-100% |
| Reasoning Engine | 77% |
| Report Generator | 84% |
| Routes | 56-75% |

### Type Checking

```bash
mypy src --ignore-missing-imports
```

### Linting

```bash
ruff check src
black src --check
```

---

## Project Structure

```
.
├── src/
│   ├── shared/                      # Shared libraries
│   │   ├── canonical_id/            # ULID-based ID generation
│   │   ├── hashing/                 # SHA-256 content hashing
│   │   ├── errors/                  # Refusal-first error types
│   │   ├── schemas/                 # Common Pydantic schemas
│   │   ├── config/                  # Environment configuration
│   │   └── logging/                 # Structured logging (structlog)
│   │
│   ├── infrastructure/              # Infrastructure abstractions
│   │   ├── postgres/                # SQLAlchemy async models
│   │   │   ├── models.py            # All ORM models
│   │   │   ├── session.py           # Session management
│   │   │   └── fact_store.py        # Fact storage operations
│   │   ├── object_store/            # S3-compatible interface
│   │   ├── graph_store/             # Graph database (future)
│   │   ├── vector_store/            # Vector similarity (future)
│   │   └── workflow/                # Workflow orchestration
│   │
│   └── services/                    # Microservices
│       ├── api_gateway/             # A1: REST API entry point
│       ├── truth_orchestrator/      # A2: Workflow coordination
│       ├── claim_service/           # A3: Claim management
│       ├── evidence_service/        # A4: Evidence handling
│       ├── extraction_service/      # A5: Fact extraction
│       ├── reasoning_engine/        # A6: Pure reasoning
│       ├── trace_audit_service/     # A7: Audit logging
│       ├── truth_versioning_service/# A8: Version management
│       └── report_service/          # A9: Report generation
│           ├── app.py               # FastAPI application
│           ├── schemas.py           # Pydantic schemas
│           ├── routes.py            # REST endpoints
│           ├── generator.py         # Report generation logic
│           ├── stores.py            # Storage layer
│           └── templates/           # Jinja2 HTML templates
│
├── tests/                           # Test suite
│   ├── conftest.py                  # Pytest fixtures
│   ├── test_api_gateway_a1.py
│   ├── test_claim_service_a3.py
│   ├── test_evidence_service_a4.py
│   ├── test_extraction_service_a5.py
│   ├── test_reasoning_engine_a6.py
│   ├── test_trace_audit_service_a7.py
│   ├── test_truth_versioning_service_a8.py
│   └── test_report_service_a9.py
│
├── scripts/
│   └── init-db.sql                  # Database initialization
│
├── docker-compose.yml               # Container orchestration
├── Dockerfile                       # Container build
├── pyproject.toml                   # Python project config
└── README.md                        # This file
```

---

## License

MIT License — See LICENSE file for details.

---

## Glossary

| Term | Definition |
|------|------------|
| **Claim** | A statement about entity solvency to be verified |
| **Claim Class Key** | Canonical identifier for claim type + entity |
| **Evidence** | Documents supporting claim evaluation |
| **Fact** | Structured data extracted from evidence |
| **Evaluation** | Single run of reasoning engine |
| **Truth Version** | Immutable snapshot of evaluation result |
| **Fragility Score** | Measure of result stability (0=robust, 1=fragile) |
| **Refusal** | Explicit decline to evaluate due to missing data |
| **Trace** | Complete execution record for replay |
| **Provenance** | Origin and lineage of data |

---

**Note**: This system is the A0-A9 foundation of the Financial Solvency Truth Engine, the first domain of the planned Global Truth Engine. The architecture is designed to extend to additional truth domains while maintaining the core guarantees of determinism, auditability, and reproducibility.
