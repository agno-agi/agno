import unittest
from unittest.mock import MagicMock, patch

from agno.db.schemas.knowledge import KnowledgeRow
from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge


class TestKnowledgeAccessCount(unittest.TestCase):
    def setUp(self):
        self.mock_vector_db = MagicMock()
        self.mock_contents_db = MagicMock()
        self.knowledge = Knowledge(vector_db=self.mock_vector_db, contents_db=self.mock_contents_db, max_results=10)

    def test_search_increments_access_count(self):
        mock_docs = [
            Document(content="doc1", content_id="content_1", id="1"),
            Document(content="doc2", content_id="content_2", id="2"),
            Document(content="doc3", content_id="content_1", id="3"),
            Document(content="doc4", content_id=None, id="4"),
        ]

        self.mock_vector_db.search.return_value = mock_docs
        self.mock_contents_db.increment_knowledge_access_count.return_value = KnowledgeRow(
            id="content_1", name="Test Content", description="Test", access_count=1
        )

        results = self.knowledge.search("test query")

        self.mock_vector_db.search.assert_called_once_with(query="test query", limit=10, filters=None)

        self.assertEqual(self.mock_contents_db.increment_knowledge_access_count.call_count, 2)

        called_ids = [call[0][0] for call in self.mock_contents_db.increment_knowledge_access_count.call_args_list]
        self.assertSetEqual(set(called_ids), {"content_1", "content_2"})

        self.assertEqual(results, mock_docs)

    def test_search_without_contents_db(self):
        knowledge = Knowledge(vector_db=self.mock_vector_db, contents_db=None, max_results=10)

        mock_docs = [
            Document(content="doc1", content_id="content_1", id="1"),
        ]
        self.mock_vector_db.search.return_value = mock_docs

        results = knowledge.search("test query")

        self.mock_vector_db.search.assert_called_once()
        self.assertEqual(results, mock_docs)

    def test_search_handles_increment_errors_gracefully(self):
        mock_docs = [
            Document(content="doc1", content_id="content_1", id="1"),
        ]

        self.mock_vector_db.search.return_value = mock_docs
        self.mock_contents_db.increment_knowledge_access_count.side_effect = Exception("Database error")

        results = self.knowledge.search("test query")

        self.mock_contents_db.increment_knowledge_access_count.assert_called_once_with("content_1")
        self.assertEqual(results, mock_docs)

    @patch("agno.knowledge.knowledge.log_debug")
    def test_async_search_increments_access_count(self, mock_log_debug):
        import asyncio

        async def run_test():
            mock_docs = [
                Document(content="doc1", content_id="content_1", id="1"),
                Document(content="doc2", content_id="content_2", id="2"),
            ]

            async def async_search_mock(*args, **kwargs):
                return mock_docs

            self.mock_vector_db.async_search = MagicMock(side_effect=async_search_mock)
            self.mock_contents_db.increment_knowledge_access_count.return_value = KnowledgeRow(
                id="content_1", name="Test Content", description="Test", access_count=1
            )

            results = await self.knowledge.async_search("test query")

            self.mock_vector_db.async_search.assert_called_once_with(query="test query", limit=10, filters=None)

            self.assertEqual(self.mock_contents_db.increment_knowledge_access_count.call_count, 2)

            called_ids = [call[0][0] for call in self.mock_contents_db.increment_knowledge_access_count.call_args_list]
            self.assertSetEqual(set(called_ids), {"content_1", "content_2"})

            self.assertEqual(results, mock_docs)

        asyncio.run(run_test())

    def test_search_with_empty_results(self):
        self.mock_vector_db.search.return_value = []

        results = self.knowledge.search("test query")

        self.mock_vector_db.search.assert_called_once()
        self.mock_contents_db.increment_knowledge_access_count.assert_not_called()
        self.assertEqual(results, [])

    def test_search_filters_duplicate_content_ids(self):
        mock_docs = [
            Document(content="doc1", content_id="content_1", id="1"),
            Document(content="doc2", content_id="content_1", id="2"),
            Document(content="doc3", content_id="content_1", id="3"),
        ]

        self.mock_vector_db.search.return_value = mock_docs

        results = self.knowledge.search("test query")

        self.mock_contents_db.increment_knowledge_access_count.assert_called_once_with("content_1")
        self.assertEqual(results, mock_docs)


if __name__ == "__main__":
    unittest.main()
