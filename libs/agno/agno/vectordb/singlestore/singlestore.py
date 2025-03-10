import json
from hashlib import md5
from typing import Any, Dict, List, Optional

try:
    from sqlalchemy.dialects import mysql
    from sqlalchemy.engine import Engine, create_engine
    from sqlalchemy.inspection import inspect
    from sqlalchemy.orm import Session, sessionmaker
    from sqlalchemy.schema import Column, MetaData, Table
    from sqlalchemy.sql.expression import func, select, text
    from sqlalchemy.types import DateTime
except ImportError:
    raise ImportError("`sqlalchemy` not installed")

from agno.document import Document
from agno.embedder import Embedder
from agno.reranker.base import Reranker

# from agno.vectordb.singlestore.index import Ivfflat, HNSWFlat
from agno.utils.log import logger
from agno.vectordb.base import VectorDb
from agno.vectordb.distance import Distance


class SingleStore(VectorDb):
    def __init__(
        self,
        collection: str,
        schema: Optional[str] = "ai",
        db_url: Optional[str] = None,
        db_engine: Optional[Engine] = None,
        embedder: Optional[Embedder] = None,
        distance: Distance = Distance.cosine,
        reranker: Optional[Reranker] = None,
        # index: Optional[Union[Ivfflat, HNSW]] = HNSW(),
    ):
        _engine: Optional[Engine] = db_engine
        if _engine is None and db_url is not None:
            _engine = create_engine(db_url)

        if _engine is None:
            raise ValueError("Must provide either db_url or db_engine")

        self.collection: str = collection
        self.schema: Optional[str] = schema
        self.db_url: Optional[str] = db_url
        self.db_engine: Engine = _engine
        self.metadata: MetaData = MetaData(schema=self.schema)

        if embedder is None:
            from agno.embedder.openai import OpenAIEmbedder

            embedder = OpenAIEmbedder()
            logger.info("Embedder not provided, using OpenAIEmbedder as default.")
        self.embedder: Embedder = embedder
        self.dimensions: Optional[int] = self.embedder.dimensions

        self.distance: Distance = distance
        # self.index: Optional[Union[Ivfflat, HNSW]] = index
        self.Session: sessionmaker[Session] = sessionmaker(bind=self.db_engine)
        self.reranker: Optional[Reranker] = reranker
        self.table: Table = self.get_table()

    def get_table(self) -> Table:
        """
        Define the table structure.

        Returns:
            Table: SQLAlchemy Table object.
        """
        return Table(
            self.collection,
            self.metadata,
            Column("id", mysql.TEXT),
            Column("name", mysql.TEXT),
            Column("meta_data", mysql.TEXT),
            Column("content", mysql.TEXT),
            Column("embedding", mysql.TEXT),  # Placeholder for the vector column
            Column("usage", mysql.TEXT),
            Column("created_at", DateTime(timezone=True), server_default=text("now()")),
            Column("updated_at", DateTime(timezone=True), onupdate=text("now()")),
            Column("content_hash", mysql.TEXT),
            extend_existing=True,
        )

    def create(self) -> None:
        """
        Create the table if it does not exist.
        """
        if not self.table_exists():
            logger.info(f"Creating table: {self.collection}")
            with self.db_engine.connect() as connection:
                connection.execute(
                    text(f"""
                    CREATE TABLE IF NOT EXISTS {self.schema}.{self.collection} (
                        id TEXT,
                        name TEXT,
                        meta_data TEXT,
                        content TEXT,
                        embedding VECTOR({self.dimensions}) NOT NULL,
                        `usage` TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        content_hash TEXT
                    );
                    """)
                )
            # Call optimize to create indexes
            self.optimize()

    def table_exists(self) -> bool:
        """
        Check if the table exists.

        Returns:
            bool: True if the table exists, False otherwise.
        """
        logger.debug(f"Checking if table exists: {self.table.name}")
        try:
            return inspect(self.db_engine).has_table(self.table.name, schema=self.schema)
        except Exception as e:
            logger.error(e)
            return False

    def doc_exists(self, document: Document) -> bool:
        """
        Validating if the document exists or not

        Args:
            document (Document): Document to validate
        """
        columns = [self.table.c.name, self.table.c.content_hash]
        with self.Session.begin() as sess:
            cleaned_content = document.content.replace("\x00", "\ufffd")
            stmt = select(*columns).where(self.table.c.content_hash == md5(cleaned_content.encode()).hexdigest())
            result = sess.execute(stmt).first()
            return result is not None

    def name_exists(self, name: str) -> bool:
        """
        Validate if a row with this name exists or not

        Args:
            name (str): Name to check
        """
        with self.Session.begin() as sess:
            stmt = select(self.table.c.name).where(self.table.c.name == name)
            result = sess.execute(stmt).first()
            return result is not None

    def id_exists(self, id: str) -> bool:
        """
        Validate if a row with this id exists or not

        Args:
            id (str): Id to check
        """
        with self.Session.begin() as sess:
            stmt = select(self.table.c.id).where(self.table.c.id == id)
            result = sess.execute(stmt).first()
            return result is not None

    def insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None, batch_size: int = 10) -> None:
        """
        Insert documents into the table.

        Args:
            documents (List[Document]): List of documents to insert.
            filters (Optional[Dict[str, Any]]): Optional filters for the insert.
            batch_size (int): Number of documents to insert in each batch.
        """
        with self.Session.begin() as sess:
            counter = 0
            for document in documents:
                document.embed(embedder=self.embedder)
                cleaned_content = document.content.replace("\x00", "\ufffd")
                content_hash = md5(cleaned_content.encode()).hexdigest()
                _id = document.id or content_hash

                meta_data_json = json.dumps(document.meta_data)
                usage_json = json.dumps(document.usage)

                # Convert embedding list to SingleStore VECTOR format
                embeddings = f"[{','.join(map(str, document.embedding))}]" if document.embedding else None

                stmt = mysql.insert(self.table).values(
                    id=_id,
                    name=document.name,
                    meta_data=meta_data_json,
                    content=cleaned_content,
                    embedding=embeddings,
                    usage=usage_json,
                    content_hash=content_hash,
                )
                sess.execute(stmt)
                counter += 1
                logger.debug(f"Inserted document: {document.name} ({document.meta_data})")

            sess.commit()
            logger.debug(f"Committed {counter} documents")

    def upsert_available(self) -> bool:
        """Indicate that upsert functionality is available."""
        return True

    def upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None, batch_size: int = 20) -> None:
        """
        Upsert (insert or update) documents in the table.

        Args:
            documents (List[Document]): List of documents to upsert.
            filters (Optional[Dict[str, Any]]): Optional filters for the upsert.
            batch_size (int): Number of documents to upsert in each batch.
        """
        with self.Session.begin() as sess:
            counter = 0
            for document in documents:
                document.embed(embedder=self.embedder)
                cleaned_content = document.content.replace("\x00", "\ufffd")
                content_hash = md5(cleaned_content.encode()).hexdigest()
                _id = document.id or content_hash

                meta_data_json = json.dumps(document.meta_data)
                usage_json = json.dumps(document.usage)

                # Convert embedding list to SingleStore VECTOR format
                embeddings = f"[{','.join(map(str, document.embedding))}]" if document.embedding else None
                stmt = (
                    mysql.insert(self.table)
                    .values(
                        id=_id,
                        name=document.name,
                        meta_data=meta_data_json,
                        content=cleaned_content,
                        embedding=embeddings,
                        usage=usage_json,
                        content_hash=content_hash,
                    )
                    .on_duplicate_key_update(
                        name=document.name,
                        meta_data=meta_data_json,
                        content=cleaned_content,
                        embedding=embeddings,
                        usage=usage_json,
                        content_hash=content_hash,
                    )
                )
                sess.execute(stmt)
                counter += 1
                logger.debug(f"Upserted document: {document.name} ({document.meta_data})")

            sess.commit()
            logger.debug(f"Committed {counter} documents")

    def search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """
        Search for documents based on a query and optional filters.

        Args:
            query (str): The search query.
            limit (int): The maximum number of results to return.
            filters (Optional[Dict[str, Any]]): Optional filters for the search.

        Returns:
            List[Document]: List of documents that match the query.
        """
        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            logger.error(f"Error getting embedding for Query: {query}")
            return []

        columns = [
            self.table.c.name,
            self.table.c.meta_data,
            self.table.c.content,
            self.table.c.embedding,
            self.table.c.usage,
        ]

        stmt = select(*columns)

        if filters is not None:
            for key, value in filters.items():
                if hasattr(self.table.c, key):
                    stmt = stmt.where(getattr(self.table.c, key) == value)

        if self.distance == Distance.l2:
            stmt = stmt.order_by(self.table.c.embedding.max_inner_product(query_embedding))
        if self.distance == Distance.cosine:
            embeddings = json.dumps(query_embedding)
            dot_product_expr = func.dot_product(self.table.c.embedding, text(":embedding"))
            stmt = stmt.order_by(dot_product_expr.desc())
            stmt = stmt.params(embedding=embeddings)
            # stmt = stmt.order_by(self.table.c.embedding.cosine_distance(query_embedding))
        if self.distance == Distance.max_inner_product:
            stmt = stmt.order_by(self.table.c.embedding.max_inner_product(query_embedding))

        stmt = stmt.limit(limit=limit)
        logger.debug(f"Query: {stmt}")

        # Get neighbors
        # This will only work if embedding column is created with `vector` data type.
        with self.Session.begin() as sess:
            sess.execute(text("SET vector_type_project_format = JSON"))
            neighbors = sess.execute(stmt).fetchall() or []
            #         if self.index is not None:
            #             if isinstance(self.index, Ivfflat):
            #                 # Assuming 'nprobe' is a relevant parameter to be set for the session
            #                 # Update the session settings based on the Ivfflat index configuration
            #                 sess.execute(text(f"SET SESSION nprobe = {self.index.nprobe}"))
            #             elif isinstance(self.index, HNSWFlat):
            #                 # Assuming 'ef_search' is a relevant parameter to be set for the session
            #                 # Update the session settings based on the HNSW index configuration
            #                 sess.execute(text(f"SET SESSION ef_search = {self.index.ef_search}"))

        # Build search results
        search_results: List[Document] = []
        for neighbor in neighbors:
            meta_data_dict = json.loads(neighbor.meta_data) if neighbor.meta_data else {}
            usage_dict = json.loads(neighbor.usage) if neighbor.usage else {}

            # Convert SingleStore VECTOR type to list
            embedding_list = []
            if neighbor.embedding:
                try:
                    embedding_list = json.loads(neighbor.embedding)
                except Exception as e:
                    logger.error(f"Error extracting vector: {e}")
                    embedding_list = []

            search_results.append(
                Document(
                    name=neighbor.name,
                    meta_data=meta_data_dict,
                    content=neighbor.content,
                    embedder=self.embedder,
                    embedding=embedding_list,
                    usage=usage_dict,
                )
            )

        if self.reranker:
            search_results = self.reranker.rerank(query=query, documents=search_results)

        return search_results

    def drop(self) -> None:
        """
        Delete the table.
        """
        if self.table_exists():
            logger.debug(f"Deleting table: {self.collection}")
            self.table.drop(self.db_engine)

    def exists(self) -> bool:
        """
        Check if the table exists.

        Returns:
            bool: True if the table exists, False otherwise.
        """
        return self.table_exists()

    def get_count(self) -> int:
        """
        Get the count of rows in the table.

        Returns:
            int: The count of rows.
        """
        with self.Session.begin() as sess:
            stmt = select(func.count(self.table.c.name)).select_from(self.table)
            result = sess.execute(stmt).scalar()
            if result is not None:
                return int(result)
            return 0

    def optimize(self) -> None:
        pass

    def delete(self) -> bool:
        """
        Clear all rows from the table.

        Returns:
            bool: True if the table was cleared, False otherwise.
        """
        from sqlalchemy import delete

        with self.Session.begin() as sess:
            stmt = delete(self.table)
            sess.execute(stmt)
            return True

    async def async_create(self) -> None:
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")

    async def async_doc_exists(self, document: Document) -> bool:
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")

    async def async_insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")

    async def async_upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")

    async def async_drop(self) -> None:
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")

    async def async_exists(self) -> bool:
        raise NotImplementedError(f"Async not supported on {self.__class__.__name__}.")
