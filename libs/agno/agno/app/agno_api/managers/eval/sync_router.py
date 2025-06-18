from fastapi import APIRouter

from agno.db.base import BaseDb


def attach_sync_routes(router: APIRouter, db: BaseDb) -> APIRouter:
    return router
