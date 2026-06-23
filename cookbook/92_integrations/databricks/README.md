# Databricks Integrations

Cookbook examples for `cookbook/92_integrations/databricks`.

## Prerequisites

Export the Databricks credentials needed by the examples:

```bash
export DATABRICKS_HOST=***
export DATABRICKS_TOKEN=***
export DATABRICKS_EMBEDDING_ENDPOINT=***
export DATABRICKS_VECTOR_SEARCH_ENDPOINT=***
export DATABRICKS_VECTOR_SEARCH_INDEX=***
```

## Files

- `embedder.py` - Native Databricks embedding endpoint usage.
- `vectordb.py` - Databricks Vector Search backed `DatabricksVectorDb` usage.

## Run

```bash
.venvs/demo/bin/python cookbook/92_integrations/databricks/<file>.py
```
