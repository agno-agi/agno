import time
from abc import ABC, abstractmethod
from typing import List, Optional
from uuid import uuid4

from agno.tools.google.oauth.crypto import decrypt_credentials, encrypt_credentials
from agno.utils.log import log_debug, log_error

try:
    from google.oauth2.credentials import Credentials
except ImportError:
    raise ImportError("google-auth required: pip install google-auth")


class BaseGoogleTokenStore(ABC):
    """Per-user Google OAuth token storage with encryption at rest.

    Methods are sync because the authenticate decorator runs in sync context.
    The OAuth router (async) calls these from sync context too — SQLAlchemy
    sync engine handles the actual I/O.
    """

    def __init__(self, encryption_key: Optional[str] = None):
        # Passed through to crypto functions; falls back to GOOGLE_OAUTH_ENCRYPTION_KEY env var
        self.encryption_key = encryption_key

    @abstractmethod
    def get_token(self, team_id: str, user_id: str) -> Optional[Credentials]: ...

    @abstractmethod
    def save_token(self, team_id: str, user_id: str, creds: Credentials, scopes: List[str]) -> None: ...

    @abstractmethod
    def delete_token(self, team_id: str, user_id: str) -> None: ...

    def has_valid_token(self, team_id: str, user_id: str) -> bool:
        creds = self.get_token(team_id, user_id)
        if creds is None:
            return False
        return creds.valid or (creds.expired and creds.refresh_token is not None)


def _raise_auth_required(
    team_id: str,
    user_id: str,
    scopes: List[str],
    oauth_base_url: Optional[str] = None,
) -> None:
    """Raise StopAgentRun with structured OAuth metadata.

    Interfaces read additional_data to render an auth prompt (e.g. Connect button).
    """
    from agno.exceptions import StopAgentRun

    auth_url = f"{oauth_base_url}/google/auth/initiate?team_id={team_id}&user_id={user_id}" if oauth_base_url else None
    raise StopAgentRun(
        "Google authentication required",
        user_message="I need access to your Google account to help with this.",
        additional_data={
            "requirement_type": "oauth",
            "provider": "Google",
            "auth_url": auth_url,
            "scopes": scopes,
        },
    )


def load_user_credentials(
    store: BaseGoogleTokenStore,
    team_id: str,
    user_id: str,
    scopes: List[str],
    oauth_base_url: Optional[str] = None,
) -> Credentials:
    """Load and refresh per-user credentials from the token store.

    Shared by all Google toolkits to avoid duplicating the load → refresh → fallback logic.
    Raises StopAgentRun with OAuth metadata if no valid token exists or refresh fails.
    """
    from google.auth.transport.requests import Request

    creds = store.get_token(team_id, user_id)
    if creds is None:
        _raise_auth_required(team_id, user_id, scopes, oauth_base_url)

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            store.save_token(team_id, user_id, creds, scopes)
        except Exception:
            store.delete_token(team_id, user_id)
            _raise_auth_required(team_id, user_id, scopes, oauth_base_url)

    if not creds.valid:
        store.delete_token(team_id, user_id)
        _raise_auth_required(team_id, user_id, scopes, oauth_base_url)

    return creds


class PostgresGoogleTokenStore(BaseGoogleTokenStore):
    """Stores encrypted Google OAuth tokens in PostgreSQL.

    Auto-creates the token table on first use. Uses sync SQLAlchemy engine
    so it works from both sync (authenticate decorator) and async (OAuth router) contexts.
    """

    def __init__(
        self,
        db_url: str,
        table_name: str = "google_oauth_tokens",
        schema: str = "agno",
        encryption_key: Optional[str] = None,
    ):
        super().__init__(encryption_key=encryption_key)
        self.db_url = db_url
        self.table_name = table_name
        self.schema = schema
        self._engine = None
        self._table = None

    def _get_engine(self):
        if self._engine is None:
            try:
                from sqlalchemy import create_engine
            except ImportError:
                raise ImportError("sqlalchemy required: pip install sqlalchemy")

            self._engine = create_engine(self.db_url)
        return self._engine

    def _ensure_table(self):
        if self._table is not None:
            return self._table

        try:
            from sqlalchemy import BigInteger, Column, LargeBinary, MetaData, String, Table, Text, UniqueConstraint
            from sqlalchemy.sql.expression import text
        except ImportError:
            raise ImportError("sqlalchemy required: pip install sqlalchemy")

        engine = self._get_engine()
        metadata = MetaData(schema=self.schema)

        self._table = Table(
            self.table_name,
            metadata,
            Column("id", String, primary_key=True),
            Column("team_id", String, nullable=False, index=True),
            Column("user_id", String, nullable=False, index=True),
            Column("encrypted_token", LargeBinary, nullable=False),
            Column("scopes", Text, nullable=False),
            Column("created_at", BigInteger, nullable=False),
            Column("updated_at", BigInteger, nullable=True),
            UniqueConstraint("team_id", "user_id", name=f"uq_{self.table_name}_team_user"),
            schema=self.schema,
        )

        with engine.begin() as conn:
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {self.schema}"))

        metadata.create_all(engine)
        log_debug(f"Ensured table {self.schema}.{self.table_name} exists")
        return self._table

    def get_token(self, team_id: str, user_id: str) -> Optional[Credentials]:
        try:
            from sqlalchemy import and_, select
        except ImportError:
            raise ImportError("sqlalchemy required")

        table = self._ensure_table()
        engine = self._get_engine()

        with engine.connect() as conn:
            row = conn.execute(
                select(table.c.encrypted_token).where(and_(table.c.team_id == team_id, table.c.user_id == user_id))
            ).first()

        if row is None:
            return None

        creds = decrypt_credentials(row[0], self.encryption_key)
        if creds is None:
            log_error(f"Corrupt token for team={team_id} user={user_id}, deleting")
            self.delete_token(team_id, user_id)
        return creds

    def save_token(self, team_id: str, user_id: str, creds: Credentials, scopes: List[str]) -> None:
        try:
            from sqlalchemy import and_
        except ImportError:
            raise ImportError("sqlalchemy required")

        table = self._ensure_table()
        engine = self._get_engine()
        encrypted = encrypt_credentials(creds, self.encryption_key)
        now = int(time.time())

        with engine.begin() as conn:
            existing = conn.execute(
                table.select().where(and_(table.c.team_id == team_id, table.c.user_id == user_id))
            ).first()

            if existing:
                conn.execute(
                    table.update()
                    .where(and_(table.c.team_id == team_id, table.c.user_id == user_id))
                    .values(encrypted_token=encrypted, scopes=",".join(scopes), updated_at=now)
                )
            else:
                conn.execute(
                    table.insert().values(
                        id=uuid4().hex,
                        team_id=team_id,
                        user_id=user_id,
                        encrypted_token=encrypted,
                        scopes=",".join(scopes),
                        created_at=now,
                    )
                )
        log_debug(f"Saved Google token for team={team_id} user={user_id}")

    def delete_token(self, team_id: str, user_id: str) -> None:
        try:
            from sqlalchemy import and_
        except ImportError:
            raise ImportError("sqlalchemy required")

        table = self._ensure_table()
        engine = self._get_engine()

        with engine.begin() as conn:
            conn.execute(table.delete().where(and_(table.c.team_id == team_id, table.c.user_id == user_id)))
        log_debug(f"Deleted Google token for team={team_id} user={user_id}")


