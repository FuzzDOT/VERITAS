# Financial Solvency Truth Engine

> A0 Foundation - The First Domain of the Global Truth Engine

An institutional-grade backend system for deterministic truth verification of financial solvency claims. This is the foundational architecture (A0) designed to be extended through phases A1-A9 into a fully operational backend.

## Architectural Guarantees

### Determinism
All operations in the Truth Engine are deterministic. Given the same inputs, the system produces identical outputs. This is critical for:
- Reproducible verification results
- Audit trail reconstruction
- Regression testing of truth determinations

### Auditability
Every action in the system is traced and logged with:
- Immutable audit entries with tamper-evident hash chains
- Complete before/after state capture
- Correlation IDs for request tracing across services

### Refusal-First Behavior
The system explicitly refuses to proceed when preconditions are not met, rather than attempting to handle invalid states. This ensures:
- Clear error boundaries
- No silent failures
- Predictable system behavior

### Reproducibility
System state can be reproduced from audit logs. Every truth determination can be replayed with identical results given the same evidence and reasoning rules.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              API Gateway                                 │
│                          (FastAPI - Port 8000)                          │
└─────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          Truth Orchestrator                              │
│                    (Workflow Coordination - Port 8001)                   │
└─────────────────────────────────────────────────────────────────────────┘
                                     │
           ┌─────────────────────────┼─────────────────────────┐
           │                         │                         │
           ▼                         ▼                         ▼
┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐
│    Claim Service    │  │  Evidence Service   │  │ Extraction Service  │
│    (Port 8002)      │  │    (Port 8003)      │  │    (Port 8004)      │
└─────────────────────┘  └─────────────────────┘  └─────────────────────┘
           │                         │                         │
           └─────────────────────────┼─────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          Reasoning Engine                                │
│                     (Pure Functions - No Service)                        │
└─────────────────────────────────────────────────────────────────────────┘
                                     │
           ┌─────────────────────────┼─────────────────────────┐
           │                         │                         │
           ▼                         ▼                         ▼
┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐
│ Trace & Audit Svc   │  │Truth Versioning Svc │  │   Report Service    │
│    (Port 8005)      │  │    (Port 8006)      │  │    (Port 8007)      │
└─────────────────────┘  └─────────────────────┘  └─────────────────────┘
```

## Services

| Service | Port | Description |
|---------|------|-------------|
| API Gateway | 8000 | Central entry point, routing, authentication context |
| Truth Orchestrator | 8001 | Workflow coordination, deterministic execution |
| Claim Service | 8002 | Claim lifecycle management |
| Evidence Service | 8003 | Evidence collection and storage |
| Extraction Service | 8004 | Data extraction from documents |
| Trace & Audit Service | 8005 | Immutable audit logging |
| Truth Versioning Service | 8006 | Truth state version management |
| Report Service | 8007 | Report generation and storage |

### Reasoning Engine

The Reasoning Engine is **not a service** - it is a library of pure functions with no side effects. This design ensures:
- Complete determinism
- Easy testing and verification
- No external dependencies during reasoning

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.11+ (for local development)

### Start with Docker

```bash
# Start all services
docker-compose up

# Start infrastructure only (for local development)
docker-compose up -d postgres minio minio-init

# Check service health
curl http://localhost:8000/health
```

### Local Development

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"

# Copy environment file
cp .env.example .env

# Start infrastructure
docker-compose up -d postgres minio minio-init

# Run API Gateway locally
cd src && uvicorn services.api_gateway.app:app --reload
```

### Health Checks

All services expose health check endpoints:

```bash
# API Gateway
curl http://localhost:8000/health

# Other services
curl http://localhost:8001/health  # Truth Orchestrator
curl http://localhost:8002/health  # Claim Service
curl http://localhost:8003/health  # Evidence Service
curl http://localhost:8004/health  # Extraction Service
curl http://localhost:8005/health  # Trace & Audit
curl http://localhost:8006/health  # Truth Versioning
curl http://localhost:8007/health  # Report Service
```

## Project Structure

```
.
├── src/
│   ├── shared/                    # Shared libraries
│   │   ├── canonical_id/          # ULID-based ID generation
│   │   ├── hashing/               # Deterministic content hashing
│   │   ├── errors/                # Refusal-first error types
│   │   ├── schemas/               # Common Pydantic schemas
│   │   ├── config/                # Configuration management
│   │   └── logging/               # Structured logging
│   │
│   ├── infrastructure/            # Infrastructure abstractions
│   │   ├── postgres/              # SQLAlchemy models & sessions
│   │   ├── object_store/          # S3-compatible storage interface
│   │   ├── graph_store/           # Graph database interface
│   │   ├── vector_store/          # Vector similarity interface
│   │   └── workflow/              # Workflow orchestration
│   │
│   └── services/                  # Microservices
│       ├── api_gateway/           # Entry point service
│       ├── truth_orchestrator/    # Workflow coordination
│       ├── claim_service/         # Claim management
│       ├── evidence_service/      # Evidence handling
│       ├── extraction_service/    # Data extraction
│       ├── reasoning_engine/      # Pure reasoning functions
│       ├── trace_audit_service/   # Audit logging
│       ├── truth_versioning_service/
│       └── report_service/        # Report generation
│
├── scripts/                       # Utility scripts
├── tests/                         # Test suite (A1+)
├── docker-compose.yml             # Docker orchestration
├── Dockerfile                     # Container definition
├── pyproject.toml                 # Python project config
└── README.md                      # This file
```

## Extension Points

A0 defines interfaces and wiring without domain logic. Each subsequent phase (A1-A9) replaces placeholder implementations with real logic.

Extension points are marked with `# EXTENSION_POINT:` comments throughout the codebase.

### Phase Roadmap

| Phase | Focus |
|-------|-------|
| A0 | Architecture & Wiring (Current) |
| A1 | Database persistence, basic claim processing |
| A2 | Graph store integration, entity relationships |
| A3 | Vector store, semantic similarity |
| A4 | Financial statement extractors |
| A5 | Reasoning rules for solvency |
| A6 | Report templates and generation |
| A7 | Workflow enhancements |
| A8 | Performance optimization |
| A9 | Production hardening |

## API Documentation

When running in development mode, API documentation is available at:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Configuration

Configuration is managed through environment variables. See `.env.example` for all available options.

Key settings:
- `DB_*` - Database connection settings
- `S3_*` - Object storage settings
- `GRAPH_*` - Graph database settings (disabled in A0)
- `VECTOR_*` - Vector store settings (disabled in A0)

## Infrastructure

### PostgreSQL

The database stores all persistent entities:
- Claims and their status
- Evidence metadata
- Extraction results
- Reasoning traces
- Truth versions
- Audit entries

### MinIO (S3-Compatible)

Object storage for:
- Raw evidence documents
- Generated reports
- Large extraction outputs

### Future Infrastructure (A2+)

- **Graph Store**: For relationship mapping between claims and entities
- **Vector Store**: For semantic similarity search

## Development Guidelines

1. **Type Hints**: All functions must have complete type annotations
2. **Pure Functions**: The Reasoning Engine must remain side-effect free
3. **Extension Points**: Mark all placeholder implementations
4. **Health Checks**: Every service must have `/health` endpoint
5. **Audit Logging**: All state changes must be audited

## Testing

```bash
# Run tests (to be implemented in A1+)
pytest

# Run with coverage
pytest --cov=src

# Type checking
mypy src

# Linting
ruff check src
```

## License

MIT License - See LICENSE file for details.

---

**Note**: This is the A0 foundation. The system is designed to be extended through phases A1-A9, each adding real domain logic while maintaining the architectural guarantees established here.
