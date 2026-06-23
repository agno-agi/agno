# Databricks Tools

Cookbook examples for `cookbook/91_tools/databricks`.

## Prerequisites

Export the Databricks credentials needed by the examples you want to run:

```bash
export DATABRICKS_HOST=***
export DATABRICKS_TOKEN=***
export DATABRICKS_SERVER_HOSTNAME=***
export DATABRICKS_HTTP_PATH=***
export DATABRICKS_CATALOG=***
export DATABRICKS_SCHEMA=***
export DATABRICKS_JOB_ID=***
export DATABRICKS_ADMIN_TOKEN=***
export DATABRICKS_ADMIN_CLIENT_ID=***
export DATABRICKS_ADMIN_CLIENT_SECRET=***
export DATABRICKS_VECTOR_SEARCH_ENDPOINT=***
export DATABRICKS_VECTOR_SEARCH_INDEX=***
```

## Files

- `jobs.py` - Read-only Databricks Jobs inspection. Run and cancel operations are not mounted unless `enable_admin_tools=True` with explicit admin credentials.
- `jobs_admin.py` - Databricks Jobs admin toolkit wiring with confirmation-gated operations.
- `sql.py` - Read-only Databricks SQL warehouse access.
- `unity_catalog.py` - Catalog, schema, table, function, and volume inspection.
- `vector_search.py` - Vector Search endpoint and index inspection. Create, sync, upsert, and delete operations are not mounted unless `enable_admin_tools=True` with explicit admin credentials.
- `workspace.py` - Workspace object inspection. Create, import, and delete operations are not mounted unless `enable_admin_tools=True` with explicit admin credentials.

## Admin enablement

Databricks toolkits that include state-changing operations follow the same policy:

- Read-only methods stay available with standard Databricks credentials.
- Mutating methods are only registered when `enable_admin_tools=True`.
- Admin-enabled toolkits require explicit admin credentials via `DATABRICKS_ADMIN_TOKEN` or `DATABRICKS_ADMIN_CLIENT_ID` and `DATABRICKS_ADMIN_CLIENT_SECRET`.
- Mutating methods remain confirmation-gated even after admin enablement.

## Run

```bash
.venvs/demo/bin/python cookbook/91_tools/databricks/<file>.py
```
