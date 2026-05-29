# Integrations

Specific reader, cloud storage, and vector database integrations.

## Prerequisites

1. Run Qdrant: `./cookbook/scripts/run_qdrant.sh`
2. Set `OPENAI_API_KEY` environment variable
3. For cloud: set provider-specific credentials (see each file)
4. For managed DBs: install provider packages (see each file)

## Readers

| File | Formats |
|------|---------|
| [readers/01_documents.py](./readers/01_documents.py) | PDF, DOCX, PPTX, Excel |
| [readers/02_data.py](./readers/02_data.py) | CSV, JSON |
| [readers/03_web.py](./readers/03_web.py) | Website, YouTube, ArXiv, Firecrawl |

## Cloud Storage

| File | Provider |
|------|----------|
| [cloud/01_aws.py](./cloud/01_aws.py) | S3 buckets |
| [cloud/02_azure.py](./cloud/02_azure.py) | Azure Blob Storage |
| [cloud/03_gcp.py](./cloud/03_gcp.py) | Google Cloud Storage |
| [cloud/04_sharepoint.py](./cloud/04_sharepoint.py) | SharePoint |

## Vector Databases

| File | Databases |
|------|-----------|
| [vector_dbs/01_qdrant.py](./vector_dbs/01_qdrant.py) | Qdrant (recommended for production) |
| [vector_dbs/02_local.py](./vector_dbs/02_local.py) | ChromaDB + LanceDB (local development) |
| [vector_dbs/03_managed.py](./vector_dbs/03_managed.py) | Pinecone + PgVector (managed/production) |

## Running

```bash
.venvs/demo/bin/python cookbook/07_knowledge/05_integrations/readers/01_documents.py
```

## Further Reading

- [Knowledge Overview](https://docs.agno.com/knowledge/overview)
- [Readers](https://docs.agno.com/knowledge/readers)
- [Vector Databases](https://docs.agno.com/vectordb)
