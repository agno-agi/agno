import os
import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

try:
    from neo4j import READ_ACCESS, WRITE_ACCESS, GraphDatabase
except ImportError:
    raise ImportError("`neo4j` not installed. Please install using `pip install neo4j`")

from agno.tools import Toolkit
from agno.tools._security import redact_password, unwrap_secret
from agno.utils.log import log_debug, log_warning, logger

if TYPE_CHECKING:
    from pydantic import SecretStr


_CYPHER_WRITE_RE: re.Pattern = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|FOREACH|CALL\s+dbms|"
    r"CALL\s+apoc\.(?:create|merge|cypher\.doIt))\b",
    re.IGNORECASE,
)


class Neo4jTools(Toolkit):
    """Neo4j toolkit.

    Security notes (hardened build):

    * ``read_only`` defaults to ``True``. Sessions are opened with
      :data:`neo4j.READ_ACCESS`, and :meth:`run_cypher_query`
      additionally rejects queries that match known write / DDL /
      procedure-invocation patterns.
    * ``password`` accepts either ``pydantic.SecretStr`` or a plain
      string, and is never surfaced in ``__repr__``. When the caller
      does not supply a password, ``$NEO4J_PASSWORD`` is read from
      the environment.
    * :meth:`run_cypher_query` takes an optional ``params`` mapping
      so agents should always use ``$placeholder`` parameters rather
      than string concatenation.

    Args:
        uri: Bolt URI. Defaults to ``$NEO4J_URI`` or
            ``"bolt://localhost:7687"``.
        user: Username. Defaults to ``$NEO4J_USERNAME``.
        password: Password. ``SecretStr`` recommended. Defaults to
            ``$NEO4J_PASSWORD``.
        database: Target database name. Defaults to ``"neo4j"``.
        read_only: When True (default), sessions open in read-access
            mode and write-looking Cypher is refused.
        enable_list_labels: Register :meth:`list_labels`.
        enable_list_relationships: Register
            :meth:`list_relationship_types`.
        enable_get_schema: Register :meth:`get_schema`.
        enable_run_cypher: Register :meth:`run_cypher_query`.
    """

    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[Union[str, "SecretStr"]] = None,
        database: Optional[str] = None,
        read_only: bool = True,
        enable_list_labels: bool = True,
        enable_list_relationships: bool = True,
        enable_get_schema: bool = True,
        enable_run_cypher: bool = True,
        all: bool = False,
        **kwargs,
    ):
        uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
        user = user or os.getenv("NEO4J_USERNAME")

        pw_plain = unwrap_secret(password) or os.getenv("NEO4J_PASSWORD")

        if user is None or pw_plain is None:
            raise ValueError("Username or password for Neo4j not provided")

        try:
            self.driver = GraphDatabase.driver(uri, auth=(user, pw_plain))
            self.driver.verify_connectivity()
            log_debug("Connected to Neo4j database")
        except Exception:
            logger.exception("Failed to connect to Neo4j")
            raise

        self.database: str = database or "neo4j"
        self.read_only: bool = bool(read_only)
        self._user: str = user
        self._uri: str = uri
        self._has_password: bool = bool(pw_plain)

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

    def __repr__(self) -> str:
        return (
            f"Neo4jTools(uri={self._uri!r}, user={self._user!r}, "
            f"database={self.database!r}, read_only={self.read_only!r}, "
            f"password={redact_password(self._has_password and '_')!r})"
        )

    def _session(self):
        """Return a Neo4j session in the configured access mode."""
        access = READ_ACCESS if self.read_only else WRITE_ACCESS
        return self.driver.session(database=self.database, default_access_mode=access)

    def list_labels(self) -> List[str]:
        """Retrieve all node labels present in the connected database."""
        try:
            log_debug("Listing node labels in Neo4j database")
            with self._session() as session:
                result = session.run("CALL db.labels()")
                return [record["label"] for record in result]
        except Exception:
            logger.exception("Error listing labels")
            return []

    def list_relationship_types(self) -> List[str]:
        """Retrieve all relationship types present in the connected database."""
        try:
            log_debug("Listing relationship types in Neo4j database")
            with self._session() as session:
                result = session.run("CALL db.relationshipTypes()")
                return [record["relationshipType"] for record in result]
        except Exception:
            logger.exception("Error listing relationship types")
            return []

    def get_schema(self) -> list:
        """Retrieve a visualization of the database schema."""
        try:
            log_debug("Retrieving Neo4j schema visualization")
            with self._session() as session:
                result = session.run("CALL db.schema.visualization()")
                return result.data()
        except Exception:
            logger.exception("Error getting Neo4j schema")
            return []

    def run_cypher_query(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> list:
        """Execute a Cypher query against the connected database.

        Args:
            query: The Cypher query string to execute. Use ``$param``
                placeholders and provide values via ``params``.
            params: Query parameters keyed by placeholder name.

        Returns:
            A list of result records as plain dicts, or a single-item
            list containing an ``error`` dict when the query is
            refused in read-only mode.
        """
        if not isinstance(query, str) or not query.strip():
            return []
        if self.read_only and _CYPHER_WRITE_RE.search(query):
            log_warning("Neo4jTools rejected write-looking query in read-only mode.")
            return [{"error": ("Write / DDL / procedure cypher is blocked in read-only mode.")}]
        try:
            log_debug(f"Running Cypher query: {query}")
            with self._session() as session:
                result = session.run(query, params or {})  # type: ignore[arg-type]
                return result.data()
        except Exception:
            logger.exception("Error running Cypher query")
            return []
