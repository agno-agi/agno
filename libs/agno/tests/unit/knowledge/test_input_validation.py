"""
Unit tests for Knowledge input validation (KNOWLEDGE-005 fixes).

These tests verify that invalid inputs are rejected before any database
operations occur, using mocking to avoid database dependencies.
"""

from unittest.mock import MagicMock, patch

import pytest


class TestKnowledgeInputValidation:
    """Test input validation in Knowledge class."""

    @pytest.fixture
    def mock_vector_db(self):
        """Create a mock vector database."""
        mock = MagicMock()
        mock.exists.return_value = True
        mock.search.return_value = []
        return mock

    @pytest.fixture
    def knowledge(self, mock_vector_db):
        """Create a Knowledge instance with mocked vector_db."""
        from agno.knowledge import Knowledge

        return Knowledge(name="test", vector_db=mock_vector_db)

    # ========================================
    # Bug 1: Empty text_content validation
    # ========================================

    def test_insert_empty_text_content_rejected(self, knowledge):
        """Bug 1: insert() should reject empty string text_content."""
        with patch("agno.knowledge.knowledge.log_warning") as mock_warning:
            knowledge.insert(name="doc", text_content="")

            # Should log warning about empty string
            mock_warning.assert_called_once()
            assert "empty string" in mock_warning.call_args[0][0].lower()

    def test_insert_none_text_content_allowed(self, knowledge):
        """None text_content should be allowed (it's different from empty)."""
        # This should not raise - None means "not provided"
        with patch("agno.knowledge.knowledge.log_warning") as mock_warning:
            # When text_content is None but no other content provided
            knowledge.insert(name="doc", text_content=None)
            # Should warn about no content provided, not about empty string
            if mock_warning.called:
                assert "empty string" not in mock_warning.call_args[0][0].lower()

    def test_insert_valid_text_content_allowed(self, knowledge, mock_vector_db):
        """Valid text_content should be processed normally."""
        with patch("agno.knowledge.knowledge.log_warning") as mock_warning:
            with patch.object(knowledge, "_load_content") as mock_load:
                knowledge.insert(name="doc", text_content="Valid content here")

                # Should NOT warn about empty string
                for call in mock_warning.call_args_list:
                    assert "empty string" not in call[0][0].lower()

    # ========================================
    # Bug 3: Empty search query validation
    # ========================================

    def test_search_empty_query_returns_empty_list(self, knowledge, mock_vector_db):
        """Bug 3: search() should return [] for empty query."""
        with patch("agno.knowledge.knowledge.log_warning") as mock_warning:
            results = knowledge.search(query="")

            assert results == []
            mock_warning.assert_called_once()
            assert "empty" in mock_warning.call_args[0][0].lower()
            # Should NOT call the vector_db.search
            mock_vector_db.search.assert_not_called()

    # ========================================
    # Bug 4: Whitespace-only search query
    # ========================================

    def test_search_whitespace_query_returns_empty_list(self, knowledge, mock_vector_db):
        """Bug 4: search() should return [] for whitespace-only query."""
        with patch("agno.knowledge.knowledge.log_warning") as mock_warning:
            results = knowledge.search(query="   \t\n   ")

            assert results == []
            mock_warning.assert_called_once()
            # Should NOT call the vector_db.search
            mock_vector_db.search.assert_not_called()

    def test_search_valid_query_calls_vector_db(self, knowledge, mock_vector_db):
        """Valid query should call vector_db.search."""
        mock_vector_db.search.return_value = []

        results = knowledge.search(query="valid query")

        mock_vector_db.search.assert_called_once()

    # ========================================
    # Bug 5: max_results=0 validation
    # ========================================

    def test_search_max_results_zero_returns_empty_list(self, knowledge, mock_vector_db):
        """Bug 5: search() should return [] when max_results=0."""
        with patch("agno.knowledge.knowledge.log_warning") as mock_warning:
            results = knowledge.search(query="valid query", max_results=0)

            assert results == []
            mock_warning.assert_called_once()
            assert "positive" in mock_warning.call_args[0][0].lower()
            # Should NOT call the vector_db.search
            mock_vector_db.search.assert_not_called()

    # ========================================
    # Bug 6: Negative max_results validation
    # ========================================

    def test_search_negative_max_results_returns_empty_list(self, knowledge, mock_vector_db):
        """Bug 6: search() should return [] when max_results is negative."""
        with patch("agno.knowledge.knowledge.log_warning") as mock_warning:
            results = knowledge.search(query="valid query", max_results=-1)

            assert results == []
            mock_warning.assert_called_once()
            assert "positive" in mock_warning.call_args[0][0].lower()
            # Should NOT call the vector_db.search
            mock_vector_db.search.assert_not_called()

    def test_search_positive_max_results_allowed(self, knowledge, mock_vector_db):
        """Positive max_results should be passed to vector_db."""
        mock_vector_db.search.return_value = []

        results = knowledge.search(query="valid query", max_results=5)

        mock_vector_db.search.assert_called_once()
        call_kwargs = mock_vector_db.search.call_args[1]
        assert call_kwargs["limit"] == 5


