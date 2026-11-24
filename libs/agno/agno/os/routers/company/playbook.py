"""Company wiki and learning-decision routes, usable without a model."""

import asyncio
from dataclasses import asdict
from typing import Any, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from agno.company.manager import AsyncCompanyManager, CompanyManager
from agno.db.base import AsyncBaseDb, BaseDb
from agno.fs.errors import InvalidPathError, QuotaExceededError, VersionConflictError
from agno.os.auth import get_authentication_dependency
from agno.os.middleware.user_scope import get_scoped_user_id, resolve_run_user_id
from agno.os.routers.company.schema import (
    DecisionCreate,
    DecisionResponse,
    WikiPageResponse,
    WikiReadResponse,
    WikiWrite,
)
from agno.os.schema import PaginatedResponse, PaginationInfo
from agno.os.settings import AgnoAPISettings


def get_playbook_router(db: Optional[Union[BaseDb, AsyncBaseDb]], settings: AgnoAPISettings) -> APIRouter:
    """Mount the existing wiki and learning domains under Company."""
    router = APIRouter(prefix="/company", tags=["Company playbook"], dependencies=[Depends(get_scoped_user_id)])
    auth = get_authentication_dependency(settings)
    manager = AsyncCompanyManager(db) if isinstance(db, AsyncBaseDb) else CompanyManager(db) if db else None

    async def call(method: str, *args: Any, **kwargs: Any):
        if manager is None:
            raise HTTPException(503, "Company requires a database")
        try:
            fn = getattr(manager, method)
            return (
                await fn(*args, **kwargs)
                if isinstance(manager, AsyncCompanyManager)
                else await asyncio.to_thread(fn, *args, **kwargs)
            )
        except NotImplementedError:
            raise HTTPException(503, "Company playbook is not supported by the configured database")
        except PermissionError as exc:
            raise HTTPException(403, str(exc))
        except LookupError as exc:
            raise HTTPException(404, str(exc))
        except VersionConflictError as exc:
            raise HTTPException(409, str(exc))
        except (ValueError, InvalidPathError, QuotaExceededError) as exc:
            raise HTTPException(422, str(exc))

    def paged(result, limit, page):
        rows, total = result
        return PaginatedResponse(
            data=[asdict(row) for row in rows],
            meta=PaginationInfo(page=page, limit=limit, total_count=total, total_pages=(total + limit - 1) // limit),
        )

    @router.get("/products/{product_id}/wiki", response_model=PaginatedResponse[WikiPageResponse])
    async def list_product_wiki(
        product_id: str,
        limit: int = Query(20, ge=1, le=1000),
        page: int = Query(1, ge=1),
        _: bool = Depends(auth),
    ):
        return paged(await call("list_wiki", product_id, limit, page), limit, page)

    @router.get("/products/{product_id}/wiki/{path:path}", response_model=WikiReadResponse)
    async def read_product_wiki(path: str, product_id: str, _: bool = Depends(auth)):
        return asdict(await call("read_wiki", product_id, path))

    @router.put("/products/{product_id}/wiki/{path:path}", response_model=WikiPageResponse)
    async def write_product_wiki(path: str, body: WikiWrite, product_id: str, _: bool = Depends(auth)):
        return asdict(
            await call(
                "write_wiki",
                product_id=product_id,
                path=path,
                content=body.content,
                expected_version=body.expected_version,
            )
        )

    @router.get("/wiki", response_model=PaginatedResponse[WikiPageResponse])
    async def list_company_wiki(
        limit: int = Query(20, ge=1, le=1000),
        page: int = Query(1, ge=1),
        _: bool = Depends(auth),
    ):
        return paged(await call("list_wiki", None, limit, page), limit, page)

    @router.get("/wiki/{path:path}", response_model=WikiReadResponse)
    async def read_company_wiki(path: str, _: bool = Depends(auth)):
        return asdict(await call("read_wiki", None, path))

    @router.put("/wiki/{path:path}", response_model=WikiPageResponse)
    async def write_company_wiki(path: str, body: WikiWrite, _: bool = Depends(auth)):
        return asdict(
            await call(
                "write_wiki",
                product_id=None,
                path=path,
                content=body.content,
                expected_version=body.expected_version,
            )
        )

    @router.get("/decisions", response_model=PaginatedResponse[DecisionResponse])
    async def list_decisions(
        query: Optional[str] = None,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        days: Optional[int] = Query(None, ge=1),
        limit: int = Query(20, ge=1, le=1000),
        page: int = Query(1, ge=1),
        _: bool = Depends(auth),
    ):
        return paged(await call("list_decisions", query, agent_id, session_id, days, limit, page), limit, page)

    @router.post("/decisions", status_code=201, response_model=DecisionResponse)
    async def create_decision(body: DecisionCreate, request: Request, _: bool = Depends(auth)):
        return asdict(await call("log_decision", **body.model_dump(), user_id=resolve_run_user_id(request)))

    return router
