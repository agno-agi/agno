import os
from unittest.mock import MagicMock, patch

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
            Neo4jTools("uri", "user", "password")


def test_list_labels_runtime_error():
    with patch("neo4j.GraphDatabase.driver") as mock_driver:
        mock_session = mock_driver.return_value.session.return_value
        mock_session.__enter__.return_value = mock_session
        mock_session.run.side_effect = Exception("Query failed")

        tools = Neo4jTools("uri", "user", "password")
        labels = tools.list_labels()
        assert labels == []


def test_list_relationship_types():
    with patch("neo4j.GraphDatabase.driver") as mock_driver:
        mock_session = mock_driver.return_value.session.return_value
        mock_session.__enter__.return_value = mock_session
        mock_run = mock_session.run
        mock_run.return_value = [{"relationshipType": "ACTED_IN"}, {"relationshipType": "DIRECTED"}]

        tools = Neo4jTools("uri", "user", "password")
        rel_types = tools.list_relationship_types()
        assert rel_types == ["ACTED_IN", "DIRECTED"]
        mock_run.assert_called_with("CALL db.relationshipTypes()")


def test_list_relationship_types_error():
    with patch("neo4j.GraphDatabase.driver") as mock_driver:
        mock_session = mock_driver.return_value.session.return_value
        mock_session.__enter__.return_value = mock_session
        mock_session.run.side_effect = Exception("Query failed")

        tools = Neo4jTools("uri", "user", "password")
        rel_types = tools.list_relationship_types()
        assert rel_types == []


def test_get_schema():
    with patch("neo4j.GraphDatabase.driver") as mock_driver:
        mock_session = mock_driver.return_value.session.return_value
        mock_session.__enter__.return_value = mock_session
        mock_result = MagicMock()
        mock_result.data.return_value = [
            {"nodes": [{"id": 1, "labels": ["Person"]}], "relationships": [{"id": 1, "type": "ACTED_IN"}]}
        ]
        mock_session.run.return_value = mock_result

        tools = Neo4jTools("uri", "user", "password")
        schema = tools.get_schema()
        assert len(schema) == 1
        assert "nodes" in schema[0]
        assert "relationships" in schema[0]
        mock_session.run.assert_called_with("CALL db.schema.visualization()")


def test_get_schema_error():
    with patch("neo4j.GraphDatabase.driver") as mock_driver:
        mock_session = mock_driver.return_value.session.return_value
        mock_session.__enter__.return_value = mock_session
        mock_session.run.side_effect = Exception("Schema query failed")

        tools = Neo4jTools("uri", "user", "password")
        schema = tools.get_schema()
        assert schema == []


def test_run_cypher_query():
    with patch("neo4j.GraphDatabase.driver") as mock_driver:
        mock_session = mock_driver.return_value.session.return_value
        mock_session.__enter__.return_value = mock_session
        mock_result = MagicMock()
        mock_result.data.return_value = [{"name": "John", "age": 30}, {"name": "Jane", "age": 25}]
        mock_session.run.return_value = mock_result

        tools = Neo4jTools("uri", "user", "password")
        query = "MATCH (p:Person) RETURN p.name as name, p.age as age"
        result = tools.run_cypher_query(query)

        assert len(result) == 2
        assert result[0]["name"] == "John"
        assert result[1]["name"] == "Jane"
        mock_session.run.assert_called_with(query)


def test_run_cypher_query_error():
    with patch("neo4j.GraphDatabase.driver") as mock_driver:
        mock_session = mock_driver.return_value.session.return_value
        mock_session.__enter__.return_value = mock_session
        mock_session.run.side_effect = Exception("Cypher query failed")

        tools = Neo4jTools("uri", "user", "password")
        result = tools.run_cypher_query("INVALID QUERY")
        assert result == []


def test_initialization_with_env_vars():
    with (
        patch("neo4j.GraphDatabase.driver") as mock_driver,
        patch.dict(
            os.environ,
            {"NEO4J_URI": "bolt://test-host:7687", "NEO4J_USERNAME": "test_user", "NEO4J_PASSWORD": "test_pass"},
        ),
    ):
        Neo4jTools()
        mock_driver.assert_called_with("bolt://test-host:7687", auth=("test_user", "test_pass"))


def test_initialization_missing_credentials():
    with patch("neo4j.GraphDatabase.driver"), patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ValueError, match="Username or password for Neo4j not provided"):
            Neo4jTools()


def test_initialization_custom_database():
    with patch("neo4j.GraphDatabase.driver") as _:
        tools = Neo4jTools("uri", "user", "password", database="custom_db")
        assert tools.database == "custom_db"


def test_initialization_default_database():
    with patch("neo4j.GraphDatabase.driver") as _:
        tools = Neo4jTools("uri", "user", "password")
        assert tools.database == "neo4j"


def test_initialization_selective_tools():
    with patch("neo4j.GraphDatabase.driver") as _:
        tools = Neo4jTools(
            "uri",
            "user",
            "password",
            enable_list_labels=True,
            enable_list_relationships=False,
            enable_get_schema=False,
            enable_run_cypher=True,
        )

        # Check that only selected tools are registered
        tool_names = [tool.__name__ for tool in tools.tools]
        assert "list_labels" in tool_names
        assert "run_cypher_query" in tool_names
        assert "list_relationship_types" not in tool_names
        assert "get_schema" not in tool_names


def test_driver_connectivity_verification():
    with patch("neo4j.GraphDatabase.driver") as mock_driver:
        mock_driver_instance = mock_driver.return_value
        mock_driver_instance.verify_connectivity.side_effect = Exception("Connection failed")

        with pytest.raises(Exception, match="Connection failed"):
            Neo4jTools("uri", "user", "password")