class SqliteGoogleTokenStore(BaseGoogleTokenStore):
    """Stores encrypted Google OAuth tokens in SQLite.

    Good for local dev and single-instance deployments. For Railway/multi-instance,
    use PostgresGoogleTokenStore instead.
    """

    def __init__(
        self,
        db_path: str = "google_oauth_tokens.db",
        table_name: str = "google_oauth_tokens",
        encryption_key: Optional[str] = None,
    ):
        super().__init__(encryption_key=encryption_key)
        self.db_path = db_path
        self.table_name = table_name
        self._engine = None
        self._table = None

    def _get_engine(self):
        if self._engine is None:
            try:
                from sqlalchemy import create_engine
            except ImportError:
                raise ImportError("sqlalchemy required: pip install sqlalchemy")

            self._engine = create_engine(f"sqlite:///{self.db_path}")
        return self._engine

    def _ensure_table(self):
        if self._table is not None:
            return self._table

        try:
            from sqlalchemy import BigInteger, Column, LargeBinary, MetaData, String, Table, Text, UniqueConstraint
        except ImportError:
            raise ImportError("sqlalchemy required: pip install sqlalchemy")

        engine = self._get_engine()
        metadata = MetaData()

        self._table = Table(
            self.table_name,
            metadata,
            Column("id", String, primary_key=True),
            Column("team_id", String, nullable=False),
            Column("user_id", String, nullable=False),
            Column("encrypted_token", LargeBinary, nullable=False),
            Column("scopes", Text, nullable=False),
            Column("created_at", BigInteger, nullable=False),
            Column("updated_at", BigInteger, nullable=True),
            UniqueConstraint("team_id", "user_id", name=f"uq_{self.table_name}_team_user"),
        )

        metadata.create_all(engine)
        log_debug(f"Ensured table {self.table_name} exists")
        return self._table

    def get_token(self, team_id: str, user_id: str) -> Optional[Credentials]:
        try:
            from sqlalchemy import and_, select
        except ImportError:
            raise ImportError("sqlalchemy required")

        table = self._ensure_table()
        engine = self._get_engine()

        with engine.connect() as conn:
            row = conn.execute(
                select(table.c.encrypted_token).where(and_(table.c.team_id == team_id, table.c.user_id == user_id))
            ).first()

        if row is None:
            return None

        creds = decrypt_credentials(row[0], self.encryption_key)
        if creds is None:
            log_error(f"Corrupt token for team={team_id} user={user_id}, deleting")
            self.delete_token(team_id, user_id)
        return creds

    def save_token(self, team_id: str, user_id: str, creds: Credentials, scopes: List[str]) -> None:
        try:
            from sqlalchemy import and_
        except ImportError:
            raise ImportError("sqlalchemy required")

        table = self._ensure_table()
        engine = self._get_engine()
        encrypted = encrypt_credentials(creds, self.encryption_key)
        now = int(time.time())

        with engine.begin() as conn:
            existing = conn.execute(
                table.select().where(and_(table.c.team_id == team_id, table.c.user_id == user_id))
            ).first()

            if existing:
                conn.execute(
                    table.update()
                    .where(and_(table.c.team_id == team_id, table.c.user_id == user_id))
                    .values(encrypted_token=encrypted, scopes=",".join(scopes), updated_at=now)
                )
            else:
                conn.execute(
                    table.insert().values(
                        id=uuid4().hex,
                        team_id=team_id,
                        user_id=user_id,
                        encrypted_token=encrypted,
                        scopes=",".join(scopes),
                        created_at=now,
                    )
                )
        log_debug(f"Saved Google token for team={team_id} user={user_id}")

    def delete_token(self, team_id: str, user_id: str) -> None:
        try:
            from sqlalchemy import and_
        except ImportError:
            raise ImportError("sqlalchemy required")

        table = self._ensure_table()
        engine = self._get_engine()

        with engine.begin() as conn:
            conn.execute(table.delete().where(and_(table.c.team_id == team_id, table.c.user_id == user_id)))
        log_debug(f"Deleted Google token for team={team_id} user={user_id}")
