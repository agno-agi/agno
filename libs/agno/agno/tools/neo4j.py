import os
from typing import Any, List, Optional

try:
    from neo4j import GraphDatabase
except ImportError:
    raise ImportError("`neo4j` not installed. Please install using `pip install neo4j`")

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger


class Neo4jTools(Toolkit):
    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None,
        # Enable flags for <6 functions
        enable_list_labels: bool = True,
        enable_list_relationships: bool = True,
        enable_get_schema: bool = True,
        enable_run_cypher: bool = True,
        all: bool = False,
        **kwargs,
    ):
        """
        Initialize the Neo4jTools toolkit.
        Connection parameters (uri/user/password or host/port) can be provided.
        If not provided, falls back to NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD env vars.

        Args:
            uri (Optional[str]): The Neo4j URI.
            user (Optional[str]): The Neo4j username.
            password (Optional[str]): The Neo4j password.
            host (Optional[str]): The Neo4j host.
            port (Optional[int]): The Neo4j port.
            database (Optional[str]): The Neo4j database.
            list_labels (bool): Whether to list node labels.
            list_relationships (bool): Whether to list relationship types.
            get_schema (bool): Whether to get the schema.
            run_cypher (bool): Whether to run Cypher queries.
            **kwargs: Additional keyword arguments.
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
        except Exception as e:
            logger.error(f"Failed to connect to Neo4j: {e}")
            raise

        self.database = database or "neo4j"

        # Register toolkit methods as tools
        tools: List[Any] = []
        if all or enable_list_labels:
            tools.append(self.list_labels)
        if all or enable_list_relationships:
            tools.append(self.list_relationship_types)
        if all or enable_get_schema:
            tools.append(self.get_schema)
        if all or enable_run_cypher:
            tools.append(self.run_cypher_query)
        super().__init__(name="neo4j_tools", tools=tools, **kwargs)

    def list_labels(self) -> list:
        """
        Retrieve all node labels present in the connected Neo4j database.
        """
        try:
            log_debug("Listing node labels in Neo4j database")
            with self.driver.session(database=self.database) as session:
                result = session.run("CALL db.labels()")
                labels = [record["label"] for record in result]
            return labels
        except Exception as e:
            logger.error(f"Error listing labels: {e}")
            return []

    def list_relationship_types(self) -> list:
        """
        Retrieve all relationship types present in the connected Neo4j database.
        """
        try:
            log_debug("Listing relationship types in Neo4j database")
            with self.driver.session(database=self.database) as session:
                result = session.run("CALL db.relationshipTypes()")
                types = [record["relationshipType"] for record in result]
            return types
        except Exception as e:
            logger.error(f"Error listing relationship types: {e}")
            return []

    def get_schema(self) -> list:
        """
        Retrieve a visualization of the database schema, including nodes and relationships.
        """
        try:
            log_debug("Retrieving Neo4j schema visualization")
            with self.driver.session(database=self.database) as session:
                result = session.run("CALL db.schema.visualization()")
                schema_data = result.data()
            return schema_data
        except Exception as e:
            logger.error(f"Error getting Neo4j schema: {e}")
            return []

    def run_cypher_query(self, query: str) -> list:
        """
        Execute an arbitrary Cypher query against the connected Neo4j database.

        Args:
            query (str): The Cypher query string to execute.
        """
        try:
            log_debug(f"Running Cypher query: {query}")
            with self.driver.session(database=self.database) as session:
                result = session.run(query)  # type: ignore[arg-type]
                data = result.data()
            return data
        except Exception as e:
            logger.error(f"Error running Cypher query: {e}")
            return []
