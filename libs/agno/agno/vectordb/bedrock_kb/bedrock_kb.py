"""Amazon Bedrock Knowledge Base as a vector database backend for Agno.

Uses Bedrock Managed Knowledge Bases for retrieval.
Write operations upload to the KB's S3 data source and trigger ingestion sync.
"""

import os
import uuid
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _get_source_uri(result: dict) -> str:
    """Extract source URI from a retrieval result, handling all location types."""
    location = result.get('location', {})
    loc_type = location.get('type', '')
    if loc_type == 'S3' or 's3Location' in location:
        return location.get('s3Location', {}).get('uri', '')
    elif loc_type == 'WEB' or 'webLocation' in location:
        return location.get('webLocation', {}).get('url', '')
    elif 'confluenceLocation' in location:
        return location.get('confluenceLocation', {}).get('url', '')
    elif 'salesforceLocation' in location:
        return location.get('salesforceLocation', {}).get('url', '')
    elif 'sharePointLocation' in location:
        return location.get('sharePointLocation', {}).get('url', '')
    elif 'customDocumentLocation' in location:
        return location.get('customDocumentLocation', {}).get('id', '')
    # Fallback to metadata._source_uri (for agentic results)
    return result.get('metadata', {}).get('_source_uri', '')


class BedrockKB:
    """Amazon Bedrock Knowledge Base vector database backend.

    Args:
        knowledge_base_id: The KB ID. Falls back to KNOWLEDGE_BASE_ID env var.
        data_source_id: The data source ID for ingestion. Falls back to BEDROCK_DATA_SOURCE_ID env var.
        data_source_bucket: S3 bucket for the KB's data source. Falls back to BEDROCK_DATA_SOURCE_BUCKET env var.
        region_name: AWS region. Falls back to AWS_REGION env var or us-east-1.
        number_of_results: Default number of results. Defaults to 5.
    """

    def __init__(
        self,
        knowledge_base_id: Optional[str] = None,
        data_source_id: Optional[str] = None,
        data_source_bucket: Optional[str] = None,
        region_name: Optional[str] = None,
        number_of_results: int = 5,
        use_agentic_retrieval: Optional[bool] = None,
        data_source_type: str = "S3",
    ):
        self.knowledge_base_id = knowledge_base_id or os.environ.get("KNOWLEDGE_BASE_ID", "")
        self.data_source_id = data_source_id or os.environ.get("BEDROCK_DATA_SOURCE_ID", "")
        self.data_source_bucket = data_source_bucket or os.environ.get("BEDROCK_DATA_SOURCE_BUCKET", "")
        self.region_name = region_name or os.environ.get("AWS_REGION", "us-east-1")
        self.number_of_results = number_of_results
        self.use_agentic_retrieval = use_agentic_retrieval if use_agentic_retrieval is not None else os.environ.get('USE_AGENTIC_RETRIEVAL', 'true').lower() != 'false'
        self.data_source_type = data_source_type or os.environ.get("BEDROCK_DATA_SOURCE_TYPE", "S3").upper()
        self._runtime_client = None
        self._agent_client = None
        self._s3_client = None

    @property
    def runtime_client(self):
        if self._runtime_client is None:
            import boto3
            from botocore.config import Config
            self._runtime_client = boto3.client(
                "bedrock-agent-runtime",
                region_name=self.region_name,
                config=Config(user_agent_extra="agno/bedrock-kb"),
            )
        return self._runtime_client

    @property
    def agent_client(self):
        if self._agent_client is None:
            import boto3
            from botocore.config import Config
            self._agent_client = boto3.client("bedrock-agent", region_name=self.region_name)
        return self._agent_client

    @property
    def s3_client(self):
        if self._s3_client is None:
            import boto3
            from botocore.config import Config
            self._s3_client = boto3.client("s3", region_name=self.region_name)
        return self._s3_client

    def search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """Search the knowledge base."""
        k = limit or self.number_of_results

        # Try agentic retrieval first
        if self.use_agentic_retrieval:
            try:
                response = self.runtime_client.agentic_retrieve_stream(
                    knowledgeBaseId=self.knowledge_base_id,
                    messages=[{"content": {"text": query}, "role": "user"}],
                    retrievers=[{
                        "configuration": {
                            "knowledgeBase": {
                                "knowledgeBaseId": self.knowledge_base_id,
                                "retrievalOverrides": {"maxNumberOfResults": k},
                            }
                        }
                    }],
                    agenticRetrieveConfiguration={
                        "foundationModelType": "MANAGED",
                        "rerankingModelType": "MANAGED",
                    },
                )
                results = []
                for event in response.get("stream", []):
                    if "result" in event and "results" in event["result"]:
                        for result in event["result"]["results"]:
                            content = result.get("content", {}).get("text", "")
                            source = _get_source_uri(result)
                            score = result.get("score", 0.0)
                            metadata = result.get("metadata", {})
                            metadata["source"] = source
                            results.append({
                                "id": source,
                                "content": content,
                                "metadata": metadata,
                                "score": score,
                            })
                if results:
                    return results
            except Exception:
                pass  # Fall through to plain retrieve

        retrieval_config: dict[str, Any] = {
            "managedSearchConfiguration": {"numberOfResults": k}
        }

        try:
            response = self.runtime_client.retrieve(
                knowledgeBaseId=self.knowledge_base_id,
                retrievalQuery={"text": query},
                retrievalConfiguration=retrieval_config,
            )

            results = []
            for result in response.get("retrievalResults", []):
                content = result.get("content", {}).get("text", "")
                source = _get_source_uri(result)
                score = result.get("score", 0.0)
                metadata = result.get("metadata", {})
                metadata["source"] = source

                results.append({
                    "id": source,
                    "content": content,
                    "metadata": metadata,
                    "score": score,
                })
            return results
        except Exception as e:
            logger.error(f"Error searching Bedrock KB: {e}")
            return []

    def upsert(self, documents: list[dict], **kwargs) -> list[str]:
        """Upsert documents into the knowledge base.

        Uses IngestKnowledgeBaseDocuments (CUSTOM) or S3 upload + sync (S3) based on data_source_type.
        Each document should have 'content' (str) and optionally 'id', 'metadata', 's3_uri', 'mime_type'.
        """
        if self.data_source_type == "CUSTOM":
            return self._upsert_direct(documents)
        else:
            return self._upsert_s3(documents)

    def _upsert_direct(self, documents: list[dict]) -> list[str]:
        """Upsert documents directly via IngestKnowledgeBaseDocuments API (CUSTOM data source)."""
        if not self.data_source_id:
            logger.warning("No data_source_id configured. Cannot upsert.")
            return []

        inserted_ids = []
        api_docs = []
        for doc in documents:
            doc_id = doc.get("id", str(uuid.uuid4()))
            metadata = doc.get("metadata", {})

            if "s3_uri" in doc:
                api_doc = {
                    "content": {
                        "dataSourceType": "CUSTOM",
                        "custom": {
                            "customDocumentIdentifier": {"id": doc_id},
                            "sourceType": "S3_LOCATION",
                            "s3Location": {"uri": doc["s3_uri"]},
                        },
                    },
                }
            elif "mime_type" in doc:
                api_doc = {
                    "content": {
                        "dataSourceType": "CUSTOM",
                        "custom": {
                            "customDocumentIdentifier": {"id": doc_id},
                            "sourceType": "IN_LINE",
                            "inlineContent": {
                                "type": "BYTE",
                                "byteContent": {"data": doc.get("content", ""), "mimeType": doc["mime_type"]},
                            },
                        },
                    },
                }
            else:
                api_doc = {
                    "content": {
                        "dataSourceType": "CUSTOM",
                        "custom": {
                            "customDocumentIdentifier": {"id": doc_id},
                            "sourceType": "IN_LINE",
                            "inlineContent": {
                                "type": "TEXT",
                                "textContent": {"data": doc.get("content", "")},
                            },
                        },
                    },
                }

            if metadata:
                api_doc["metadata"] = {
                    "type": "IN_LINE_ATTRIBUTE",
                    "inlineAttributes": [
                        {"key": k, "value": {"stringValue": str(v), "type": "STRING"}}
                        for k, v in metadata.items()
                    ],
                }

            api_docs.append(api_doc)
            inserted_ids.append(doc_id)

            # API allows max 10 docs per call
            if len(api_docs) >= 10:
                self._ingest_documents(api_docs)
                api_docs = []

        if api_docs:
            self._ingest_documents(api_docs)

        return inserted_ids

    def _ingest_documents(self, documents: list[dict]) -> None:
        """Call IngestKnowledgeBaseDocuments API."""
        try:
            self.agent_client.ingest_knowledge_base_documents(
                knowledgeBaseId=self.knowledge_base_id,
                dataSourceId=self.data_source_id,
                documents=documents,
            )
        except Exception as e:
            logger.error(f"Error ingesting documents directly: {e}")

    def _upsert_s3(self, documents: list[dict]) -> list[str]:
        """Upsert documents by uploading to S3 and triggering ingestion."""
        if not self.data_source_bucket:
            logger.warning(
                "No data_source_bucket configured. Set BEDROCK_DATA_SOURCE_BUCKET env var "
                "or pass data_source_bucket to constructor."
            )
            return []

        inserted_ids = []
        for doc in documents:
            doc_id = doc.get("id", str(uuid.uuid4()))
            content = doc.get("content", "")
            metadata = doc.get("metadata", {})

            key = f"agno/{doc_id}.txt"
            self.s3_client.put_object(
                Bucket=self.data_source_bucket,
                Key=key,
                Body=content,
                Metadata={k: str(v) for k, v in metadata.items()},
            )
            inserted_ids.append(doc_id)

        # Trigger ingestion sync
        if inserted_ids:
            self._start_ingestion()

        return inserted_ids

    def delete(self, ids: list[str], **kwargs) -> None:
        """Delete documents by removing from S3 and triggering re-sync."""
        if not self.data_source_bucket:
            logger.warning("No data_source_bucket configured. Cannot delete.")
            return

        for doc_id in ids:
            key = f"agno/{doc_id}.txt"
            try:
                self.s3_client.delete_object(Bucket=self.data_source_bucket, Key=key)
            except Exception as e:
                logger.error(f"Error deleting {doc_id} from S3: {e}")

        self._start_ingestion()

    def exists(self) -> bool:
        """Check if the knowledge base exists and is accessible."""
        try:
            response = self.agent_client.get_knowledge_base(
                knowledgeBaseId=self.knowledge_base_id
            )
            return response["knowledgeBase"]["status"] == "ACTIVE"
        except Exception:
            return False

    def _start_ingestion(self):
        """Trigger a data source ingestion job."""
        if not self.data_source_id:
            logger.warning(
                "No data_source_id configured. Set BEDROCK_DATA_SOURCE_ID env var. "
                "Documents uploaded to S3 but ingestion not triggered."
            )
            return
        try:
            self.agent_client.start_ingestion_job(
                knowledgeBaseId=self.knowledge_base_id,
                dataSourceId=self.data_source_id,
            )
            logger.info(f"Ingestion job started for KB {self.knowledge_base_id}")
        except Exception as e:
            logger.error(f"Error starting ingestion: {e}")
