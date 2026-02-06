# LanceDB Cloud

This cookbook tests Agno's connection to **LanceDB Cloud** (hosted LanceDB with `db://` URI).

## Prerequisites

- A LanceDB Cloud database. Create one at [LanceDB Cloud](https://lancedb.com/) and note:
  - **URI**: e.g. `db://default-0am290` (from the cloud console)
  - **API key**: from your project settings
- Environment variables set (e.g. in `.envrc` or shell):

  ```bash
  export LANCE_DB_URI="db://your-database-id"
  export LANCE_DB_API_KEY="your-api-key"
  ```

  Alternatively the library also reads `LANCEDB_API_KEY`.

## Run

From the agno repo root with the demo venv:

```bash
.venvs/demo/bin/python cookbook/07_knowledge/vector_db/lance_db_cloud/lance_db_cloud.py
```

The script will:

1. Connect to LanceDB Cloud using `LanceDb(uri=..., api_key=...)`
2. Insert a small test document via Knowledge
3. Run a vector search and print results
4. Delete the test document

## URI format

- **LanceDB Cloud**: `db://<database-id>` (e.g. `db://default-0am290`). The database id is shown in the LanceDB Cloud console.
- **Local**: use a path like `tmp/lancedb` instead of `db://...`.
