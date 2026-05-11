# Financial Solvency Truth Engine

**An institutional grade backend system for deterministic, auditable, and reproducible verification of financial solvency claims, built as a microservice architecture across nine independently deployable services.**

The Truth Engine evaluates whether a named entity is solvent over a given time horizon, using structured evidence collected from regulatory filings, financial statements, and market data. Every evaluation is cryptographically traceable, version-controlled, and byte-for-byte reproducible on demand.

---

## Highlights

- **Deterministic evaluation**: the same inputs always produce the same probability interval, trace hash, and report bytes
- **Refusal-first design**: the system explicitly refuses to proceed rather than producing low-confidence outputs when evidence is insufficient
- **Tamper-evident audit log**: SHA-256 hash chains link every audit entry to its predecessor, making retroactive modification detectable
- **Full replay capability**: any past evaluation can be re-executed from its stored trace and verified against the original hashes
- **Nine loosely coupled services**: each independently deployable, each with its own health endpoint and database scope
- **71% test coverage** across 427 passing tests, with 100% coverage on models and schemas

---

## Table of Contents

1. [What It Does](#what-it-does)
2. [Architecture](#architecture)
3. [Service Details](#service-details)
4. [Architectural Guarantees](#architectural-guarantees)
5. [Data Models](#data-models)
6. [Outputs](#outputs)
7. [Requirements](#requirements)
8. [Installation](#installation)
9. [Quick Start](#quick-start)
10. [API Reference](#api-reference)
11. [Configuration](#configuration)
12. [Testing](#testing)
13. [Development](#development)
14. [Project Structure](#project-structure)
15. [Glossary](#glossary)

---

## What It Does

Given a solvency claim:

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

The system executes a deterministic pipeline:

1. **Registers** the claim with a time-sortable canonical ULID
2. **Collects** evidence from 10-K filings, financial statements, and regulatory documents
3. **Extracts** structured facts (revenue, liabilities, cash flow, ratios) with per-fact confidence scores
4. **Evaluates** solvency using pure-function reasoning rules with no side effects
5. **Produces** a probability interval: `P(solvent)` in `[p_low, p_mid, p_high]`
6. **Records** a tamper-evident trace with SHA-256 hash chains
7. **Versions** the truth determination so the full history of evaluations for an entity is preserved
8. **Generates** an auditable HTML and PDF report with complete evidence and fact provenance

If required evidence is missing, the system returns a structured `REFUSED` response with specific missing items rather than producing an uncertain evaluation.

---

## Architecture

The system is composed of nine services. Six handle business logic; two handle observability and versioning; one handles the entry point.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              API Gateway (A1)                                │
│                          FastAPI  ·  Port 8000                               │
│              Entry point, validation, routing, authentication                │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Truth Orchestrator (A2)                              │
│                      Workflow Coordination  ·  Port 8001                     │
│              Deterministic execution, saga patterns, retries                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
            ┌─────────────────────────┼─────────────────────────┐
            │                         │                         │
            ▼                         ▼                         ▼
┌─────────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐
│   Claim Service     │   │  Evidence Service   │   │ Extraction Service  │
│   (A3) Port 8002    │   │   (A4) Port 8003    │   │   (A5) Port 8004    │
│                     │   │                     │   │                     │
│  Claim lifecycle    │   │  Document storage   │   │  PDF/XBRL parsing   │
│  Canonical IDs      │   │  Metadata index     │   │  Fact extraction    │
│  Status tracking    │   │  Provenance         │   │  Confidence scores  │
└─────────────────────┘   └─────────────────────┘   └─────────────────────┘
            │                         │                         │
            └─────────────────────────┼─────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Reasoning Engine (A6)                                │
│                    Pure Functions  ·  No Side Effects                        │
│                                                                              │
│   Solvency evaluation with probability intervals                             │
│   Fragility analysis and sensitivity scoring                                 │
│   Risk identification and categorization                                     │
│   Policy enforcement and refusal logic                                       │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
            ┌─────────────────────────┼─────────────────────────┐
            │                         │                         │
            ▼                         ▼                         ▼
┌─────────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐
│ Trace & Audit Svc   │   │Truth Versioning Svc │   │   Report Service    │
│   (A7) Port 8005    │   │   (A8) Port 8006    │   │   (A9) Port 8007    │
│                     │   │                     │   │                     │
│  Hash chains        │   │  Version history    │   │  Jinja2 HTML        │
│  Replay support     │   │  Current truth      │   │  WeasyPrint PDF     │
│  Tamper detection   │   │  Promotion rules    │   │  Deterministic      │
└─────────────────────┘   └─────────────────────┘   └─────────────────────┘
```

### Service summary

| Service | Port | Phase | Role |
|---|---|---|---|
| API Gateway | 8000 | A1 | REST entry point, request validation |
| Truth Orchestrator | 8001 | A2 | Workflow coordination, saga patterns |
| Claim Service | 8002 | A3 | Claim registration and lifecycle |
| Evidence Service | 8003 | A4 | Document storage and metadata |
| Extraction Service | 8004 | A5 | Fact extraction from documents |
| Reasoning Engine | library | A6 | Pure evaluation functions |
| Trace and Audit Service | 8005 | A7 | Immutable audit logging |
| Truth Versioning Service | 8006 | A8 | Truth state management |
| Report Service | 8007 | A9 | HTML and PDF report generation |

The Reasoning Engine (A6) is a pure-function library rather than a service. It has no HTTP interface, no database connection, and no side effects. All other services call it as a local import.

---

## Service Details

### A1: API Gateway

The sole external entry point. All requests from clients flow through here before reaching any downstream service.

Responsibilities include request validation via Pydantic, rate limiting and authentication context injection, routing to downstream services over internal HTTP, and standardization of all error responses.

```python
CreateClaimRequest(
    entity_id: str,           # e.g., "US0378331005"
    entity_id_type: str,      # ISIN, LEI, DUNS
    scenario_name: str,       # going_concern, liquidity
    jurisdiction: str,        # US, EU, UK
    horizon_months: int,      # 6, 12, 24, 36
    as_of_date: date
)
```

### A2: Truth Orchestrator

Coordinates the end-to-end evaluation workflow using saga patterns. Each step in the pipeline is explicitly sequenced, and failures trigger compensating actions to leave the system in a consistent state. Retries are handled with exponential backoff via `tenacity`.

### A3: Claim Service

Manages the full lifecycle of solvency claims from registration through evaluation to versioning.

**Claim states:**

| State | Meaning |
|---|---|
| `pending` | Registered, awaiting evaluation |
| `processing` | Evaluation currently in progress |
| `evaluated` | Determination complete |
| `refused` | Evaluation declined due to missing or conflicting data |
| `superseded` | Replaced by a newer truth version |

Canonical claim IDs use the ULID format: time-sortable, globally unique, and lexicographically ordered by creation time.

```
clm_01HXY2ABC123DEF456GHI789JKL0
     └─── ULID (26 chars, ms precision, Crockford base32) ───┘
```

### A4: Evidence Service

Collects and stores the documents that support an evaluation.

Supported evidence types include SEC 10-K and 10-Q filings, financial statements (balance sheet, income statement, cash flow), regulatory filings, and market data including credit ratings. Document bodies are stored in MinIO (S3-compatible object storage) addressed by SHA-256 content hash. Metadata and relationships are stored in PostgreSQL.

### A5: Extraction Service

Parses evidence documents and produces structured facts with confidence scores. Extraction methods include regex pattern matching, XBRL tag parsing, and LLM-assisted extraction for unstructured PDF content.

```python
ExtractedFact(
    fact_id: str,
    fact_type: str,             # total_revenue, current_ratio, etc.
    value: Decimal,
    unit: str,                  # USD, EUR, ratio
    currency: str | None,
    as_of_date: date,
    period_end: date | None,
    confidence: Decimal,        # 0.0 to 1.0
    extraction_method: str,     # llm, regex, xbrl
    evidence_id: str
)
```

Supported fact types include `total_revenue`, `net_income`, `total_assets`, `total_liabilities`, `cash_and_equivalents`, `current_ratio`, `debt_to_equity`, `operating_cash_flow`, and `working_capital`.

### A6: Reasoning Engine

The core evaluation logic. Every function is pure: given the same inputs it returns the same outputs, and no function touches a database, network, or file system. This makes the engine trivially testable and fully reproducible.

```python
EvaluationResult(
    conclusion: str,                  # "solvent", "insolvent", "refused"
    probability_interval: ProbabilityInterval(
        p_low: Decimal,
        p_mid: Decimal,
        p_high: Decimal
    ),
    fragility_score: Decimal,         # 0.0 = robust, 1.0 = maximally fragile
    top_sensitivity_driver: str,      # which fact most changes the result
    key_risks: list[KeyRisk],
    trace_hash: str,
    result_hash: str
)
```

**Refusal codes:**

| Code | When it fires |
|---|---|
| `MISSING_EVIDENCE` | Required document types not found |
| `INSUFFICIENT_FACTS` | Cannot extract the metrics needed for evaluation |
| `CONFLICTING_DATA` | Two evidence sources produce irreconcilable values |
| `POLICY_VIOLATION` | Evaluation blocked by an active policy rule |

### A7: Trace and Audit Service

Every action in the system produces an audit entry. Entries are linked into a hash chain: each entry's hash is computed over its own data concatenated with the previous entry's hash. Any retroactive modification to an entry breaks the chain at that point and is immediately detectable.

```python
# Hash chain construction
Entry[n].hash = SHA256(Entry[n].data + Entry[n-1].hash)
```

The service also supports full replay: given an `evaluation_id` and the expected `trace_hash` and `result_hash`, it re-executes the evaluation from stored inputs and verifies that the outputs match.

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

Every evaluation that completes successfully creates a new truth version. Versions are immutable snapshots: once created they are never modified. The service tracks which version is currently authoritative for each claim class key and maintains the full history.

```python
TruthVersion(
    truth_version_id: str,
    claim_class_key: str,           # "going_concern:US0378331005:ISIN:US:12:2024-01"
    evaluation_id: str,
    version_number: int,
    is_current: bool,
    conclusion: str,
    probability_interval: ProbabilityInterval,
    facts_snapshot_hash: str,       # hash of all facts used
    evidence_set_hash: str,         # hash of all evidence IDs
    policy_hash: str,               # hash of policy config at eval time
    trace_hash: str,
    result_hash: str,
    created_at: datetime
)
```

Promotion rules: only verified evaluations can be promoted to current. When a new version is promoted, the previous current version is marked `is_current=False`. Every promotion is audited.

### A9: Report Service

Generates deterministic HTML reports and WeasyPrint PDF exports. Determinism is achieved through fixed numeric precision (four decimal places for probabilities), sorted lists (evidence by ID, facts by ID, risks by type), canonical ISO 8601 UTC timestamps, and UTF-8 encoding with normalized line endings.

Report sections:

1. Claim summary
2. Evaluation metadata
3. Policy configuration at evaluation time
4. Conclusion with plain-English interpretation
5. Probability interval visualization
6. Risk analysis and fragility score interpretation
7. Intermediate computed metrics
8. Integrity section with all hashes and replay instructions
9. Appendix A: evidence provenance
10. Appendix B: fact provenance

Note: the HTML report is the authoritative artifact for reproducibility verification. PDF output via WeasyPrint is not byte-for-byte deterministic due to font rendering differences across platforms.

---

## Architectural Guarantees

### Determinism

Given the same evidence, the system always produces the same extracted facts, the same probability interval, the same trace hash, and the same report bytes. This is enforced through pure functions in the Reasoning Engine, fixed serialization ordering in the Report Service, and content-addressed storage for evidence documents.

### Auditability

Every state change in the system produces an immutable audit entry. Entries are hash-chained so any retroactive modification is detectable. Correlation IDs propagate across all service boundaries so a single external request can be traced through every downstream call.

### Refusal-first behavior

The system prefers an explicit structured refusal over a low-confidence evaluation. If required evidence is absent, if extracted facts fall below coverage thresholds, or if data sources conflict irreconcilably, the evaluation returns `REFUSED` with machine-readable codes and human-readable explanations for each failure reason.

### Reproducibility

Any evaluation can be replayed:

```bash
POST /v1/trace/replay
{
  "evaluation_id": "eval_01HXY...",
  "expected_trace_hash": "sha256:abc...",
  "expected_result_hash": "sha256:def..."
}
```

The service re-executes the evaluation from stored inputs and returns whether the hashes match, providing a cryptographic proof that the stored result is authentic.

---

## Data Models

### Entity relationships

```
┌─────────────┐       ┌──────────────┐       ┌─────────────────┐
│    Claim    │──────▶│   Evidence   │──────▶│ Extracted Facts │
└─────────────┘  1:N  └──────────────┘  1:N  └─────────────────┘
       │                                              │
       │                                              ▼
       │                                     ┌────────────────┐
       │                                     │   Reasoning    │
       │                                     └────────────────┘
       │                                              │
       ▼                                              ▼
┌─────────────┐◀─────────────────────────────┌──────────────┐
│ Evaluation  │                              │    Trace     │
└─────────────┘                              └──────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────┐
│                      Truth Version                        │
│   Immutable snapshot of evaluation at a point in time    │
└──────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────┐
│                         Report                            │
│   Deterministic HTML/PDF with full provenance            │
└──────────────────────────────────────────────────────────┘
```

### PostgreSQL tables

| Table | Contents |
|---|---|
| `claims` | Solvency claim definitions and lifecycle state |
| `evidence` | Evidence document metadata and storage references |
| `extracted_facts` | Structured facts with confidence scores |
| `evaluations` | Evaluation records with conclusions and hashes |
| `truth_versions` | Immutable version history per claim class key |
| `audit_entries` | Tamper-evident hash-chained audit log |
| `traces` | Full execution traces for replay |
| `reports` | Report metadata and artifact storage references |

---

## Outputs

### Evaluation result

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

### Truth version

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

### Reports

The HTML report is a self-contained document including the full claim and evaluation metadata, a visual probability interval representation, risk analysis with fragility score interpretation, complete evidence and fact provenance in appendices, all integrity hashes, and step-by-step replay instructions. The PDF version is generated from the HTML via WeasyPrint and is suitable for transmission to external parties.

---

## Requirements

### System requirements

- Python 3.11 or later (developed against 3.14)
- Docker 20.10 and Docker Compose v2
- 4 GB RAM minimum, 8 GB recommended
- 10 GB disk for containers and data volumes

### Core Python dependencies

```
fastapi>=0.104.0          # Web framework
uvicorn[standard]>=0.24.0 # ASGI server
pydantic>=2.5.0           # Data validation
pydantic-settings>=2.1.0  # Settings management
sqlalchemy>=2.0.23        # Async ORM
asyncpg>=0.29.0           # PostgreSQL async driver
alembic>=1.13.0           # Database migrations
structlog>=23.2.0         # Structured JSON logging
python-ulid>=2.2.0        # Canonical ULID IDs
boto3>=1.34.0             # S3-compatible storage client
httpx>=0.25.0             # Async HTTP client
tenacity>=8.2.0           # Retry logic with backoff
jinja2>=3.1.0             # HTML report templating
weasyprint>=62.3          # PDF generation (optional)
```

### Infrastructure

| Component | Purpose | Image |
|---|---|---|
| PostgreSQL 15 | Primary relational store | `postgres:15-alpine` |
| MinIO | S3-compatible object storage for documents and reports | `minio/minio:latest` |

---

## Installation

### Docker (recommended)

```bash
git clone https://github.com/your-org/truth-engine.git
cd truth-engine

docker-compose up -d

curl http://localhost:8000/health
```

### Local development

```bash
python -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"

# Start infrastructure only
docker-compose up -d postgres minio minio-init

export DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/truth_engine"
export S3_ENDPOINT_URL="http://localhost:9000"
export S3_ACCESS_KEY="minioadmin"
export S3_SECRET_KEY="minioadmin"

cd src && uvicorn services.api_gateway.app:app --reload --port 8000
```

### PDF support

WeasyPrint requires system-level font and layout libraries.

```bash
# macOS
brew install pango libffi
pip install weasyprint

# Ubuntu/Debian
apt-get install libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0
pip install weasyprint

python -c "import weasyprint; print('PDF support enabled')"
```

---

## Quick Start

### 1. Start all services

```bash
docker-compose up -d
```

### 2. Verify all services are healthy

```bash
for port in 8000 8001 8002 8003 8004 8005 8006 8007; do
  echo "Port $port: $(curl -s http://localhost:$port/health | jq -r .status)"
done
```

### 3. Register a solvency claim

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

### 4. Trigger evaluation

```bash
curl -X POST http://localhost:8000/v1/claims/clm_01HXY2ABC123.../evaluate
```

### 5. Retrieve the current truth version

```bash
curl http://localhost:8000/v1/truth/going_concern:US0378331005:ISIN:US:12:2024-01/current
```

### 6. Generate a report

```bash
curl -X POST http://localhost:8000/v1/reports \
  -H "Content-Type: application/json" \
  -d '{"truth_version_id": "tv_01HXY..."}'
```

---

## API Reference

### API Gateway (Port 8000)

#### Claims

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/v1/claims` | Register a new solvency claim |
| `GET` | `/v1/claims/{claim_id}` | Get claim by ID |
| `GET` | `/v1/claims` | List claims with pagination |
| `GET` | `/v1/claims/{claim_id}/status` | Get current claim status |
| `POST` | `/v1/claims/{claim_id}/evaluate` | Trigger evaluation pipeline |

#### Evidence

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/v1/claims/{claim_id}/evidence` | List evidence for a claim |
| `POST` | `/v1/evidence` | Submit a new evidence document |

#### Reports

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/v1/reports` | Generate a report for a truth version |
| `GET` | `/v1/reports/{report_id}` | Get report metadata |

#### Truth

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/v1/truth/{claim_class_key}/current` | Get current truth version |
| `GET` | `/v1/truth/{claim_class_key}/history` | Get full version history |

### Report Service (Port 8007)

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/v1/reports/generate` | Generate report for a truth version |
| `GET` | `/v1/reports/{report_id}` | Get report metadata |
| `GET` | `/v1/reports/{report_id}/html` | Download HTML artifact |
| `GET` | `/v1/reports/{report_id}/pdf` | Download PDF artifact |
| `GET` | `/v1/reports/by-truth/{truth_version_id}` | List all reports for a truth version |
| `GET` | `/v1/reports/version` | Get service version info |

### Truth Versioning (Port 8006)

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/v1/truth-versions` | Create a new truth version |
| `GET` | `/v1/truth-versions/{id}` | Get truth version by ID |
| `GET` | `/v1/truth-versions/current/{claim_class_key}` | Get current authoritative version |
| `GET` | `/v1/truth-versions/history/{claim_class_key}` | Get full version history |
| `POST` | `/v1/truth-versions/{id}/promote` | Promote a version to current |

### Trace and Audit (Port 8005)

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/v1/traces` | Record a trace entry |
| `GET` | `/v1/traces/{trace_id}` | Get trace by ID |
| `POST` | `/v1/traces/replay` | Replay an evaluation and verify hashes |
| `GET` | `/v1/audit/{entity_id}` | Get all audit entries for an entity |

### Interactive documentation

| Interface | URL |
|---|---|
| Swagger UI | http://localhost:8000/docs |
| ReDoc | http://localhost:8000/redoc |

---

## Configuration

### Environment variables

```bash
# Database
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20

# Object storage
S3_ENDPOINT_URL=http://minio:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_BUCKET_EVIDENCE=evidence
S3_BUCKET_REPORTS=reports

# Internal service URLs
CLAIM_SERVICE_URL=http://claim-service:8002
EVIDENCE_SERVICE_URL=http://evidence-service:8003
EXTRACTION_SERVICE_URL=http://extraction-service:8004
TRACE_SERVICE_URL=http://trace-service:8005
TRUTH_VERSION_SERVICE_URL=http://truth-version-service:8006
REPORT_SERVICE_URL=http://report-service:8007

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json

# Features
WEASYPRINT_AVAILABLE=true
```

All service configuration is managed through `pydantic-settings`, which reads from environment variables with validation and type coercion at startup. Missing required variables cause the service to fail fast with a clear error rather than silently operating with defaults.

---

## Testing

### Run the full suite

```bash
pytest tests/ -v

pytest tests/ --cov=src --cov-report=term-missing

pytest tests/test_report_service_a9.py -v
```

### Coverage by component

| Component | Coverage |
|---|---|
| Models | 100% |
| Schemas | 97% to 100% |
| Reasoning Engine | 77% |
| Report Generator | 84% |
| Routes | 56% to 75% |

427 tests passing total.

### Type checking and linting

```bash
mypy src --ignore-missing-imports

ruff check src
black src --check
```

---

## Development

### Code conventions

All functions must have complete type annotations. Pydantic models are `frozen=True` wherever the data is not expected to change after construction. The Reasoning Engine enforces a strict no-side-effects discipline: any function that touches I/O belongs in a service, not the engine. Extension points for future domains are marked with `# EXTENSION_POINT:` comments to make them discoverable.

### Adding a new service

1. Create `src/services/your_service/` with `__init__.py`, `app.py`, `schemas.py`, and `routes.py`
2. Implement a `/health` endpoint returning `{"status": "ok"}`
3. Add the service to `docker-compose.yml` with an appropriate port
4. Register the internal URL in environment config
5. Add tests in `tests/test_your_service.py`

### Running a single service locally

```bash
source .venv/bin/activate
docker-compose up -d postgres minio minio-init

cd src && uvicorn services.report_service.app:app --reload --port 8007
```

---

## Project Structure

```
.
├── src/
│   ├── shared/                        # Libraries shared across all services
│   │   ├── canonical_id/              # ULID-based ID generation
│   │   ├── hashing/                   # SHA-256 content hashing
│   │   ├── errors/                    # Refusal-first error types
│   │   ├── schemas/                   # Common Pydantic schemas
│   │   ├── config/                    # Environment configuration
│   │   └── logging/                   # Structured logging via structlog
│   │
│   ├── infrastructure/                # Infrastructure abstractions
│   │   ├── postgres/                  # SQLAlchemy async models and sessions
│   │   │   ├── models.py              # All ORM models
│   │   │   ├── session.py             # Session lifecycle management
│   │   │   └── fact_store.py          # Fact storage operations
│   │   ├── object_store/              # S3-compatible storage interface
│   │   ├── graph_store/               # Graph database (future)
│   │   ├── vector_store/              # Vector similarity search (future)
│   │   └── workflow/                  # Saga workflow orchestration
│   │
│   └── services/                      # The nine microservices
│       ├── api_gateway/               # A1: REST entry point
│       ├── truth_orchestrator/        # A2: Workflow coordination
│       ├── claim_service/             # A3: Claim lifecycle
│       ├── evidence_service/          # A4: Document storage
│       ├── extraction_service/        # A5: Fact extraction
│       ├── reasoning_engine/          # A6: Pure evaluation logic
│       ├── trace_audit_service/       # A7: Tamper-evident audit log
│       ├── truth_versioning_service/  # A8: Version management
│       └── report_service/            # A9: Report generation
│           ├── app.py                 # FastAPI application
│           ├── schemas.py             # Pydantic schemas
│           ├── routes.py              # REST endpoints
│           ├── generator.py           # Report generation logic
│           ├── stores.py              # Storage layer
│           └── templates/             # Jinja2 HTML templates
│
├── tests/
│   ├── conftest.py
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
│   └── init-db.sql
│
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── README.md
```

---

## Design Decisions Worth Noting

**Why is the Reasoning Engine a library rather than a service?** A networked reasoning service would introduce latency, serialization overhead, and a new failure mode for the most critical part of the pipeline. Because the engine is pure functions with no I/O, there is no benefit to isolating it behind HTTP. It is easier to test, easier to reason about, and faster to call as a local import.

**Why refusal-first rather than best-effort evaluation?** Financial solvency determinations have real consequences. A low-confidence output that looks like a real result is more dangerous than a structured refusal that makes uncertainty explicit. Downstream consumers can handle a `REFUSED` response; they cannot easily detect an evaluation that silently degraded to a guess.

**Why ULID instead of UUID?** ULIDs are time-sortable, which means database index locality is preserved as records are inserted. They are also slightly shorter and more readable in logs. The time prefix makes it easy to tell at a glance whether two IDs are from the same time window without parsing timestamps separately.

**Why hash-chain audit entries rather than a simple append-only log?** An append-only table in a relational database can still be modified by anyone with the right database credentials. The hash chain makes tampering detectable without requiring write-once storage: any modification to a historical entry breaks the chain at that point, which surfaces immediately during chain verification.

**Why content-address evidence documents by SHA-256?** Content addressing means that two submissions of the same document produce the same storage key, so deduplication is automatic. It also means the evidence set hash in a truth version is a commitment to exactly which documents were used, not just their identifiers, which strengthens the reproducibility guarantee.

---

## Glossary

| Term | Definition |
|---|---|
| Claim | A statement about entity solvency to be verified |
| Claim class key | Canonical string identifying a claim type, entity, jurisdiction, and horizon |
| Evidence | A document that supports or informs claim evaluation |
| Fact | A structured numeric or categorical value extracted from evidence |
| Evaluation | A single execution of the reasoning engine against a set of facts |
| Truth version | An immutable snapshot of one evaluation result |
| Fragility score | A measure of how sensitive the result is to small changes in inputs (0 = robust, 1 = fragile) |
| Refusal | An explicit structured decline to evaluate, with machine-readable reason codes |
| Trace | The complete execution record of an evaluation, used for replay |
| Provenance | The documented origin and transformation history of a piece of data |

---

## License

MIT. See LICENSE for details.
