# Financial Solvency Truth Engine - Copilot Instructions

## Project Overview
This is the A0 foundation of the Financial Solvency Truth Engine, the first domain of a future Global Truth Engine. It is an institutional-grade backend system built as a Python monorepo.

## Architecture Principles
- **Determinism**: All operations must be deterministic and reproducible
- **Auditability**: Every action must be traceable with complete audit trails
- **Refusal-First**: System refuses to proceed when preconditions are not met
- **Reproducibility**: Given the same inputs, the system produces identical outputs

## Project Structure
```
src/
├── shared/           # Shared libraries
│   ├── canonical_id/ # Canonical ID generation
│   ├── hashing/      # Deterministic hashing
│   ├── errors/       # Refusal and error types
│   ├── schemas/      # Common Pydantic schemas
│   ├── config/       # Configuration management
│   └── logging/      # Structured logging
├── infrastructure/   # Infrastructure abstractions
│   ├── postgres/     # Database models
│   ├── object_store/ # Object storage interface
│   ├── graph_store/  # Graph database interface
│   ├── vector_store/ # Vector store interface
│   └── workflow/     # Workflow orchestration
└── services/         # Microservices
    ├── api_gateway/
    ├── truth_orchestrator/
    ├── claim_service/
    ├── evidence_service/
    ├── extraction_service/
    ├── reasoning_engine/
    ├── trace_audit_service/
    ├── truth_versioning_service/
    └── report_service/
```

## Development Guidelines
- Use type hints for all function signatures
- All services must have health check endpoints
- Extension points must be clearly marked with `# EXTENSION_POINT:` comments
- No domain logic in A0 - only interfaces and wiring
- Reasoning Engine must be pure functions only (no side effects)

## Commands
- `docker-compose up` - Start all services
- `docker-compose up -d postgres minio` - Start infrastructure only
- Health checks available at `/health` for each service
