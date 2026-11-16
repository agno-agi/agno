"""Shared SQLAlchemy implementation of the identity link tables.

An identity link ties an account on another service (a Slack member) to the AgentOS principal it
acts as. The sync and async SQLAlchemy backends expose these as ``BaseDb`` methods
(``*_identity_link*``) and delegate here, as the authorization tables do (``db/sql/authz.py``).

A link is made only by redeeming a one-time code. Redeeming deletes the code in the same
transaction that writes the link, so two redeemers of one code cannot both link.
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


def _code_values(provider: str, principal_id: str, code_hash: str, expires_at: int, now: int) -> Dict[str, Any]:
    return {
        "code_hash": code_hash,
        "provider": provider,
        "principal_id": principal_id,
        "expires_at": expires_at,
        "created_at": now,
    }


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


def create_code(
    engine: Engine, table: Any, provider: str, principal_id: str, code_hash: str, expires_at: int, now: int
) -> None:
    with engine.begin() as conn:
        # One live code per principal: a new code voids the earlier one, and expired codes are cleared
        conn.execute(delete(table).where(table.c.provider == provider, table.c.principal_id == principal_id))
        conn.execute(delete(table).where(table.c.expires_at <= now))
        _upsert(conn, table, _code_values(provider, principal_id, code_hash, expires_at, now), ["code_hash"], [])


def redeem_code(
    engine: Engine, codes: Any, links: Any, provider: str, code_hash: str, tenant: str, external_id: str, now: int
) -> Optional[str]:
    with engine.begin() as conn:
        row = (
            conn.execute(select(codes).where(codes.c.code_hash == code_hash, codes.c.provider == provider))
            .mappings()
            .first()
        )
        if row is None:
            return None
        # Spent even when expired; a concurrent redeemer that deleted it first wins
        if conn.execute(delete(codes).where(codes.c.code_hash == code_hash)).rowcount != 1:
            return None
        if row["expires_at"] <= now:
            return None
        principal_id = row["principal_id"]
        # One account per principal and tenant: linking again replaces the earlier account
        conn.execute(delete(links).where(*_link_filters(links, provider, principal_id=principal_id, tenant=tenant)))
        _upsert(
            conn,
            links,
            _link_values(provider, tenant, external_id, principal_id, now),
            ["provider", "tenant", "external_id"],
            ["principal_id", "created_at"],
        )
        return principal_id


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


async def acreate_code(
    engine: "AsyncEngine", table: Any, provider: str, principal_id: str, code_hash: str, expires_at: int, now: int
) -> None:
    async with engine.begin() as conn:
        await conn.execute(delete(table).where(table.c.provider == provider, table.c.principal_id == principal_id))
        await conn.execute(delete(table).where(table.c.expires_at <= now))
        await _aupsert(conn, table, _code_values(provider, principal_id, code_hash, expires_at, now), ["code_hash"], [])


async def aredeem_code(
    engine: "AsyncEngine",
    codes: Any,
    links: Any,
    provider: str,
    code_hash: str,
    tenant: str,
    external_id: str,
    now: int,
) -> Optional[str]:
    async with engine.begin() as conn:
        row = (
            (await conn.execute(select(codes).where(codes.c.code_hash == code_hash, codes.c.provider == provider)))
            .mappings()
            .first()
        )
        if row is None:
            return None
        if (await conn.execute(delete(codes).where(codes.c.code_hash == code_hash))).rowcount != 1:
            return None
        if row["expires_at"] <= now:
            return None
        principal_id = row["principal_id"]
        await conn.execute(
            delete(links).where(*_link_filters(links, provider, principal_id=principal_id, tenant=tenant))
        )
        await _aupsert(
            conn,
            links,
            _link_values(provider, tenant, external_id, principal_id, now),
            ["provider", "tenant", "external_id"],
            ["principal_id", "created_at"],
        )
        return principal_id


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
