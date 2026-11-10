# Bedrock Managed Knowledge Base Support

## Overview
Adds an Agno vector database backend that delegates search to Amazon Bedrock Knowledge Bases for managed retrieval.

## Usage
```python
from agno.agent import Agent
from agno.vectordb.bedrock_kb import BedrockKnowledgeBase
from agno.knowledge import AgentKnowledge

kb = BedrockKnowledgeBase(knowledge_base_id="YOUR_KB_ID")
knowledge = AgentKnowledge(vector_db=kb)
agent = Agent(knowledge=knowledge, search_knowledge=True)
agent.print_response("What are our security policies?")
```

## Configuration
| Variable | Description | Default |
|---|---|---|
| KNOWLEDGE_BASE_ID | Bedrock Knowledge Base ID | None |
| AWS_REGION | AWS region for the KB | us-east-1 |
| AWS_PROFILE | AWS credentials profile | None |
| USE_AGENTIC_RETRIEVAL | Enable agentic retrieval | true |
| MAX_RESULTS | Maximum retrieval results | 5 |

## Features
- Managed search (no vector store needed)
- Agentic retrieval with query decomposition + reranking
- Automatic fallback to plain Retrieve if agentic fails
- Multi-source support (S3, Web, Confluence, SharePoint)
- Implements Agno VectorDb interface

## SDK Requirements
- boto3 >= 1.43
- agno >= 0.1

## Required IAM Permissions
```json
{
  "Effect": "Allow",
  "Action": [
    "bedrock:Retrieve",
    "bedrock:AgenticRetrieveStream"
  ],
  "Resource": "arn:aws:bedrock:<region>:<account-id>:knowledge-base/<kb-id>"
}
```

## References
- [Build a Managed Knowledge Base](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-build-managed.html)
- [Retrieve API](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-test-retrieve.html)
- [Agentic Retrieval](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-test-agentic.html)

## Direct Ingestion (CUSTOM Data Source)

When using a CUSTOM data source, you can ingest documents directly without S3 upload + sync:

```python
from agno.vectordb.bedrock_kb import BedrockKB

kb = BedrockKB(
    knowledge_base_id="YOUR_KB_ID",
    data_source_id="YOUR_CUSTOM_DS_ID",
    region_name="us-west-2",
    data_source_type="CUSTOM",
)

# Inline text
kb.upsert([{"content": "Your document content.", "id": "doc-001"}])

# S3 reference (ingest specific file without full sync)
kb.upsert([{"s3_uri": "s3://bucket/path/to/file.pdf", "id": "doc-002"}])

# Binary file (PDF, images, audio — depends on KB indexing settings)
import base64
with open("document.pdf", "rb") as f:
    encoded = base64.b64encode(f.read()).decode()
kb.upsert([{"content": encoded, "mime_type": "application/pdf", "id": "doc-003"}])
```

### Configuration

| Parameter | Description | Default |
|---|---|---|
| `data_source_type` | `"S3"` (upload + sync) or `"CUSTOM"` (direct ingestion) | `"S3"` |
| `data_source_id` | Required for both modes | Env: `BEDROCK_DATA_SOURCE_ID` |
| `data_source_bucket` | Required only for `"S3"` mode | Env: `BEDROCK_DATA_SOURCE_BUCKET` |

> **Note:** CUSTOM data source must be created on the KB beforehand via the AWS console.

**References:**
- [Ingest documents directly into a knowledge base](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-direct-ingestion.html)
- [IngestKnowledgeBaseDocuments API](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_IngestKnowledgeBaseDocuments.html)
- [Connect to a custom data source](https://docs.aws.amazon.com/bedrock/latest/userguide/custom-data-source-connector.html)

