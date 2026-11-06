"""Slack receipt and notification intent, separate from Company work records."""

import asyncio
import time
from typing import Any, Callable, Dict, Optional
from uuid import uuid4

from sqlalchemy import JSON, BigInteger, Column, MetaData, String, Table, select, text
from sqlalchemy.ext.asyncio import AsyncEngine


class _SlackStore:
    def __init__(self, db: Any, scope: str):
        self.engine = db.db_engine
        self.scope = scope
        schema = getattr(db, "db_schema", None) if self.engine.dialect.name == "postgresql" else None
        self.table = Table(
            str(db.session_table_name) + "_slack_receipts",
            MetaData(schema=schema),
            Column("id", String, primary_key=True),
            Column("scope", String, nullable=False, index=True),
            Column("session_id", String, nullable=False, index=True),
            Column("principal", String, nullable=False),
            Column("data", JSON, nullable=False),
            Column("next_at", BigInteger, nullable=False, index=True),
            Column("lease", String),
            Column("lease_until", BigInteger, nullable=False),
        )

    async def _call(self, operation: Callable) -> Any:
        if isinstance(self.engine, AsyncEngine):
            async with self.engine.begin() as conn:
                return await conn.run_sync(operation)

        def run():
            with self.engine.begin() as conn:
                return operation(conn)

        return await asyncio.to_thread(run)

    async def _initialize(self) -> None:
        def initialize(conn):
            if conn.dialect.name == "postgresql":
                conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": self.table.fullname})
            self.table.create(conn, checkfirst=True)

        await self._call(initialize)

    async def _receive(self, receipt_id: str, session_id: str, principal: str, data: Dict[str, Any]) -> Dict[str, Any]:
        def receive(conn):
            if conn.dialect.name == "postgresql":
                from sqlalchemy.dialects.postgresql import insert as pg_insert

                insert: Any = pg_insert
            else:
                from sqlalchemy.dialects.sqlite import insert as sqlite_insert

                insert = sqlite_insert
            conn.execute(
                insert(self.table)
                .values(
                    id=receipt_id,
                    scope=self.scope,
                    session_id=session_id,
                    principal=principal,
                    data=data,
                    next_at=0,
                    lease_until=0,
                )
                .on_conflict_do_nothing(index_elements=["id"])
            )
            return dict(
                conn.execute(select(self.table).where(self.table.c.id == receipt_id, self.table.c.scope == self.scope))
                .one()
                ._mapping
            )

        return await self._call(receive)

    async def _get(self, receipt_id: str) -> Optional[Dict[str, Any]]:
        def get(conn):
            row = conn.execute(
                select(self.table).where(self.table.c.id == receipt_id, self.table.c.scope == self.scope)
            ).first()
            return dict(row._mapping) if row else None

        return await self._call(get)

    async def _claim(self, receipt_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        now = int(time.time())
        lease = str(uuid4())

        def claim(conn):
            stmt = (
                select(self.table.c.id)
                .where(self.table.c.scope == self.scope, self.table.c.next_at <= now, self.table.c.lease_until <= now)
                .order_by(self.table.c.next_at, self.table.c.id)
                .limit(1)
            )
            if receipt_id is not None:
                stmt = stmt.where(self.table.c.id == receipt_id)
            if conn.dialect.name == "postgresql":
                stmt = stmt.with_for_update(skip_locked=True)
            key = conn.execute(stmt).scalar()
            if key is None:
                return None
            row = conn.execute(
                self.table.update()
                .where(self.table.c.id == key, self.table.c.lease_until <= now)
                .values(lease=lease, lease_until=now + 120)
                .returning(self.table)
            ).first()
            return dict(row._mapping) if row else None

        return await self._call(claim)

    async def _save(self, row: Dict[str, Any], *, release: bool = False, delay: int = 0) -> None:
        values: Dict[str, Any] = {"data": row["data"], "next_at": int(time.time()) + delay}
        if not release:
            values["lease_until"] = int(time.time()) + 120
        if release:
            values.update(lease=None, lease_until=0)

        def save(conn):
            result = conn.execute(
                self.table.update()
                .where(
                    self.table.c.id == row["id"], self.table.c.scope == self.scope, self.table.c.lease == row["lease"]
                )
                .values(**values)
            )
            if result.rowcount != 1:
                raise RuntimeError("Slack delivery lease was lost")

        await self._call(save)

    async def _thread_exists(self, channel: str, thread: str) -> bool:
        def exists(conn):
            return (
                conn.execute(
                    select(self.table.c.id)
                    .where(
                        self.table.c.scope == self.scope,
                        self.table.c.data["channel"].as_string() == channel,
                        self.table.c.data["thread"].as_string() == thread,
                    )
                    .limit(1)
                ).first()
                is not None
            )

        return await self._call(exists)

    async def _by_run(self, run_id: str, principal: str, channel: str, thread: str) -> Optional[Dict[str, Any]]:
        def get(conn):
            row = conn.execute(
                select(self.table)
                .where(
                    self.table.c.scope == self.scope,
                    self.table.c.principal == principal,
                    self.table.c.data["run_id"].as_string() == run_id,
                    self.table.c.data["channel"].as_string() == channel,
                    self.table.c.data["thread"].as_string() == thread,
                )
                .limit(1)
            ).first()
            return dict(row._mapping) if row else None

        return await self._call(get)
