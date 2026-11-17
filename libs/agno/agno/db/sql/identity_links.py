"""Shared SQLAlchemy implementation of the identity link tables.

An identity link ties an account on another service (a Slack member) to the AgentOS principal it
acts as. The sync and async SQLAlchemy backends expose these as ``BaseDb`` methods
(``*_identity_link*``) and delegate here, as the authorization tables do (``db/sql/authz.py``).

A Slack member is linked to the user whose ID is their confirmed email (see
agno.os.interfaces.slack.links); each member has at most one link per workspace.
"""

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from sqlalchemy import delete, select
from sqlalchemy.engine import Engine

from agno.db.sql.authz import _aupsert, _upsert

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine


def _link_filters(
    table: Any,
    provider: str,
    principal_id: Optional[str] = None,
    tenant: Optional[str] = None,
    external_id: Optional[str] = None,
) -> list:
    filters = [table.c.provider == provider]
    if principal_id is not None:
        filters.append(table.c.principal_id == principal_id)
    if tenant is not None:
        filters.append(table.c.tenant == tenant)
    if external_id is not None:
        filters.append(table.c.external_id == external_id)
    return filters


def _link_values(provider: str, tenant: str, external_id: str, principal_id: str, now: int) -> Dict[str, Any]:
    return {
        "provider": provider,
        "tenant": tenant,
        "external_id": external_id,
        "principal_id": principal_id,
        "created_at": now,
    }


def _link_row(row: Any) -> Dict[str, Any]:
    return {
        "provider": row["provider"],
        "tenant": row["tenant"],
        "external_id": row["external_id"],
        "principal_id": row["principal_id"],
        "created_at": row["created_at"],
    }


def set_link(
    engine: Engine, table: Any, provider: str, tenant: str, external_id: str, principal_id: str, now: int
) -> None:
    with engine.begin() as conn:
        _upsert(
            conn,
            table,
            _link_values(provider, tenant, external_id, principal_id, now),
            ["provider", "tenant", "external_id"],
            ["principal_id", "created_at"],
        )


def get_link(engine: Engine, table: Any, provider: str, tenant: str, external_id: str) -> Optional[str]:
    with engine.connect() as conn:
        return conn.execute(
            select(table.c.principal_id).where(*_link_filters(table, provider, tenant=tenant, external_id=external_id))
        ).scalar()


def list_links(
    engine: Engine, table: Any, provider: str, principal_id: Optional[str] = None, external_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            select(table)
            .where(*_link_filters(table, provider, principal_id=principal_id, external_id=external_id))
            .order_by(table.c.created_at)
        ).mappings()
        return [_link_row(row) for row in rows]


def delete_links(
    engine: Engine,
    table: Any,
    provider: str,
    principal_id: Optional[str] = None,
    tenant: Optional[str] = None,
    external_id: Optional[str] = None,
) -> int:
    with engine.begin() as conn:
        return conn.execute(
            delete(table).where(*_link_filters(table, provider, principal_id, tenant, external_id))
        ).rowcount


# Async twins: the same statements over an AsyncEngine.


async def aset_link(
    engine: "AsyncEngine", table: Any, provider: str, tenant: str, external_id: str, principal_id: str, now: int
) -> None:
    async with engine.begin() as conn:
        await _aupsert(
            conn,
            table,
            _link_values(provider, tenant, external_id, principal_id, now),
            ["provider", "tenant", "external_id"],
            ["principal_id", "created_at"],
        )


async def aget_link(engine: "AsyncEngine", table: Any, provider: str, tenant: str, external_id: str) -> Optional[str]:
    async with engine.connect() as conn:
        return (
            await conn.execute(
                select(table.c.principal_id).where(
                    *_link_filters(table, provider, tenant=tenant, external_id=external_id)
                )
            )
        ).scalar()


async def alist_links(
    engine: "AsyncEngine",
    table: Any,
    provider: str,
    principal_id: Optional[str] = None,
    external_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                select(table)
                .where(*_link_filters(table, provider, principal_id=principal_id, external_id=external_id))
                .order_by(table.c.created_at)
            )
        ).mappings()
        return [_link_row(row) for row in rows]


async def adelete_links(
    engine: "AsyncEngine",
    table: Any,
    provider: str,
    principal_id: Optional[str] = None,
    tenant: Optional[str] = None,
    external_id: Optional[str] = None,
) -> int:
    async with engine.begin() as conn:
        result = await conn.execute(
            delete(table).where(*_link_filters(table, provider, principal_id, tenant, external_id))
        )
        return result.rowcount
