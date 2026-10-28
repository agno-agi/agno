"""Refresh proposals and retention through Company and filesystem APIs."""

import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

from agno.company.execution import _call
from agno.company.playbook import _require_product_scope
from agno.db.schemas.products import product_metadata
from agno.utils.string import hash_string_sha256


async def _records(manager: Any, method: str, **filters: Any):
    rows = []
    page = 1
    while True:
        batch, total = await _call(manager, method, limit=100, page=page, **filters)
        rows.extend(batch)
        if page * 100 >= total:
            return rows
        page += 1


def _generated_page(path: str, content: str) -> bool:
    if path in {"brief.md", "status.md"}:
        return False
    return (path == "summary.md" and "<!-- Company summary snapshot:" in content) or (
        path.startswith("project-completion/") and content.startswith("<!-- Company completion proposal -->\n")
    )


def _completion_proposal(project: Dict[str, Any], tasks: List[Dict[str, Any]]) -> Tuple[str, str]:
    """Render the same server facts for Refresh and automatic acceptance."""
    path = "project-completion/" + hash_string_sha256(project["id"]) + ".md"
    content = (
        "<!-- Company completion proposal -->\n# Complete "
        + project["name"]
        + "\n\n"
        + "Proposed transition: Done. Every Task is terminal. A human must review and accept this proposal "
        + "through the Project transition API. Refresh has not changed the Project's status.\n\n"
        + "Project: "
        + project["id"]
        + "\n\n"
        + "\n".join(
            "- " + task["id"] + ": " + task["status"]
            for task in sorted(tasks, key=lambda task: task["id"])
            if task.get("deleted_at") is None
        )
        + "\n"
    )
    return path, content


async def arefresh_product(manager: Any, product_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    """Propose completion and archive old terminal work without accepting it."""
    product = await _call(manager, "get", product_id)
    if product is None:
        raise LookupError("Product not found")
    _require_product_scope(product)
    days = product_metadata(product.get("metadata"))["archive_window_days"]
    cutoff = int(time.time()) - days * 86400
    result: Dict[str, Any] = {
        "archive_window_days": days,
        "completion_proposals": [],
        "archived_projects": [],
        "archived_tasks": [],
        "deleted_pages": [],
    }
    # Snapshot paging before deleting prevents offset pagination from skipping work.
    for kind in ("project", "task"):
        records = await _records(manager, "list_" + kind + "s", product_id=product_id)
        for record in records:
            updated = record.get("updated_at")
            if (
                record["status"] not in {"done", "cancelled"}
                or (updated if updated is not None else record["created_at"]) >= cutoff
            ):
                continue
            # Recheck terminal state and age in the existing soft-delete statement.
            if await _call(manager, "delete_" + kind, record["id"], user_id=None, updated_before=cutoff):
                result["archived_" + kind + "s"].append(record["id"])

    from agno.db.schemas.scheduler import COMPANY_AUTOMATION_SCHEDULE_ID

    result["deleted_automation_runs"] = await _call(
        manager.schedule_db,
        "delete_schedule_runs",
        COMPANY_AUTOMATION_SCHEDULE_ID,
        before=int(time.time()) - manager.automation_history_retention_days * 86400,
    )
    wiki = await _call(manager, "get_wiki", product_id)
    filesystem = wiki.backend.filesystem
    for page in await filesystem.alist():
        if page.path in {"brief.md", "status.md"} or page.updated_at is None or page.updated_at >= cutoff:
            continue
        current = await filesystem.aread_with_meta(page.path)
        if (
            current is not None
            and current.metadata.updated_at is not None
            and current.metadata.updated_at < cutoff
            and _generated_page(page.path, current.content)
        ):
            if page.path == "summary.md":
                from agno.company.summary import _aload_summary_state

                # Upgrade old reports before retention removes their only delivery receipts.
                await _aload_summary_state(manager.db, product_id, current.content)
            if await filesystem.adelete(page.path, expected_version=current.metadata.version):
                result["deleted_pages"].append(page.path)

    projects = await _records(manager, "list_projects", product_id=product_id, status="active")
    for project in projects:
        tasks = await _records(manager, "list_tasks", project_id=project["id"], include_deleted=True)
        if not tasks or any(
            task["status"] not in {"done", "cancelled"} for task in tasks if task.get("deleted_at") is None
        ):
            continue
        path, content = _completion_proposal(project, tasks)
        existing = await filesystem.aread_with_meta(path)
        if existing is None or existing.content != content:
            await _call(
                manager,
                "write_wiki",
                product_id=product_id,
                path=path,
                content=content,
                expected_version=existing.metadata.version if existing else 0,
                user_id=user_id,
            )
        result["completion_proposals"].append({"project_id": project["id"], "name": project["name"], "path": path})
    # Withdraw stale proposals after new work arrives or the Project leaves Active.
    pending = {proposal["path"] for proposal in result["completion_proposals"]}
    for page in await filesystem.alist("project-completion"):
        if page.path in pending:
            continue
        current = await filesystem.aread_with_meta(page.path)
        if (
            current is not None
            and _generated_page(page.path, current.content)
            and await filesystem.adelete(page.path, expected_version=current.metadata.version)
        ):
            result["deleted_pages"].append(page.path)
    return result


def refresh_product(manager: Any, product_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    """Run the same retention and proposal operations through a synchronous manager."""
    return asyncio.run(arefresh_product(manager, product_id, user_id))
