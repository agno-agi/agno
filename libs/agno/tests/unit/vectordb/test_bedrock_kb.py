import logging
import os
from unittest.mock import ANY, MagicMock, patch

import pytest

from agno.vectordb.bedrock_kb.bedrock_kb import BedrockKB

LOGGER_NAME = "agno.vectordb.bedrock_kb.bedrock_kb"


@pytest.fixture
def _enable_log_propagation():
    """Enable propagation on the 'agno' logger so caplog can capture records."""
    agno_logger = logging.getLogger("agno")
    original = agno_logger.propagate
    agno_logger.propagate = True
    yield
    agno_logger.propagate = original


class TestBedrockKBInit:
    """Test initialization with params and env vars."""

    def test_init_with_explicit_params(self):
        kb = BedrockKB(
            knowledge_base_id="kb-123",
            data_source_id="ds-456",
            data_source_bucket="my-bucket",
            region_name="us-west-2",
            number_of_results=10,
        )

        assert kb.knowledge_base_id == "kb-123"
        assert kb.data_source_id == "ds-456"
        assert kb.data_source_bucket == "my-bucket"
        assert kb.region_name == "us-west-2"
        assert kb.number_of_results == 10

    @patch.dict(
        "os.environ",
        {},
        clear=False,
    )
    def test_init_defaults(self):
        # Remove relevant env vars if set in the environment
        for key in ("KNOWLEDGE_BASE_ID", "BEDROCK_DATA_SOURCE_ID", "BEDROCK_DATA_SOURCE_BUCKET", "AWS_REGION"):
            os.environ.pop(key, None)

        kb = BedrockKB()

        assert kb.knowledge_base_id == ""
        assert kb.data_source_id == ""
        assert kb.data_source_bucket == ""
        assert kb.region_name == "us-east-1"
        assert kb.number_of_results == 5

    @patch.dict(
        "os.environ",
        {
            "KNOWLEDGE_BASE_ID": "env-kb-id",
            "BEDROCK_DATA_SOURCE_ID": "env-ds-id",
            "BEDROCK_DATA_SOURCE_BUCKET": "env-bucket",
            "AWS_REGION": "eu-west-1",
        },
    )
    def test_init_from_env_vars(self):
        kb = BedrockKB()

        assert kb.knowledge_base_id == "env-kb-id"
        assert kb.data_source_id == "env-ds-id"
        assert kb.data_source_bucket == "env-bucket"
        assert kb.region_name == "eu-west-1"

    @patch.dict(
        "os.environ",
        {"KNOWLEDGE_BASE_ID": "env-kb-id"},
    )
    def test_explicit_params_override_env_vars(self):
        kb = BedrockKB(knowledge_base_id="explicit-kb-id")

        assert kb.knowledge_base_id == "explicit-kb-id"

    def test_clients_are_lazy(self):
        kb = BedrockKB(knowledge_base_id="kb-123")

        assert kb._runtime_client is None
        assert kb._agent_client is None
        assert kb._s3_client is None