class TestKnowledgeAsyncInputValidation:
    """Test input validation in Knowledge async methods."""

    @pytest.fixture
    def mock_vector_db(self):
        """Create a mock vector database with async support."""
        mock = MagicMock()
        mock.exists.return_value = True
        mock.async_search.return_value = []
        return mock

    @pytest.fixture
    def knowledge(self, mock_vector_db):
        """Create a Knowledge instance with mocked vector_db."""
        from agno.knowledge import Knowledge

        return Knowledge(name="test", vector_db=mock_vector_db)

    # ========================================
    # Async Bug 1: Empty text_content
    # ========================================

    @pytest.mark.asyncio
    async def test_ainsert_empty_text_content_rejected(self, knowledge):
        """ainsert() should reject empty string text_content."""
        with patch("agno.knowledge.knowledge.log_warning") as mock_warning:
            await knowledge.ainsert(name="doc", text_content="")

            mock_warning.assert_called_once()
            assert "empty string" in mock_warning.call_args[0][0].lower()

    # ========================================
    # Async Bug 3: Empty search query
    # ========================================

    @pytest.mark.asyncio
    async def test_asearch_empty_query_returns_empty_list(self, knowledge, mock_vector_db):
        """asearch() should return [] for empty query."""
        with patch("agno.knowledge.knowledge.log_warning") as mock_warning:
            results = await knowledge.asearch(query="")

            assert results == []
            mock_warning.assert_called_once()

    # ========================================
    # Async Bug 4: Whitespace-only query
    # ========================================

    @pytest.mark.asyncio
    async def test_asearch_whitespace_query_returns_empty_list(self, knowledge, mock_vector_db):
        """asearch() should return [] for whitespace-only query."""
        with patch("agno.knowledge.knowledge.log_warning") as mock_warning:
            results = await knowledge.asearch(query="   \t\n   ")

            assert results == []
            mock_warning.assert_called_once()

    # ========================================
    # Async Bug 5: max_results=0
    # ========================================

    @pytest.mark.asyncio
    async def test_asearch_max_results_zero_returns_empty_list(self, knowledge, mock_vector_db):
        """asearch() should return [] when max_results=0."""
        with patch("agno.knowledge.knowledge.log_warning") as mock_warning:
            results = await knowledge.asearch(query="valid query", max_results=0)

            assert results == []
            mock_warning.assert_called_once()

    # ========================================
    # Async Bug 6: Negative max_results
    # ========================================

    @pytest.mark.asyncio
    async def test_asearch_negative_max_results_returns_empty_list(self, knowledge, mock_vector_db):
        """asearch() should return [] when max_results is negative."""
        with patch("agno.knowledge.knowledge.log_warning") as mock_warning:
            results = await knowledge.asearch(query="valid query", max_results=-1)

            assert results == []
            mock_warning.assert_called_once()
