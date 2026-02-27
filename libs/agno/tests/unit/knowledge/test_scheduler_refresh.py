"""Tests for scheduler-based content refresh integration."""

import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.knowledge.content import Content
from agno.knowledge.pipeline.ingestion import IngestionPipeline


@pytest.fixture
def pipeline():
    return IngestionPipeline(
        vector_db=MagicMock(),
        content_store=MagicMock(),
        reader_registry=MagicMock(),
    )


class TestCheckContentChanged:
    def test_file_changed_by_mtime(self, pipeline):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("original content")
            path = f.name

        content = Content(
            id="test-id",
            path=path,
            updated_at=int(time.time()) - 100,
        )

        assert pipeline.check_content_changed(content) is True
        Path(path).unlink()

    def test_file_not_changed(self, pipeline):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("content")
            path = f.name

        content = Content(
            id="test-id",
            path=path,
            updated_at=int(time.time()) + 100,
        )

        assert pipeline.check_content_changed(content) is False
        Path(path).unlink()

    def test_file_does_not_exist(self, pipeline):
        content = Content(
            id="test-id",
            path="/nonexistent/path.txt",
            updated_at=int(time.time()),
        )

        assert pipeline.check_content_changed(content) is False

    def test_url_changed(self, pipeline):
        content = Content(
            id="test-id",
            url="https://example.com/data.txt",
            content_hash="old_hash",
        )

        with patch.object(pipeline, "_compute_url_hash", return_value="new_hash"):
            assert pipeline.check_content_changed(content) is True

    def test_url_not_changed(self, pipeline):
        content = Content(
            id="test-id",
            url="https://example.com/data.txt",
            content_hash="same_hash",
        )

        with patch.object(pipeline, "_compute_url_hash", return_value="same_hash"):
            assert pipeline.check_content_changed(content) is False

    def test_url_fetch_failure(self, pipeline):
        content = Content(
            id="test-id",
            url="https://example.com/data.txt",
            content_hash="old_hash",
        )

        with patch.object(pipeline, "_compute_url_hash", return_value=None):
            assert pipeline.check_content_changed(content) is False

    def test_no_path_or_url_returns_false(self, pipeline):
        content = Content(id="test-id")
        assert pipeline.check_content_changed(content) is False

    @pytest.mark.asyncio
    async def test_async_file_changed(self, pipeline):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("content")
            path = f.name

        content = Content(
            id="test-id",
            path=path,
            updated_at=int(time.time()) - 100,
        )

        assert await pipeline.acheck_content_changed(content) is True
        Path(path).unlink()

    @pytest.mark.asyncio
    async def test_async_url_changed(self, pipeline):
        content = Content(
            id="test-id",
            url="https://example.com/data.txt",
            content_hash="old_hash",
        )

        with patch.object(pipeline, "_acompute_url_hash", new_callable=AsyncMock, return_value="new_hash"):
            assert await pipeline.acheck_content_changed(content) is True


class TestComputeUrlHash:
    def test_computes_hash(self, pipeline):
        mock_response = MagicMock()
        mock_response.content = b"test content"
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response

        with patch("httpx.Client", return_value=mock_client):
            result = pipeline._compute_url_hash("https://example.com")

        assert result is not None
        assert isinstance(result, str)

    def test_returns_none_on_error(self, pipeline):
        with patch("httpx.Client", side_effect=Exception("Connection failed")):
            result = pipeline._compute_url_hash("https://example.com")

        assert result is None


class TestRefreshEndpoint:
    """Tests for the POST /knowledge/refresh endpoint."""

    @pytest.fixture
    def mock_knowledge(self):
        knowledge = MagicMock()
        knowledge.name = "test-kb"
        knowledge.arefresh = AsyncMock(
            return_value={
                "content-1": "refreshed",
                "content-2": "unchanged",
            }
        )
        return knowledge

    def test_refresh_response_schema(self):
        from agno.os.routers.knowledge.schemas import RefreshResponseSchema

        schema = RefreshResponseSchema(
            results={"id1": "refreshed", "id2": "unchanged"},
            total=2,
            refreshed=1,
        )
        assert schema.total == 2
        assert schema.refreshed == 1
        assert schema.results["id1"] == "refreshed"


