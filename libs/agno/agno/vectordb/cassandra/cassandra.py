import asyncio
from typing import Any, Dict, Iterable, List, Optional

from agno.document import Document
from agno.embedder import Embedder
from agno.utils.log import log_debug, log_info
from agno.vectordb.base import VectorDb
from agno.vectordb.cassandra.index import AgnoMetadataVectorCassandraTable


class Cassandra(VectorDb):
    def __init__(
        self,
        table_name: str,
        keyspace: str,
        embedder: Optional[Embedder] = None,
        session=None,
    ) -> None:
        if not table_name:
            raise ValueError("Table name must be provided.")

        if not session:
            raise ValueError("Session is not provided")

        if not keyspace:
            raise ValueError("Keyspace must be provided")

        if embedder is None:
            from agno.embedder.openai import OpenAIEmbedder

            embedder = OpenAIEmbedder()
            log_info("Embedder not provided, using OpenAIEmbedder as default.")
        self.table_name: str = table_name
        self.embedder: Embedder = embedder
        self.session = session
        self.keyspace: str = keyspace
        self.initialize_table()

    def initialize_table(self):
        self.table = AgnoMetadataVectorCassandraTable(
            session=self.session,
            keyspace=self.keyspace,
            vector_dimension=1024,
            table=self.table_name,
            primary_key_type="TEXT",
        )

    def create(self) -> None:
        """Create the table in Cassandra for storing vectors and metadata."""
        if not self.exists():
            log_debug(f"Cassandra VectorDB : Creating table {self.table_name}")
            self.initialize_table()

    async def async_create(self) -> None:
        """Create the table asynchronously by running in a thread."""
        await asyncio.to_thread(self.create)

    def _row_to_document(self, row: Dict[str, Any]) -> Document:
        return Document(
            id=row["row_id"],
            content=row["body_blob"],
            meta_data=row["metadata"],
            embedding=row["vector"],
            name=row["document_name"],
        )

    def doc_exists(self, document: Document) -> bool:
        """Check if a document exists by ID."""
        query = f"SELECT COUNT(*) FROM {self.keyspace}.{self.table_name} WHERE row_id = %s"
        result = self.session.execute(query, (document.id,))
        return result.one()[0] > 0

    async def async_doc_exists(self, document: Document) -> bool:
        """Check if a document exists asynchronously."""
        return await asyncio.to_thread(self.doc_exists, document)

    def name_exists(self, name: str) -> bool:
        """Check if a document exists by name."""
        query = f"SELECT COUNT(*) FROM {self.keyspace}.{self.table_name} WHERE document_name = %s ALLOW FILTERING"
        result = self.session.execute(query, (name,))
        return result.one()[0] > 0

    async def async_name_exists(self, name: str) -> bool:
        """Check if a document with given name exists asynchronously."""
        return await asyncio.to_thread(self.name_exists, name)

    def id_exists(self, id: str) -> bool:
        """Check if a document exists by ID."""
        query = f"SELECT COUNT(*) FROM {self.keyspace}.{self.table_name} WHERE row_id = %s ALLOW FILTERING"
        result = self.session.execute(query, (id,))
        return result.one()[0] > 0

    def insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        log_debug(f"Cassandra VectorDB : Inserting Documents to the table {self.table_name}")
        futures = []
        for doc in documents:
            doc.embed(embedder=self.embedder)
            metadata = {key: str(value) for key, value in doc.meta_data.items()}
            futures.append(
                self.table.put_async(
                    row_id=doc.id,
                    vector=doc.embedding,
                    metadata=metadata or {},
                    body_blob=doc.content,
                    document_name=doc.name,
                )
            )

        for f in futures:
            f.result()

    async def async_insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert documents asynchronously by running in a thread."""
        await asyncio.to_thread(self.insert, documents, filters)

    def upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert or update documents based on primary key."""
        self.insert(documents, filters)

    async def async_upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Upsert documents asynchronously by running in a thread."""
        await asyncio.to_thread(self.upsert, documents, filters)

    def search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """Keyword-based search on document metadata."""
        log_debug(f"Cassandra VectorDB : Performing Vector Search on {self.table_name} with query {query}")
        return self.vector_search(query=query, limit=limit)

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """Search asynchronously by running in a thread."""
        return await asyncio.to_thread(self.search, query, limit, filters)

    def _search_to_documents(
        self,
        hits: Iterable[Dict[str, Any]],
    ) -> List[Document]:
        return [self._row_to_document(row=hit) for hit in hits]

    def vector_search(self, query: str, limit: int = 5) -> List[Document]:
        """Vector similarity search implementation."""
        query_embedding = self.embedder.get_embedding(query)
        hits = list(
            self.table.metric_ann_search(
                vector=query_embedding,
                n=limit,
                metric="cos",
            )
        )
        d = self._search_to_documents(hits)
        return d

    def drop(self) -> None:
        """Drop the vector table in Cassandra."""
        log_debug(f"Cassandra VectorDB : Dropping Table {self.table_name}")
        drop_table_query = f"DROP TABLE IF EXISTS {self.keyspace}.{self.table_name}"
        self.session.execute(drop_table_query)

    async def async_drop(self) -> None:
        """Drop the table asynchronously by running in a thread."""
        await asyncio.to_thread(self.drop)

    def exists(self) -> bool:
        """Check if the table exists in Cassandra."""
        check_table_query = """
        SELECT * FROM system_schema.tables
        WHERE keyspace_name = %s AND table_name = %s
        """
        result = self.session.execute(check_table_query, (self.keyspace, self.table_name))
        return bool(result.one())

    async def async_exists(self) -> bool:
        """Check if table exists asynchronously by running in a thread."""
        return await asyncio.to_thread(self.exists)

    def delete(self) -> bool:
        """Delete all documents in the table."""
        log_debug(f"Cassandra VectorDB : Clearing the table {self.table_name}")
        self.table.clear()
        return True