class TestBedrockKBSearch:
    """Test search() with managed and vector configs."""

    @pytest.fixture
    def managed_kb(self):
        kb = BedrockKB(
            knowledge_base_id="kb-managed",
            region_name="us-east-1",
        )
        kb._runtime_client = MagicMock()
        return kb

    @pytest.fixture
    def vector_kb(self):
        kb = BedrockKB(
            knowledge_base_id="kb-vector",
            region_name="us-east-1",
        )
        kb._runtime_client = MagicMock()
        return kb

    def test_search_managed_config(self, managed_kb):
        managed_kb._runtime_client.retrieve.return_value = {
            "retrievalResults": [
                {
                    "content": {"text": "Hello world"},
                    "location": {"s3Location": {"uri": "s3://bucket/doc.txt"}},
                    "score": 0.95,
                    "metadata": {"author": "test"},
                },
            ]
        }

        results = managed_kb.search("hello", limit=3)

        managed_kb._runtime_client.retrieve.assert_called_once_with(
            knowledgeBaseId="kb-managed",
            retrievalQuery={"text": "hello"},
            retrievalConfiguration={
                "managedSearchConfiguration": {"numberOfResults": 3}
            },
        )
        assert len(results) == 1
        assert results[0]["content"] == "Hello world"
        assert results[0]["id"] == "s3://bucket/doc.txt"
        assert results[0]["score"] == 0.95
        assert results[0]["metadata"]["author"] == "test"
        assert results[0]["metadata"]["source"] == "s3://bucket/doc.txt"

    def test_search_uses_default_number_of_results(self, managed_kb):
        managed_kb.number_of_results = 7
        managed_kb._runtime_client.retrieve.return_value = {"retrievalResults": []}

        managed_kb.search("test", limit=7)

        call_args = managed_kb._runtime_client.retrieve.call_args
        config = call_args.kwargs["retrievalConfiguration"]
        assert config["managedSearchConfiguration"]["numberOfResults"] == 7

    @pytest.mark.usefixtures("_enable_log_propagation")
    def test_search_handles_exception(self, managed_kb, caplog):
        managed_kb._runtime_client.retrieve.side_effect = Exception("API error")

        with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
            results = managed_kb.search("fail")

        assert results == []
        assert "Error searching Bedrock KB" in caplog.text

    def test_search_handles_missing_fields(self, managed_kb):
        managed_kb._runtime_client.retrieve.return_value = {
            "retrievalResults": [
                {
                    "content": {},
                    "location": {},
                    "metadata": {},
                },
            ]
        }

        results = managed_kb.search("sparse")

        assert len(results) == 1
        assert results[0]["content"] == ""
        assert results[0]["id"] == ""
        assert results[0]["score"] == 0.0


class TestBedrockKBUpsert:
    """Test upsert() uploads to S3 and triggers ingestion."""

    @pytest.fixture
    def kb_with_bucket(self):
        kb = BedrockKB(
            knowledge_base_id="kb-123",
            data_source_id="ds-456",
            data_source_bucket="my-bucket",
            region_name="us-east-1",
        )
        kb._s3_client = MagicMock()
        kb._agent_client = MagicMock()
        return kb

    def test_upsert_uploads_to_s3_and_triggers_ingestion(self, kb_with_bucket):
        documents = [
            {"id": "doc-1", "content": "First document", "metadata": {"tag": "test"}},
            {"id": "doc-2", "content": "Second document", "metadata": {}},
        ]

        result = kb_with_bucket.upsert(documents)

        assert result == ["doc-1", "doc-2"]
        assert kb_with_bucket._s3_client.put_object.call_count == 2

        first_call = kb_with_bucket._s3_client.put_object.call_args_list[0]
        assert first_call.kwargs["Bucket"] == "my-bucket"
        assert first_call.kwargs["Key"] == "agno/doc-1.txt"
        assert first_call.kwargs["Body"] == "First document"
        assert first_call.kwargs["Metadata"] == {"tag": "test"}

        kb_with_bucket._agent_client.start_ingestion_job.assert_called_once_with(
            knowledgeBaseId="kb-123",
            dataSourceId="ds-456",
        )

    @patch("agno.vectordb.bedrock_kb.bedrock_kb.uuid.uuid4", return_value="generated-uuid")
    def test_upsert_generates_id_when_missing(self, mock_uuid, kb_with_bucket):
        documents = [{"content": "No ID provided"}]

        result = kb_with_bucket.upsert(documents)

        assert result == ["generated-uuid"]
        call_kwargs = kb_with_bucket._s3_client.put_object.call_args.kwargs
        assert call_kwargs["Key"] == "agno/generated-uuid.txt"

    def test_upsert_empty_documents_does_not_trigger_ingestion(self, kb_with_bucket):
        result = kb_with_bucket.upsert([])

        assert result == []
        kb_with_bucket._s3_client.put_object.assert_not_called()
        kb_with_bucket._agent_client.start_ingestion_job.assert_not_called()

    @pytest.mark.usefixtures("_enable_log_propagation")
    def test_upsert_missing_bucket_returns_empty(self, caplog):
        kb = BedrockKB(
            knowledge_base_id="kb-123",
            data_source_id="ds-456",
            data_source_bucket="",
        )

        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            result = kb.upsert([{"content": "data"}])

        assert result == []
        assert "No data_source_bucket configured" in caplog.text


