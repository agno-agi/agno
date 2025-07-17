import json
import os
from typing import List, Optional

from neo4j import GraphDatabase

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger


class Neo4jTools(Toolkit):
    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        database: Optional[str] = None,
        list_labels: bool = True,
        list_relationships: bool = True,
        get_schema: bool = True,
        run_cypher: bool = True,
        **kwargs,
    ):
        """
        Initialize the Neo4jTools toolkit.
        Connection parameters (uri/user/password or host/port) can be provided.
        If not provided, falls back to NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD env vars.
        """
        # Determine the connection URI and credentials
        uri = uri or os.getenv("NEO4J_URI")
        user = user or os.getenv("NEO4J_USERNAME")
        password = password or os.getenv("NEO4J_PASSWORD")

        # If a host and port are provided instead of a full URI, construct the Bolt URI
        if uri is None and host and port:
            uri = f"bolt://{host}:{port}"
        if uri is None:
            raise ValueError("No Neo4j URI or host/port provided")
        if user is None or password is None:
            raise ValueError("Username or password for Neo4j not provided")

        # Create the Neo4j driver
        try:
            self.driver = GraphDatabase.driver(uri, auth=(user, password))
            self.driver.verify_connectivity()
            log_debug("Connected to Neo4j database")
        except Exception as e:
            logger.error(f"Failed to connect to Neo4j: {e}")
            raise

        self.database = database

        # Register toolkit methods as tools
        tools = []
        if list_labels:
            tools.append(self.list_labels)
        if list_relationships:
            tools.append(self.list_relationship_types)
        if get_schema:
            tools.append(self.get_schema)
        if run_cypher:
            tools.append(self.run_cypher_query)
        super().__init__(name="neo4j_tools", tools=tools, **kwargs)

    def list_labels(self) -> str:
        """List all node labels in the Neo4j database."""
        try:
            log_debug("Listing node labels in Neo4j database")
            with self.driver.session(database=self.database) as session:
                result = session.run("CALL db.labels()")
                # Each record has a 'label' field
                labels = [record["label"] for record in result]
            return json.dumps(labels)
        except Exception as e:
            logger.error(f"Error listing labels: {e}")
            return f"Error: {e}"

    def list_relationship_types(self) -> str:
        """List all relationship types in the Neo4j database."""
        try:
            log_debug("Listing relationship types in Neo4j database")
            with self.driver.session(database=self.database) as session:
                result = session.run("CALL db.relationshipTypes()")
                # Each record has a 'relationshipType' field
                types = [record["relationshipType"] for record in result]
            return json.dumps(types)
        except Exception as e:
            logger.error(f"Error listing relationship types: {e}")
            return f"Error: {e}"

    def get_schema(self) -> str:
        """Get the database schema (nodes and relationships) visualization."""
        try:
            log_debug("Retrieving Neo4j schema visualization")
            with self.driver.session(database=self.database) as session:
                result = session.run("CALL db.schema.visualization()")
                schema_data = result.data()
            return json.dumps(schema_data)
        except Exception as e:
            logger.error(f"Error getting Neo4j schema: {e}")
            return f"Error: {e}"

    def run_cypher_query(self, query: str) -> str:
        """Run an arbitrary Cypher query and return the result."""
        try:
            log_debug(f"Running Cypher query: {query}")
            with self.driver.session(database=self.database) as session:
                result = session.run(query)  # type: ignore[arg-type]
                data = result.data()
            return json.dumps(data, default=str)
        except Exception as e:
            logger.error(f"Error running Cypher query: {e}")
            return f"Error: {e}"
