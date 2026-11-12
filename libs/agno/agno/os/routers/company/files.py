"""Read-only routes over the Company file tree: a Task's files and the shared notes."""

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query

from agno.company.execution import _call
from agno.company.files import LIST_ENTRIES, CompanyFiles
from agno.fs.errors import InvalidPathError
from agno.os.auth import get_authentication_dependency
from agno.os.middleware.user_scope import get_scoped_user_id
from agno.os.routers.company.schema import CompanyFileReadResponse, WikiPageResponse
from agno.os.schema import PaginatedResponse, PaginationInfo


def get_company_files_router(agent_os: Any) -> APIRouter:
    """Build the file routes. tasks/ is in the Company database and notes/ in the AgentOS database."""
    router = APIRouter(prefix="/company", tags=["Company files"], dependencies=[Depends(get_scoped_user_id)])
    auth = get_authentication_dependency(agent_os.settings)
    db = agent_os._company_db
    files = CompanyFiles(db, notes_db=agent_os.db)

    async def tree(method: str, *args: Any) -> Dict[str, Any]:
        try:
            return await getattr(files, method)(*args)
        except NotImplementedError:
            raise HTTPException(503, "Company files are not supported by the configured database")
        except (ValueError, InvalidPathError) as exc:
            raise HTTPException(422, str(exc))

    async def task_folder(task_id: str) -> str:
        """The folder of a Task the Task route would return. Any other Task is not found."""
        if db is None:
            raise HTTPException(503, "Company requires a database")
        try:
            task = await _call(db, "get_task", task_id)
        except NotImplementedError:
            raise HTTPException(503, "Company tasks not supported by the configured database")
        if task is None:
            raise HTTPException(404, "Task not found")
        return f"tasks/{task['id']}"

    def notes_folder() -> str:
        if agent_os.db is None:
            raise HTTPException(503, "Company notes require the AgentOS database")
        return "notes"

    def named(folder: str, entry: Dict[str, Any]) -> Dict[str, Any]:
        """A file's details with its path inside the folder, which is the path the read route takes."""
        return {
            "path": entry["path"][len(folder) + 1 :],
            "size_bytes": entry["size_bytes"],
            "version": entry["version"],
            "updated_at": entry["updated_at"],
        }

    async def listing(folder: str, limit: int, page: int) -> PaginatedResponse:
        # The tree lists LIST_ENTRIES files a page, so one page here may span more than one of them.
        start = (page - 1) * limit
        tree_page, skip = start // LIST_ENTRIES + 1, start % LIST_ENTRIES
        rows: List[Dict[str, Any]] = []
        while True:
            result = await tree("alist", folder, tree_page)
            rows.extend(result["files"])
            if len(rows) >= skip + limit or "next_page" not in result:
                break
            tree_page += 1
        total = result["total"]
        return PaginatedResponse(
            data=[named(folder, row) for row in rows[skip : skip + limit]],
            meta=PaginationInfo(page=page, limit=limit, total_count=total, total_pages=(total + limit - 1) // limit),
        )

    async def reading(folder: str, path: str, offset: int) -> Dict[str, Any]:
        result = await tree("aread", f"{folder}/{path}", offset)
        if "content" not in result:
            raise HTTPException(404, "File not found")
        return {
            "content": result["content"],
            "metadata": named(folder, result),
            "next_offset": result.get("next_offset"),
        }

    @router.get("/tasks/{task_id}/files", response_model=PaginatedResponse[WikiPageResponse])
    async def list_task_files(
        task_id: str,
        limit: int = Query(20, ge=1, le=1000),
        page: int = Query(1, ge=1),
        _: bool = Depends(auth),
    ):
        return await listing(await task_folder(task_id), limit, page)

    @router.get("/tasks/{task_id}/files/{path:path}", response_model=CompanyFileReadResponse)
    async def read_task_file(task_id: str, path: str, offset: int = Query(0, ge=0), _: bool = Depends(auth)):
        return await reading(await task_folder(task_id), path, offset)

    @router.get("/notes", response_model=PaginatedResponse[WikiPageResponse])
    async def list_notes(
        limit: int = Query(20, ge=1, le=1000),
        page: int = Query(1, ge=1),
        _: bool = Depends(auth),
    ):
        return await listing(notes_folder(), limit, page)

    @router.get("/notes/{path:path}", response_model=CompanyFileReadResponse)
    async def read_note(path: str, offset: int = Query(0, ge=0), _: bool = Depends(auth)):
        return await reading(notes_folder(), path, offset)

    return router