class TestBedrockKBDelete:
    """Test delete() removes from S3 and triggers ingestion."""

    @pytest.fixture
    def kb_with_bucket(self):
        kb = BedrockKB(
            knowledge_base_id="kb-123",
            data_source_id="ds-456",
            data_source_bucket="my-bucket",
            region_name="us-east-1",
        )
        kb._s3_client = MagicMock()
        kb._agent_client = MagicMock()
        return kb

    def test_delete_removes_objects_and_triggers_ingestion(self, kb_with_bucket):
        kb_with_bucket.delete(["doc-1", "doc-2"])

        assert kb_with_bucket._s3_client.delete_object.call_count == 2
        first_call = kb_with_bucket._s3_client.delete_object.call_args_list[0]
        assert first_call.kwargs["Bucket"] == "my-bucket"
        assert first_call.kwargs["Key"] == "agno/doc-1.txt"

        second_call = kb_with_bucket._s3_client.delete_object.call_args_list[1]
        assert second_call.kwargs["Key"] == "agno/doc-2.txt"

        kb_with_bucket._agent_client.start_ingestion_job.assert_called_once_with(
            knowledgeBaseId="kb-123",
            dataSourceId="ds-456",
        )

    @pytest.mark.usefixtures("_enable_log_propagation")
    def test_delete_handles_s3_error_gracefully(self, kb_with_bucket, caplog):
        kb_with_bucket._s3_client.delete_object.side_effect = Exception("S3 failure")

        with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
            kb_with_bucket.delete(["doc-fail"])

        assert "Error deleting doc-fail from S3" in caplog.text
        # Ingestion is still triggered even if S3 delete fails
        kb_with_bucket._agent_client.start_ingestion_job.assert_called_once()

    @pytest.mark.usefixtures("_enable_log_propagation")
    def test_delete_missing_bucket_warns(self, caplog):
        kb = BedrockKB(
            knowledge_base_id="kb-123",
            data_source_bucket="",
        )

        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            kb.delete(["doc-1"])

        assert "No data_source_bucket configured" in caplog.text


class TestBedrockKBExists:
    """Test exists() checks KB status."""

    @pytest.fixture
    def kb(self):
        kb = BedrockKB(knowledge_base_id="kb-123")
        kb._agent_client = MagicMock()
        return kb

    def test_exists_returns_true_when_active(self, kb):
        kb._agent_client.get_knowledge_base.return_value = {
            "knowledgeBase": {"status": "ACTIVE"}
        }

        assert kb.exists() is True
        kb._agent_client.get_knowledge_base.assert_called_once_with(
            knowledgeBaseId="kb-123"
        )

    def test_exists_returns_false_when_not_active(self, kb):
        kb._agent_client.get_knowledge_base.return_value = {
            "knowledgeBase": {"status": "CREATING"}
        }

        assert kb.exists() is False

    def test_exists_returns_false_on_exception(self, kb):
        kb._agent_client.get_knowledge_base.side_effect = Exception("Not found")

        assert kb.exists() is False


class TestBedrockKBIngestionWarnings:
    """Test missing bucket and data source warnings."""

    @pytest.mark.usefixtures("_enable_log_propagation")
    def test_start_ingestion_warns_when_no_data_source_id(self, caplog):
        kb = BedrockKB(
            knowledge_base_id="kb-123",
            data_source_id="",
            data_source_bucket="my-bucket",
        )
        kb._s3_client = MagicMock()
        kb._agent_client = MagicMock()

        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            kb.upsert([{"id": "doc-1", "content": "test"}])

        assert "No data_source_id configured" in caplog.text
        kb._agent_client.start_ingestion_job.assert_not_called()

    @pytest.mark.usefixtures("_enable_log_propagation")
    def test_start_ingestion_logs_error_on_failure(self, caplog):
        kb = BedrockKB(
            knowledge_base_id="kb-123",
            data_source_id="ds-456",
            data_source_bucket="my-bucket",
        )
        kb._s3_client = MagicMock()
        kb._agent_client = MagicMock()
        kb._agent_client.start_ingestion_job.side_effect = Exception("Ingestion failed")

        with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
            kb.upsert([{"id": "doc-1", "content": "test"}])

        assert "Error starting ingestion" in caplog.text


