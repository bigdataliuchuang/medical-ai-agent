# Semantic Layer Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a platform-style Semantic Layer backend in `medical-ai-agent` and a management/query UI in `medical-platform`.

**Architecture:** The backend owns semantic metadata, DSL validation, policy enforcement, SQL compilation, optional query execution, and audit events. The frontend consumes stable `/api/v1/semantic/*` endpoints and provides catalog browsing plus a query builder.

**Tech Stack:** FastAPI, Pydantic, YAML metadata, existing Doris/DuckDB executors, React 19, Ant Design 6, Axios, Vite.

---

## Task 1: Backend Semantic Metadata And Compiler

**Files:**
- Create: `metadata/semantic/datasets.yaml`
- Create: `metadata/semantic/dimensions.yaml`
- Create: `metadata/semantic/metrics.yaml`
- Create: `metadata/semantic/policies.yaml`
- Create: `src/ai_data_agent/semantic_service/catalog.py`
- Create: `src/ai_data_agent/semantic_service/dsl.py`
- Create: `src/ai_data_agent/semantic_service/policy.py`
- Create: `src/ai_data_agent/semantic_service/compiler.py`
- Test: `tests/test_semantic_service.py`

- [ ] Write failing tests for loading catalog, policy denial, sensitive dimension denial, and DSL-to-SQL compilation.
- [ ] Run `pytest tests/test_semantic_service.py -q` and confirm imports fail because the module does not exist.
- [ ] Add semantic metadata YAML fixtures under `metadata/semantic`.
- [ ] Implement catalog, DSL models, policy engine, and compiler.
- [ ] Run `pytest tests/test_semantic_service.py -q` and confirm passing.

## Task 2: Backend API And Service

**Files:**
- Create: `src/ai_data_agent/semantic_service/audit.py`
- Create: `src/ai_data_agent/semantic_service/service.py`
- Create: `src/ai_data_agent/semantic_service/api.py`
- Modify: `src/ai_data_agent/api/app.py`
- Test: `tests/test_semantic_api.py`

- [ ] Write failing API tests for list metrics, list dimensions, compile query, execute query, and audit event listing.
- [ ] Run `pytest tests/test_semantic_api.py -q` and confirm routes are missing.
- [ ] Implement service orchestration and in-memory audit event store.
- [ ] Register semantic routes in the production FastAPI app.
- [ ] Run semantic API tests.

## Task 3: Frontend Semantic Layer Workbench

**Files in `medical-platform`:**
- Create: `frontend/src/api/semantic.ts`
- Create: `frontend/src/pages/SemanticLayer/index.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/main.tsx`

- [ ] Add API client types for metrics, dimensions, datasets, compile, query, and audit events.
- [ ] Add a sidebar entry named `语义层`.
- [ ] Add a page with tabs for metrics, dimensions, query builder, SQL preview/results, and audit events.
- [ ] Build with `npm run build`.

## Task 4: Documentation And Verification

**Files:**
- Modify: `README.md`
- Create: `docs/semantic-layer.md`

- [ ] Document the DSL, API, policy model, and frontend route.
- [ ] Run backend semantic tests and relevant existing tests.
- [ ] Run frontend build.
- [ ] Summarize residual gaps: persistent audit storage, approval workflow UI, and BI API hardening.
