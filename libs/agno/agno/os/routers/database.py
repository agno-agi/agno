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
from agno.exceptions import AgnoError
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
    AgnoHTTPException,
    get_db,
)
from agno.remote.base import RemoteDb
from agno.utils.log import log_error, log_info

if TYPE_CHECKING:
    from agno.os.app import AgentOS


class MigrationInProgressError(RuntimeError):
    """Another process holds the migration lock of the database."""


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
        """Migrate a single local database.

        Remote databases are rejected: they belong to another AgentOS, which owns
        their schema and exposes its own migrate endpoints.
        """
        if isinstance(db, RemoteDb):
            raise ValueError(f"Database '{db.id}' is remote; run the migration on the AgentOS that owns it instead.")

        from agno.db.migrations import startup

        async with startup.migration_lock(db, startup.REQUEST_LOCK_WAIT_SECONDS) as held:
            if not held:
                raise MigrationInProgressError(
                    f"Another process is migrating database '{db.id}'. Try again when it has finished."
                )
            if target_version:
                # Use the session table as proxy for the database schema version. At that version
                # another table can still be behind it, and up() migrates only those.
                if isinstance(db, AsyncBaseDb):
                    current_version = await db.get_latest_schema_version(db.session_table_name)
                else:
                    current_version = db.get_latest_schema_version(db.session_table_name)

                if version.parse(target_version) >= version.parse(current_version):  # type: ignore
                    await MigrationManager(db).up(target_version)  # type: ignore
                else:
                    await MigrationManager(db).down(target_version)  # type: ignore
            else:
                # If the target version is not provided, migrate to the latest version
                await MigrationManager(db).up()  # type: ignore

    def _company_db():
        """The Company database when it is not one of the AgentOS databases."""
        company_db = getattr(os, "_company_db", None)
        registered = [db for dbs in os.dbs.values() for db in dbs]
        return None if company_db is None or any(db is company_db for db in registered) else company_db

    async def _start_company() -> None:
        """Start Company if the start could not, now that its database may be migrated.

        The answer of the migrate endpoint is about the migration. A Company that still cannot start
        is logged, as it is when AgentOS starts.
        """
        if getattr(os, "_company_start_pending", False):
            from agno.company.bootstrap import _start_company as start_company

            try:
                await start_company(os)
            except Exception as exc:
                log_error(f"Company did not start after the migration: {type(exc).__name__}: {exc}")

    @router.post(
        "/databases/all/migrate",
        tags=["Database"],
        operation_id="migrate_all_databases",
        summary="Migrate All Databases",
        description=(
            "Migrate all database schemas to the given target version. "
            "If a target version is not provided, all databases will be migrated to the latest version. "
            "A separate Company database is migrated too. If Company could not start because a database was not "
            "migrated, it is started afterwards, with no restart."
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
        """Migrate all local databases. Remote databases are skipped and listed in the response."""
        all_dbs = {db.id: db for db_id, dbs in os.dbs.items() for db in dbs}
        company_db = _company_db()
        if company_db is not None:
            # A separate database can have the id of a registered one. Both are migrated.
            name = company_db.id if company_db.id not in all_dbs else f"{company_db.id} (Company)"
            all_dbs[name] = company_db
        local_dbs = {db_id: db for db_id, db in all_dbs.items() if not isinstance(db, RemoteDb)}
        skipped_dbs = [db_id for db_id in all_dbs if db_id not in local_dbs]
        if skipped_dbs:
            log_info(f"Skipping migration for remote databases: {', '.join(skipped_dbs)}")
        failed_dbs: dict[str, str] = {}

        for db_id, db in local_dbs.items():
            try:
                await _migrate_single_db(db, target_version)
            except Exception as e:
                failed_dbs[db_id] = str(e)

        await os._finish_company_migration()
        await _start_company()
        version_msg = f"version {target_version}" if target_version else "latest version"
        migrated_count = len(local_dbs) - len(failed_dbs)

        if failed_dbs:
            content = {
                "message": f"Migrated {migrated_count}/{len(local_dbs)} databases to {version_msg}",
                "failed": failed_dbs,
            }
            if skipped_dbs:
                content["skipped"] = skipped_dbs
            return JSONResponse(content=content, status_code=207)  # Multi-Status

        content = {"message": f"All databases migrated successfully to {version_msg}"}
        if skipped_dbs:
            content["skipped"] = skipped_dbs
        return JSONResponse(content=content, status_code=200)

    @router.post(
        "/databases/{db_id}/migrate",
        tags=["Database"],
        operation_id="migrate_database",
        summary="Migrate Database",
        description=(
            "Migrate the given database schema to the given target version. "
            "If a target version is not provided, the database will be migrated to the latest version. "
            "The id of a separate Company database is accepted too. If Company could not start because a database "
            "was not migrated, it is started afterwards, with no restart."
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
            409: {"description": "Another process is migrating the database", "model": BadRequestResponse},
            500: {"description": "Failed to migrate database", "model": InternalServerErrorResponse},
        },
    )
    async def migrate_database(db_id: str, target_version: Optional[str] = None):
        company_db = _company_db()
        separate = company_db if company_db is not None and company_db.id == db_id else None
        db = separate if separate is not None and db_id not in os.dbs else await get_db(os.dbs, db_id)
        if not db:
            raise HTTPException(status_code=404, detail="Database not found")

        if isinstance(db, RemoteDb):
            raise HTTPException(
                status_code=400,
                detail=f"Database '{db_id}' is remote; run the migration on the AgentOS that owns it instead.",
            )

        try:
            await _migrate_single_db(db, target_version)
            if separate is not None and separate is not db:
                # The Company database has the id of a registered one. Both are migrated.
                await _migrate_single_db(separate, target_version)
            await os._finish_company_migration()
            await _start_company()

            version_msg = f"version {target_version}" if target_version else "latest version"
            return JSONResponse(
                content={"message": f"Database migrated successfully to {version_msg}"}, status_code=200
            )
        except HTTPException:
            raise
        except MigrationInProgressError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except AgnoError as e:
            raise AgnoHTTPException(e, detail=f"Failed to migrate database: {str(e)}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to migrate database: {str(e)}")

    return router