class TestBedrockKBClientCreation:
    """Test that boto3 clients are created lazily with correct region."""

    @patch("boto3.client")
    def test_runtime_client_created_with_region(self, mock_boto3_client):
        kb = BedrockKB(knowledge_base_id="kb-123", region_name="ap-southeast-1")
        mock_boto3_client.return_value = MagicMock()

        _ = kb.runtime_client

        mock_boto3_client.assert_called_with(
            "bedrock-agent-runtime",
            region_name="ap-southeast-1",
            config=mock_boto3_client.call_args.kwargs.get("config"),
        )

    @patch("boto3.client")
    def test_agent_client_created_with_region(self, mock_boto3_client):
        kb = BedrockKB(knowledge_base_id="kb-123", region_name="ap-southeast-1")
        mock_boto3_client.return_value = MagicMock()

        _ = kb.agent_client

        mock_boto3_client.assert_called_with("bedrock-agent", region_name="ap-southeast-1")

    @patch("boto3.client")
    def test_s3_client_created_with_region(self, mock_boto3_client):
        kb = BedrockKB(knowledge_base_id="kb-123", region_name="ap-southeast-1")
        mock_boto3_client.return_value = MagicMock()

        _ = kb.s3_client

        mock_boto3_client.assert_called_with("s3", region_name="ap-southeast-1")

    @patch("boto3.client")
    def test_client_cached_after_first_access(self, mock_boto3_client):
        kb = BedrockKB(knowledge_base_id="kb-123", region_name="us-east-1")
        mock_boto3_client.return_value = MagicMock()

        client1 = kb.runtime_client
        client2 = kb.runtime_client

        assert client1 is client2
        assert mock_boto3_client.call_count == 1


class TestUpsertDirect:
    """Tests for CUSTOM data source (IngestKnowledgeBaseDocuments) path."""

    def test_upsert_direct_inline_text(self):
        from agno.vectordb.bedrock_kb.bedrock_kb import BedrockKB

        kb = BedrockKB(knowledge_base_id="TEST_KB", data_source_id="DS_CUSTOM", data_source_type="CUSTOM")
        mock_client = MagicMock()
        kb._agent_client = mock_client

        result = kb.upsert([{"content": "Test doc", "id": "doc-001", "metadata": {"k": "v"}}])

        assert result == ["doc-001"]
        mock_client.ingest_knowledge_base_documents.assert_called_once()
        doc = mock_client.ingest_knowledge_base_documents.call_args.kwargs["documents"][0]
        assert doc["content"]["custom"]["inlineContent"]["type"] == "TEXT"
        assert doc["content"]["custom"]["inlineContent"]["textContent"]["data"] == "Test doc"

    def test_upsert_direct_s3_reference(self):
        from agno.vectordb.bedrock_kb.bedrock_kb import BedrockKB

        kb = BedrockKB(knowledge_base_id="TEST_KB", data_source_id="DS_CUSTOM", data_source_type="CUSTOM")
        mock_client = MagicMock()
        kb._agent_client = mock_client

        result = kb.upsert([{"s3_uri": "s3://bucket/file.pdf", "id": "s3-001"}])

        assert result == ["s3-001"]
        doc = mock_client.ingest_knowledge_base_documents.call_args.kwargs["documents"][0]
        assert doc["content"]["custom"]["sourceType"] == "S3_LOCATION"
        assert doc["content"]["custom"]["s3Location"]["uri"] == "s3://bucket/file.pdf"

    def test_upsert_direct_binary(self):
        from agno.vectordb.bedrock_kb.bedrock_kb import BedrockKB

        kb = BedrockKB(knowledge_base_id="TEST_KB", data_source_id="DS_CUSTOM", data_source_type="CUSTOM")
        mock_client = MagicMock()
        kb._agent_client = mock_client

        result = kb.upsert([{"content": "base64data", "mime_type": "application/pdf", "id": "bin-001"}])

        assert result == ["bin-001"]
        doc = mock_client.ingest_knowledge_base_documents.call_args.kwargs["documents"][0]
        assert doc["content"]["custom"]["inlineContent"]["type"] == "BYTE"
        assert doc["content"]["custom"]["inlineContent"]["byteContent"]["mimeType"] == "application/pdf"

    def test_upsert_direct_no_ds_id_returns_empty(self):
        from agno.vectordb.bedrock_kb.bedrock_kb import BedrockKB

        kb = BedrockKB(knowledge_base_id="TEST_KB", data_source_type="CUSTOM")
        result = kb.upsert([{"content": "test"}])
        assert result == []
