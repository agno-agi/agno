from pathlib import Path
from typing import List, Optional

try:
    from sqlalchemy import (
        Column,
        DateTime,
        Engine,
        MetaData,
        String,
        Table,
        create_engine,
        delete,
        inspect,
        select,
        text,
    )
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.orm import scoped_session, sessionmaker
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it with `pip install sqlalchemy`")

from agno.memory.db import MemoryDb
from agno.memory.row import MemoryRow
from agno.utils.log import logger


class SqliteMemoryDb(MemoryDb):
    def __init__(
        self,
        table_name: str = "memory",
        db_url: Optional[str] = None,
        db_file: Optional[str] = None,
        db_engine: Optional[Engine] = None,
    ):
        """
        This class provides a memory store backed by a SQLite table.

        The following order is used to determine the database connection:
            1. Use the db_engine if provided
            2. Use the db_url
            3. Use the db_file
            4. Create a new in-memory database

        Args:
            table_name: The name of the table to store Agent sessions.
            db_url: The database URL to connect to.
            db_file: The database file to connect to.
            db_engine: The database engine to use.
        """
        _engine: Optional[Engine] = db_engine
        if _engine is None and db_url is not None:
            _engine = create_engine(db_url)
        elif _engine is None and db_file is not None:
            # Use the db_file to create the engine
            db_path = Path(db_file).resolve()
            # Ensure the directory exists
            db_path.parent.mkdir(parents=True, exist_ok=True)
            _engine = create_engine(f"sqlite:///{db_path}")
        else:
            _engine = create_engine("sqlite://")

        if _engine is None:
            raise ValueError("Must provide either db_url, db_file or db_engine")

        # Database attributes
        self.table_name: str = table_name
        self.db_url: Optional[str] = db_url
        self.db_engine: Engine = _engine
        self.metadata: MetaData = MetaData()
        self.inspector = inspect(self.db_engine)

        # Database session
        self.Session = scoped_session(sessionmaker(bind=self.db_engine))
        # Database table for memories
        self.table: Table = self.get_table()

    def get_table(self) -> Table:
        return Table(
            self.table_name,
            self.metadata,
            Column("id", String, primary_key=True),
            Column("user_id", String),
            Column("memory", String),
            Column("created_at", DateTime, server_default=text("CURRENT_TIMESTAMP")),
            Column(
                "updated_at", DateTime, server_default=text("CURRENT_TIMESTAMP"), onupdate=text("CURRENT_TIMESTAMP")
            ),
            extend_existing=True,
        )

    def create(self) -> None:
        if not self.table_exists():
            try:
                logger.debug(f"Creating table: {self.table_name}")
                self.table.create(self.db_engine, checkfirst=True)
            except Exception as e:
                logger.error(f"Error creating table '{self.table_name}': {e}")
                raise

    def memory_exists(self, memory: MemoryRow) -> bool:
        with self.Session() as session:
            stmt = select(self.table.c.id).where(self.table.c.id == memory.id)
            result = session.execute(stmt).first()
            return result is not None

    def read_memories(
        self, user_id: Optional[str] = None, limit: Optional[int] = None, sort: Optional[str] = None
    ) -> List[MemoryRow]:
        memories: List[MemoryRow] = []
        try:
            with self.Session() as session:
                stmt = select(self.table)
                if user_id is not None:
                    stmt = stmt.where(self.table.c.user_id == user_id)

                if sort == "asc":
                    stmt = stmt.order_by(self.table.c.created_at.asc())
                else:
                    stmt = stmt.order_by(self.table.c.created_at.desc())

                if limit is not None:
                    stmt = stmt.limit(limit)

                result = session.execute(stmt)
                for row in result:
                    memories.append(MemoryRow(id=row.id, user_id=row.user_id, memory=eval(row.memory)))
        except SQLAlchemyError as e:
            logger.debug(f"Exception reading from table: {e}")
            logger.debug(f"Table does not exist: {self.table_name}")
            logger.debug("Creating table for future transactions")
            self.create()
        return memories

    def upsert_memory(self, memory: MemoryRow, create_and_retry: bool = True) -> None:
        try:
            with self.Session() as session:
                # Check if the memory already exists
                existing = session.execute(select(self.table).where(self.table.c.id == memory.id)).first()

                if existing:
                    # Update existing memory
                    stmt = (
                        self.table.update()
                        .where(self.table.c.id == memory.id)
                        .values(user_id=memory.user_id, memory=str(memory.memory), updated_at=text("CURRENT_TIMESTAMP"))
                    )
                else:
                    # Insert new memory
                    stmt = self.table.insert().values(id=memory.id, user_id=memory.user_id, memory=str(memory.memory))  # type: ignore

                session.execute(stmt)
                session.commit()
        except SQLAlchemyError as e:
            logger.error(f"Exception upserting into table: {e}")
            if not self.table_exists():
                logger.info(f"Table does not exist: {self.table_name}")
                logger.info("Creating table for future transactions")
                self.create()
                if create_and_retry:
                    return self.upsert_memory(memory, create_and_retry=False)
            else:
                raise

    def delete_memory(self, id: str) -> None:
        with self.Session() as session:
            stmt = delete(self.table).where(self.table.c.id == id)
            session.execute(stmt)
            session.commit()

    def drop_table(self) -> None:
        if self.table_exists():
            logger.debug(f"Deleting table: {self.table_name}")
            self.table.drop(self.db_engine)

    def table_exists(self) -> bool:
        logger.debug(f"Checking if table exists: {self.table.name}")
        try:
            return self.inspector.has_table(self.table.name)
        except Exception as e:
            logger.error(e)
            return False

    def clear(self) -> bool:
        with self.Session() as session:
            stmt = delete(self.table)
            session.execute(stmt)
            session.commit()
        return True

    def __del__(self):
        # self.Session.remove()
        pass
