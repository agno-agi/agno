dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
from typing import Any, Dict, Iterable, List, Optional
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):

dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
from agno.document import Document
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
from agno.embedder import Embedder
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
from agno.utils.log import logger
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
from agno.vectordb.base import VectorDb
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
from agno.vectordb.cassandra.index import AgnoMetadataVectorCassandraTable
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):

dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):

dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
class Cassandra(VectorDb):
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
    def __init__(
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        self,
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        table_name: str,
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        keyspace: str,
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        embedder: Optional[Embedder] = None,
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        session=None,
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
    ) -> None:
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        if not table_name:
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
            raise ValueError("Table name must be provided.")
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):

dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        if not session:
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
            raise ValueError("Session is not provided")
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):

dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        if not keyspace:
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
            raise ValueError("Keyspace must be provided")
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):

dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        if embedder is None:
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
            from agno.embedder.openai import OpenAIEmbedder
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):

dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
            embedder = OpenAIEmbedder()
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
            logger.info("Embedder not provided, using OpenAIEmbedder as default.")
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        self.table_name: str = table_name
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        self.embedder: Embedder = embedder
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        # Validate keyspace and table_name to prevent CQL injection
        identifier_regex = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
        if not identifier_regex.match(keyspace):
            raise ValueError(
                f"Invalid keyspace name '{keyspace}'. "
                "Only alphanumeric characters and underscores are allowed, "
                "and it must start with a letter."
            )
        if not identifier_regex.match(table_name):
            raise ValueError(
                f"Invalid table name '{table_name}'. "
                "Only alphanumeric characters and underscores are allowed, "
                "and it must start with a letter."
            )

        self.session = session
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        self.keyspace: str = keyspace
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        self.initialize_table()
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):

dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
    def initialize_table(self):
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        self.table = AgnoMetadataVectorCassandraTable(
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
            session=self.session,
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
            keyspace=self.keyspace,
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
            vector_dimension=1024,
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
            table=self.table_name,
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
            primary_key_type="TEXT",
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        )
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):

dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
    def create(self) -> None:
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        """Create the table in Cassandra for storing vectors and metadata."""
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        if not self.exists():
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
            logger.debug(f"Cassandra VectorDB : Creating table {self.table_name}")
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
            self.initialize_table()
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):

dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
    def _row_to_document(self, row: Dict[str, Any]) -> Document:
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        return Document(
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
            id=row["row_id"],
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
            content=row["body_blob"],
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
            meta_data=row["metadata"],
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
            embedding=row["vector"],
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
            name=row["document_name"],
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        )
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):

dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
    def doc_exists(self, document: Document) -> bool:
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        """Check if a document exists by ID."""
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        query = f"SELECT COUNT(*) FROM {self.keyspace}.{self.table_name} WHERE row_id = %s"
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        result = self.session.execute(query, (document.id,))
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        return result.one()[0] > 0
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):

dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
    def name_exists(self, name: str) -> bool:
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        """Check if a document exists by name."""
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        query = f"SELECT COUNT(*) FROM {self.keyspace}.{self.table_name} WHERE document_name = %s ALLOW FILTERING"
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        result = self.session.execute(query, (name,))
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        return result.one()[0] > 0
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):

dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
    def id_exists(self, id: str) -> bool:
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        """Check if a document exists by ID."""
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        query = f"SELECT COUNT(*) FROM {self.keyspace}.{self.table_name} WHERE row_id = %s ALLOW FILTERING"
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        result = self.session.execute(query, (id,))
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        return result.one()[0] > 0
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):

dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
    def insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        logger.debug(f"Cassandra VectorDB : Inserting Documents to the table {self.table_name}")
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        futures = []
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        for doc in documents:
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
            doc.embed(embedder=self.embedder)
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
            metadata = {key: str(value) for key, value in doc.meta_data.items()}
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
            futures.append(
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
                self.table.put_async(
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
                    row_id=doc.id,
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
                    vector=doc.embedding,
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
                    metadata=metadata or {},
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
                    body_blob=doc.content,
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
                    document_name=doc.name,
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
                )
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
            )
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):

dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        for f in futures:
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
            f.result()
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):

dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
    def upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        """Insert or update documents based on primary key."""
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        self.insert(documents, filters)
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):

dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
    def search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        """Keyword-based search on document metadata."""
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        logger.debug(f"Cassandra VectorDB : Performing Vector Search on {self.table_name} with query {query}")
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        return self.vector_search(query=query, limit=limit)
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):

dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
    def _search_to_documents(
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        self,
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        hits: Iterable[Dict[str, Any]],
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
    ) -> List[Document]:
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        return [self._row_to_document(row=hit) for hit in hits]
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):

dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
    def vector_search(self, query: str, limit: int = 5) -> List[Document]:
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        """Vector similarity search implementation."""
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        query_embedding = self.embedder.get_embedding(query)
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        hits = list(
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
            self.table.metric_ann_search(
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
                vector=query_embedding,
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
                n=limit,
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
                metric="cos",
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
            )
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        )
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        d = self._search_to_documents(hits)
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        return d
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):

dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
    def drop(self) -> None:
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        """Drop the vector table in Cassandra."""
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        logger.debug(f"Cassandra VectorDB : Dropping Table {self.table_name}")
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        drop_table_query = f"DROP TABLE IF EXISTS {self.keyspace}.{self.table_name}"
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        self.session.execute(drop_table_query)
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):

dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
    def exists(self) -> bool:
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        """Check if the table exists in Cassandra."""
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        check_table_query = """
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        SELECT * FROM system_schema.tables
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        WHERE keyspace_name = %s AND table_name = %s
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        """
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        result = self.session.execute(check_table_query, (self.keyspace, self.table_name))
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        return bool(result.one())
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):

dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
    def delete(self) -> bool:
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        """Delete all documents in the table."""
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        logger.debug(f"Cassandra VectorDB : Clearing the table {self.table_name}")
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        self.table.clear()
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        return True
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):

dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
    async def async_create(self) -> None:
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):

dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
    async def async_doc_exists(self, document: Document) -> bool:
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):

dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
    async def async_insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):

dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
    async def async_upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):

dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
    async def async_search(
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
    ) -> List[Document]:
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):

dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
    async def async_drop(self) -> None:
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):

dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
    async def async_exists(self) -> bool:
dentifier_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
f not identifier_pattern.match(self.table_name):
f not identifier_pattern.match(self.index_name):
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")
