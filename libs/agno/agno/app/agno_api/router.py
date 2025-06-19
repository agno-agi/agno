from typing import Optional

from fastapi import APIRouter, HTTPException


def get_base_async_router(
    active_app_id: Optional[str] = None,
) -> APIRouter:
    router = APIRouter(tags=["Status"])

    @router.get("/status")
    async def status(app_id: Optional[str] = None):
        if app_id is None:
            return {"status": "available"}
        else:
            if active_app_id == app_id:
                return {"status": "available"}
            else:
                raise HTTPException(status_code=404, detail="App not available")

    return router


def get_base_sync_router(
    active_app_id: Optional[str] = None,
) -> APIRouter:
    router = APIRouter(tags=["Status"])

    @router.get("/status")
    def status(app_id: Optional[str] = None):
        if app_id is None:
            return {"status": "available"}
        else:
            if active_app_id == app_id:
                return {"status": "available"}
            else:
                raise HTTPException(status_code=404, detail="App not available")

    return router
