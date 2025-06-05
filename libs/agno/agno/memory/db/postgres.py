from typing import List, Optional

try:
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.engine import Engine, create_engine
    from sqlalchemy.inspection import inspect
    from sqlalchemy.orm import scoped_session, sessionmaker
    from sqlalchemy.schema import Column, MetaData, Table
    from sqlalchemy.sql.expression import delete, select, text
    from sqlalchemy.types import DateTime, String
except ImportError:
    raise ImportError("`sqlalchemy` not installed.  Please install using `pip install sqlalchemy 'psycopg[binary]'`")

from agno.memory.db.base import MemoryDb
from agno.memory.row import MemoryRow
from agno.utils.log import log_debug, logger


class PgMemoryDb(MemoryDb):
    def __init__(
        self,
        table_name: str,
        schema: Optional[str] = "ai",
        db_url: Optional[str] = None,
        db_engine: Optional[Engine] = None,
    ):
        """
        This class provides a memory store backed by a postgres table.

        The following order is used to determine the database connection:
            1. Use the db_engine if provided
            2. Use the db_url to create the engine

        Args:
            table_name (str): The name of the table to store memory rows.
            schema (Optional[str]): The schema to store the table in. Defaults to "ai".
            db_url (Optional[str]): The database URL to connect to. Defaults to None.
            db_engine (Optional[Engine]): The database engine to use. Defaults to None.
        """
        _engine: Optional[Engine] = db_engine
        if _engine is None and db_url is not None:
            _engine = create_engine(db_url)

        if _engine is None:
            raise ValueError("Must provide either db_url or db_engine")

        self.table_name: str = table_name
        self.schema: Optional[str] = schema
        self.db_url: Optional[str] = db_url
        self.db_engine: Engine = _engine
        self.inspector = inspect(self.db_engine)
        self.metadata: MetaData = MetaData(schema=self.schema)
        self.Session: scoped_session = scoped_session(sessionmaker(bind=self.db_engine))
        self.table: Table = self.get_table()

    def get_table(self) -> Table:
        return Table(
            self.table_name,
            self.metadata,
            Column("id", String, primary_key=True),
            Column("user_id", String),
            Column("memory", postgresql.JSONB, server_default=text("'{}'::jsonb")),
            Column("created_at", DateTime(timezone=True), server_default=text("now()")),
            Column("updated_at", DateTime(timezone=True), onupdate=text("now()")),
            extend_existing=True,
        )

    def create(self) -> None:
        if not self.table_exists():
            try:
                with self.Session() as sess, sess.begin():
                    if self.schema is not None:
                        log_debug(f"Creating schema: {self.schema}")
                        sess.execute(text(f"CREATE SCHEMA IF NOT EXISTS {self.schema};"))
                log_debug(f"Creating table: {self.table_name}")
                self.table.create(self.db_engine, checkfirst=True)
            except Exception as e:
                logger.error(f"Error creating table '{self.table.fullname}': {e}")
                raise

    def memory_exists(self, memory: MemoryRow) -> bool:
        columns = [self.table.c.id]
        with self.Session() as sess, sess.begin():
            stmt = select(*columns).where(self.table.c.id == memory.id)
            result = sess.execute(stmt).first()
            return result is not None

    def read_memories(
        self, user_id: Optional[str] = None, limit: Optional[int] = None, sort: Optional[str] = None
    ) -> List[MemoryRow]:
        memories: List[MemoryRow] = []
        try:
            with self.Session() as sess, sess.begin():
                stmt = select(self.table)
                if user_id is not None:
                    stmt = stmt.where(self.table.c.user_id == user_id)
                if limit is not None:
                    stmt = stmt.limit(limit)

                if sort == "asc":
                    stmt = stmt.order_by(self.table.c.created_at.asc())
                else:
                    stmt = stmt.order_by(self.table.c.created_at.desc())

                rows = sess.execute(stmt).fetchall()
                for row in rows:
                    if row is not None:
                        memories.append(MemoryRow.model_validate(row))
        except Exception as e:
            log_debug(f"Exception reading from table: {e}")
            log_debug(f"Table does not exist: {self.table.name}")
            log_debug("Creating table for future transactions")
            self.create()
        return memories

    def upsert_memory(self, memory: MemoryRow, create_and_retry: bool = True) -> None:
        """Create a new memory if it does not exist, otherwise update the existing memory"""

        try:
            with self.Session() as sess, sess.begin():
                # Create an insert statement
                stmt = postgresql.insert(self.table).values(
                    id=memory.id,
                    user_id=memory.user_id,
                    memory=memory.memory,
                )

                # Define the upsert if the memory already exists
                # See: https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#postgresql-insert-on-conflict
                stmt = stmt.on_conflict_do_update(
                    index_elements=["id"],
                    set_=dict(
                        user_id=stmt.excluded.user_id,
                        memory=stmt.excluded.memory,
                    ),
                )

                sess.execute(stmt)
        except Exception as e:
            log_debug(f"Exception upserting into table: {e}")
            log_debug(f"Table does not exist: {self.table.name}")
            log_debug("Creating table for future transactions")
            self.create()
            if create_and_retry:
                return self.upsert_memory(memory, create_and_retry=False)
            return None

    def delete_memory(self, id: str) -> None:
        with self.Session() as sess, sess.begin():
            stmt = delete(self.table).where(self.table.c.id == id)
            sess.execute(stmt)

    def drop_table(self) -> None:
        if self.table_exists():
            log_debug(f"Deleting table: {self.table_name}")
            self.table.drop(self.db_engine)

    def table_exists(self) -> bool:
        log_debug(f"Checking if table exists: {self.table.name}")
        try:
            return inspect(self.db_engine).has_table(self.table.name, schema=self.schema)
        except Exception as e:
            logger.error(e)
            return False

    def clear(self) -> bool:
        with self.Session() as sess, sess.begin():
            stmt = delete(self.table)
            sess.execute(stmt)
            return True

    def __deepcopy__(self, memo):
        """
        Create a deep copy of the PgMemoryDb instance, handling unpickleable attributes.

        Args:
            memo (dict): A dictionary of objects already copied during the current copying pass.

        Returns:
            PgMemoryDb: A deep-copied instance of PgMemoryDb.
        """
        from copy import deepcopy

        # Create a new instance without calling __init__
        cls = self.__class__
        copied_obj = cls.__new__(cls)
        memo[id(self)] = copied_obj

        # Deep copy attributes
        for k, v in self.__dict__.items():
            if k in {"metadata", "table"}:
                continue
            # Reuse db_engine and Session without copying
            elif k in {"db_engine", "Session"}:
                setattr(copied_obj, k, v)
            else:
                setattr(copied_obj, k, deepcopy(v, memo))

        # Recreate metadata and table for the copied instance
        copied_obj.metadata = MetaData(schema=copied_obj.schema)
        copied_obj.table = copied_obj.get_table()

        return copied_obj