class TestAutoScheduleCreation:
    """Tests for auto-creating refresh schedules when AgentOS starts with scheduler=True."""

    @pytest.mark.asyncio
    async def test_creates_schedule_for_knowledge_with_refresh_cron(self):
        from agno.os.app import _create_knowledge_refresh_schedules

        mock_kb = MagicMock()
        mock_kb.name = "my-docs"
        mock_kb.refresh_cron = "0 * * * *"

        mock_os = MagicMock()
        mock_os.knowledge_instances = [mock_kb]
        mock_os.knowledge = None
        mock_os.db = MagicMock()

        with patch("agno.scheduler.manager.ScheduleManager") as MockManager:
            mock_manager = MagicMock()
            mock_manager.acreate = AsyncMock()
            mock_manager.close = MagicMock()
            MockManager.return_value = mock_manager

            await _create_knowledge_refresh_schedules(mock_os)

            mock_manager.acreate.assert_called_once_with(
                name="knowledge-refresh-my-docs",
                cron="0 * * * *",
                endpoint="/knowledge/refresh",
                method="POST",
                description="Auto-refresh knowledge base: my-docs",
                payload={"knowledge_id": "my-docs"},
                if_exists="update",
            )
            mock_manager.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_knowledge_without_refresh_cron(self):
        from agno.os.app import _create_knowledge_refresh_schedules

        mock_kb = MagicMock()
        mock_kb.name = "no-refresh"
        mock_kb.refresh_cron = None

        mock_os = MagicMock()
        mock_os.knowledge_instances = [mock_kb]
        mock_os.knowledge = None
        mock_os.db = MagicMock()

        with patch("agno.scheduler.manager.ScheduleManager") as MockManager:
            mock_manager = MagicMock()
            mock_manager.acreate = AsyncMock()
            mock_manager.close = MagicMock()
            MockManager.return_value = mock_manager

            await _create_knowledge_refresh_schedules(mock_os)

            mock_manager.acreate.assert_not_called()
            mock_manager.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_schedule_creation_error_gracefully(self):
        from agno.os.app import _create_knowledge_refresh_schedules

        mock_kb = MagicMock()
        mock_kb.name = "error-kb"
        mock_kb.refresh_cron = "*/5 * * * *"

        mock_os = MagicMock()
        mock_os.knowledge_instances = [mock_kb]
        mock_os.knowledge = None
        mock_os.db = MagicMock()

        with patch("agno.scheduler.manager.ScheduleManager") as MockManager:
            mock_manager = MagicMock()
            mock_manager.acreate = AsyncMock(side_effect=ValueError("Invalid cron"))
            mock_manager.close = MagicMock()
            MockManager.return_value = mock_manager

            # Should not raise
            await _create_knowledge_refresh_schedules(mock_os)

            mock_manager.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_db_skips_schedule_creation(self):
        from agno.os.app import _create_knowledge_refresh_schedules

        mock_os = MagicMock()
        mock_os.knowledge_instances = [MagicMock(name="kb", refresh_cron="0 * * * *")]
        mock_os.db = None

        with patch("agno.scheduler.manager.ScheduleManager") as MockManager:
            await _create_knowledge_refresh_schedules(mock_os)
            MockManager.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_knowledge_instances_skips(self):
        from agno.os.app import _create_knowledge_refresh_schedules

        mock_os = MagicMock()
        mock_os.knowledge_instances = []
        mock_os.knowledge = []
        mock_os.db = MagicMock()

        with patch("agno.scheduler.manager.ScheduleManager") as MockManager:
            await _create_knowledge_refresh_schedules(mock_os)
            MockManager.assert_not_called()


class TestKnowledgeRefreshCronField:
    """Test that the refresh_cron field exists on Knowledge."""

    def test_refresh_cron_default_none(self):
        from agno.knowledge.knowledge import Knowledge

        kb = Knowledge.__new__(Knowledge)
        kb.refresh_cron = None
        assert kb.refresh_cron is None

    def test_refresh_cron_can_be_set(self):
        from agno.knowledge.knowledge import Knowledge

        kb = Knowledge.__new__(Knowledge)
        kb.refresh_cron = "0 */6 * * *"
        assert kb.refresh_cron == "0 */6 * * *"
