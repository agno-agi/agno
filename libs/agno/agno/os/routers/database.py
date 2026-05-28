from typing import TYPE_CHECKING, Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)
from fastapi.responses import JSONResponse
from packaging import version

from agno.db.base import AsyncBaseDb
from agno.db.migrations.manager import MigrationManager
from agno.os.auth import get_authentication_dependency
from agno.os.schema import (
    BadRequestResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    UnauthenticatedResponse,
    ValidationErrorResponse,
)
from agno.os.settings import AgnoAPISettings
from agno.os.utils import (
    get_db,
)
from agno.remote.base import RemoteDb
from agno.utils.log import log_info

if TYPE_CHECKING:
    from agno.os.app import AgentOS


def get_database_router(
    os: "AgentOS",
    settings: AgnoAPISettings = AgnoAPISettings(),
) -> APIRouter:
    """Create the database router with comprehensive OpenAPI documentation."""
    router = APIRouter(
        dependencies=[Depends(get_authentication_dependency(settings))],
        responses={
            400: {"description": "Bad Request", "model": BadRequestResponse},
            401: {"description": "Unauthorized", "model": UnauthenticatedResponse},
            404: {"description": "Not Found", "model": NotFoundResponse},
            422: {"description": "Validation Error", "model": ValidationErrorResponse},
            500: {"description": "Internal Server Error", "model": InternalServerErrorResponse},
        },
    )

    async def _migrate_single_db(db, target_version: Optional[str] = None) -> None:
        """Migrate a single database."""
        if isinstance(db, RemoteDb):
            log_info("Skipping logs for remote DB")

        if target_version:
            # Use the session table as proxy for the database schema version
            if isinstance(db, AsyncBaseDb):
                current_version = await db.get_latest_schema_version(db.session_table_name)
            else:
                current_version = db.get_latest_schema_version(db.session_table_name)

            if version.parse(target_version) > version.parse(current_version):  # type: ignore
                await MigrationManager(db).up(target_version)  # type: ignore
            else:
                await MigrationManager(db).down(target_version)  # type: ignore
        else:
            # If the target version is not provided, migrate to the latest version
            await MigrationManager(db).up()  # type: ignore

    @router.post(
        "/databases/all/migrate",
        tags=["Database"],
        operation_id="migrate_all_databases",
        summary="Migrate All Databases",
        description=(
            "Migrate all database schemas to the given target version. "
            "If a target version is not provided, all databases will be migrated to the latest version."
        ),
        responses={
            200: {
                "description": "All databases migrated successfully",
                "content": {
                    "application/json": {
                        "example": {"message": "All databases migrated successfully to version 3.0.0"},
                    }
                },
            },
            500: {"description": "Failed to migrate databases", "model": InternalServerErrorResponse},
        },
    )
    async def migrate_all_databases(target_version: Optional[str] = None):
        """Migrate all databases."""
        all_dbs = {db.id: db for db_id, dbs in os.dbs.items() for db in dbs}
        failed_dbs: dict[str, str] = {}

        for db_id, db in all_dbs.items():
            try:
                await _migrate_single_db(db, target_version)
            except Exception as e:
                failed_dbs[db_id] = str(e)

        version_msg = f"version {target_version}" if target_version else "latest version"
        migrated_count = len(all_dbs) - len(failed_dbs)

        if failed_dbs:
            return JSONResponse(
                content={
                    "message": f"Migrated {migrated_count}/{len(all_dbs)} databases to {version_msg}",
                    "failed": failed_dbs,
                },
                status_code=207,  # Multi-Status
            )

        return JSONResponse(
            content={"message": f"All databases migrated successfully to {version_msg}"}, status_code=200
        )

    @router.post(
        "/databases/{db_id}/migrate",
        tags=["Database"],
        operation_id="migrate_database",
        summary="Migrate Database",
        description=(
            "Migrate the given database schema to the given target version. "
            "If a target version is not provided, the database will be migrated to the latest version."
        ),
        responses={
            200: {
                "description": "Database migrated successfully",
                "content": {
                    "application/json": {
                        "example": {"message": "Database migrated successfully to version 3.0.0"},
                    }
                },
            },
            404: {"description": "Database not found", "model": NotFoundResponse},
            500: {"description": "Failed to migrate database", "model": InternalServerErrorResponse},
        },
    )
    async def migrate_database(db_id: str, target_version: Optional[str] = None):
        db = await get_db(os.dbs, db_id)
        if not db:
            raise HTTPException(status_code=404, detail="Database not found")

        try:
            await _migrate_single_db(db, target_version)

            version_msg = f"version {target_version}" if target_version else "latest version"
            return JSONResponse(
                content={"message": f"Database migrated successfully to {version_msg}"}, status_code=200
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to migrate database: {str(e)}")

    return router
