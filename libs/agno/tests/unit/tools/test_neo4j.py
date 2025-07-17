from unittest.mock import patch
import pytest
from agno.tools.neo4j import Neo4jTools


def test_list_labels():
    with patch("neo4j.GraphDatabase.driver") as mock_driver:
        mock_session = mock_driver.return_value.session.return_value
        # Patch the context manager's __enter__ to return mock_session
        mock_session.__enter__.return_value = mock_session
        mock_run = mock_session.run
        mock_run.return_value = [{"label": "Person"}, {"label": "Movie"}]

        tools = Neo4jTools("uri", "user", "password")
        labels = tools.list_labels()
        assert labels == ["Person", "Movie"]
        mock_run.assert_called_with("CALL db.labels()")


def test_list_labels_connection_error():
    with patch("neo4j.GraphDatabase.driver") as mock_driver:
        mock_driver.side_effect = Exception("Connection error")

        with pytest.raises(Exception, match="Connection error"):
            tools = Neo4jTools("uri", "user", "password")
