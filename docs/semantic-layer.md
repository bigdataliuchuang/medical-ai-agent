# Semantic Layer

`medical-ai-agent` now provides a platform-style Semantic Layer backend. The UI lives in `medical-platform` under the `语义层` menu.

## Backend Scope

The Semantic Layer owns:

- Semantic metadata catalogs for datasets, metrics, dimensions, and policies.
- A controlled query DSL so callers do not submit raw SQL.
- Tenant and role policy checks.
- Sensitive dimension protection.
- DSL-to-SQL compilation.
- Query execution through the existing agent executor.
- In-memory audit events for compile and query actions.

## Metadata

Semantic metadata lives under `metadata/semantic/`:

| File | Purpose |
|------|---------|
| `datasets.yaml` | Physical serving tables, time fields, and available fields |
| `dimensions.yaml` | Unified dimensions, field mappings, hierarchy, and sensitivity |
| `metrics.yaml` | Metric formulas, versions, status, owner, approval, and lineage |
| `policies.yaml` | Tenant and role access to metrics and dimensions |

## DSL Example

```json
{
  "tenant_id": "hospital-a",
  "role": "analyst",
  "metrics": ["antitumor_drug_amount"],
  "dimensions": ["dept_name", "drug_name"],
  "filters": [
    {
      "field": "stat_date",
      "op": "between",
      "value": ["2026-01-01", "2026-01-31"]
    }
  ],
  "limit": 100
}
```

Compiled SQL:

```sql
SELECT
  dept_name,
  drug_name,
  SUM(drug_amount) AS antitumor_drug_amount
FROM dws.dws_tumor_drug_usage_1d
WHERE drug_category = 'ANTITUMOR'
  AND stat_date BETWEEN '2026-01-01' AND '2026-01-31'
GROUP BY dept_name, drug_name
LIMIT 100
```

## API

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/semantic/metrics` | List semantic metrics |
| `GET` | `/api/v1/semantic/dimensions` | List semantic dimensions |
| `GET` | `/api/v1/semantic/datasets` | List semantic datasets |
| `POST` | `/api/v1/semantic/compile` | Compile DSL to SQL without execution |
| `POST` | `/api/v1/semantic/query` | Compile and execute DSL |
| `GET` | `/api/v1/semantic/audit/events` | List in-memory audit events |

The same routes are registered on both the production app (`src/ai_data_agent/api/app.py`) and the legacy compatibility app (`main.py`) so `medical-platform` can call the AI Agent through its existing `/agent-api` proxy.

## Frontend

The `medical-platform` frontend adds:

- `frontend/src/api/semantic.ts`
- `frontend/src/pages/SemanticLayer/index.tsx`
- A sidebar route at `/semantic-layer`

The page includes catalog tabs, a DSL query builder, SQL preview, query results, and audit event display.

## Current Gaps

- Audit events are in memory only.
- Approval and publication workflows are metadata fields, not interactive workflows yet.
- Cross-dataset joins are intentionally rejected until join-path compilation is added.
- BI API hardening and stable query result contracts need a later pass.
