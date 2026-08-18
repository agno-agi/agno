import json
import os
from typing import Callable, List, Optional

try:
    from neo4j import GraphDatabase
except ImportError:
    raise ImportError("`neo4j` not installed. Please install using `pip install neo4j`")

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger


class Neo4jTools(Toolkit):
    # Agno 2.x kwarg names accepted for backwards compatibility
    _legacy_param_aliases = {
        "enable_list_relationships": "list_relationship_types",
        "enable_run_cypher": "run_cypher_query",
    }

    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None,
        list_labels: bool = True,
        list_relationship_types: bool = True,
        get_schema: bool = True,
        run_cypher_query: bool = False,
        all: bool = False,
        **kwargs,
    ):
        """
        Initialize the Neo4jTools toolkit for interacting with a Neo4j graph database.

        Connection parameters can be provided directly or via environment variables
        (NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD).

        Args:
            uri: Neo4j connection URI (default: bolt://localhost:7687 or NEO4J_URI env var)
            user: Neo4j username (falls back to NEO4J_USERNAME env var)
            password: Neo4j password (falls back to NEO4J_PASSWORD env var)
            database: Neo4j database name (default: "neo4j")
            list_labels: Register the list_labels tool
            list_relationship_types: Register the list_relationship_types tool
            get_schema: Register the get_schema tool
            run_cypher_query: Register the run_cypher_query tool (can execute arbitrary queries)
            all: Register all tools
        """
        # Determine the connection URI and credentials
        uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
        user = user or os.getenv("NEO4J_USERNAME")
        password = password or os.getenv("NEO4J_PASSWORD")

        if user is None or password is None:
            raise ValueError("Username or password for Neo4j not provided")

        # Create the Neo4j driver
        try:
            self.driver = GraphDatabase.driver(uri, auth=(user, password))  # type: ignore
            self.driver.verify_connectivity()
            log_debug("Connected to Neo4j database")
        except Exception:
            logger.exception("Failed to connect to Neo4j")
            raise

        self.database = database or "neo4j"

        # Register toolkit methods as tools
        tools: List[Callable] = []
        if all or list_labels:
            tools.append(self.list_neo4j_labels)
        if all or list_relationship_types:
            tools.append(self.list_neo4j_relationship_types)
        if all or get_schema:
            tools.append(self.get_neo4j_schema)
        if all or run_cypher_query:
            tools.append(self.run_neo4j_cypher_query)
        super().__init__(name="neo4j_tools", tools=tools, **kwargs)

    def list_neo4j_labels(self) -> str:
        """
        Retrieve all node labels present in the connected Neo4j database.

        Returns:
            JSON array of label strings
        """
        try:
            log_debug("Listing node labels in Neo4j database")
            with self.driver.session(database=self.database) as session:
                result = session.run("CALL db.labels()")
                labels = [record["label"] for record in result]
            return json.dumps(labels, default=str)
        except Exception as e:
            logger.exception("Error listing labels")
            return json.dumps({"error": f"Error listing labels: {e}"})

    def list_neo4j_relationship_types(self) -> str:
        """
        Retrieve all relationship types present in the connected Neo4j database.

        Returns:
            JSON array of relationship type strings
        """
        try:
            log_debug("Listing relationship types in Neo4j database")
            with self.driver.session(database=self.database) as session:
                result = session.run("CALL db.relationshipTypes()")
                types = [record["relationshipType"] for record in result]
            return json.dumps(types, default=str)
        except Exception as e:
            logger.exception("Error listing relationship types")
            return json.dumps({"error": f"Error listing relationship types: {e}"})

    def get_neo4j_schema(self) -> str:
        """
        Retrieve a visualization of the database schema, including nodes and relationships.

        Returns:
            JSON array with schema visualization data
        """
        try:
            log_debug("Retrieving Neo4j schema visualization")
            with self.driver.session(database=self.database) as session:
                result = session.run("CALL db.schema.visualization()")
                schema_data = result.data()
            return json.dumps(schema_data, default=str)
        except Exception as e:
            logger.exception("Error getting Neo4j schema")
            return json.dumps({"error": f"Error getting Neo4j schema: {e}"})

    def run_neo4j_cypher_query(self, query: str) -> str:
        """
        Execute an arbitrary Cypher query against the connected Neo4j database.

        Args:
            query: The Cypher query string to execute

        Returns:
            JSON array of result records
        """
        try:
            log_debug(f"Running Cypher query: {query}")
            with self.driver.session(database=self.database) as session:
                result = session.run(query)  # type: ignore[arg-type]
                data = result.data()
            return json.dumps(data, default=str)
        except Exception as e:
            logger.exception("Error running Cypher query")
            return json.dumps({"error": f"Error running Cypher query: {e}"})
