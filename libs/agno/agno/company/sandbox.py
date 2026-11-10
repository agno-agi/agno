"""Derived executor capabilities, repository acceptance and completed checkout pins."""

from typing import Any, Dict, Optional, Tuple


def _is_sandboxed(component: Any) -> bool:
    from agno.agents.base import BaseExternalAgent

    return isinstance(component, BaseExternalAgent) and component.sandbox is not None


def _task_response(task: Dict[str, Any], registry: Any) -> Dict[str, Any]:
    from agno.registry._reserved import RESERVED_MANAGER_IDS

    kind = task.get("executor_type")
    component = (
        getattr(registry, "get_" + kind)(task.get("executor_id"))
        if registry is not None
        and kind in {"agent", "team", "workflow"}
        and task.get("executor_id")
        and task["executor_id"] not in RESERVED_MANAGER_IDS
        else None
    )
    return {**task, "sandboxed": _is_sandboxed(component)}


def _accept_sandbox(component: Any, sources: list) -> Dict[str, Any]:
    repository = component.repository
    if repository is None:
        raise ValueError("Sandboxed executor requires repository=Repository(url, branch)")
    matches = [source for source in sources if source["type"] == "git" and source["reference"] == repository.url]
    if not matches:
        raise ValueError("Sandboxed executor requires a Product git Source matching repository URL " + repository.url)
    # A public repository needs no credential. The runtime reads only this variable.
    usable = [source for source in matches if source.get("credential_ref") in {None, "GITHUB_READ_TOKEN"}]
    if not usable:
        raise ValueError("Sandboxed executor git Source credential_ref must be GITHUB_READ_TOKEN")
    usable = [
        source
        for source in usable
        if not source.get("credential_ref") or (component.sandbox.env or {}).get("GITHUB_READ_TOKEN")
    ]
    if not usable:
        raise ValueError("Sandboxed executor requires GITHUB_READ_TOKEN in Sandbox.env for this git Source")
    return sorted(usable, key=lambda source: source["id"])[0]


def _accept_checkout(component: Any, task: Dict[str, Any]) -> None:
    checkout = (task.get("metadata") or {}).get("checkout")
    if checkout is not None and not _is_sandboxed(component):
        raise ValueError("Task checkout is already pinned and requires a sandboxed executor; create a new Task")
    if checkout is not None and any(
        checkout.get(key) != getattr(component.repository, key) for key in ("url", "branch")
    ):
        raise ValueError("Task checkout is already pinned to another repository or branch; create a new Task")


async def _project_checkout(
    db: Any, task: Dict[str, Any], component: Any, data: Dict[str, Any], result: Dict[str, Any]
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    from agno.company.execution import _call
    from agno.sandbox.repository import validate_repository, validate_repository_override

    if not _is_sandboxed(component):
        return None, result
    try:
        pin = (data.get("metadata") or {}).get("sandbox", {}).get("repository")
        if not isinstance(pin, dict) or set(pin) != {"url", "branch", "commit"}:
            raise ValueError("Sandboxed run did not publish a repository pin")
        validate_repository({key: pin[key] for key in ("url", "branch")})
        validate_repository_override({"repository": {"commit": pin["commit"]}}, pin)
        checkout = (task.get("metadata") or {}).get("checkout")
        if checkout is not None:
            if pin != {key: checkout[key] for key in ("url", "branch", "commit")}:
                raise ValueError("Sandboxed run repository pin does not match the Task checkout")
            return checkout, result
        sources = []
        page = 1
        while True:
            rows, total = await _call(db, "get_sources", product_id=task["product_id"], limit=100, page=page)
            sources.extend(rows)
            if page * 100 >= total:
                break
            page += 1
        source = _accept_sandbox(component, sources)
        if pin["url"] != source["reference"]:
            raise ValueError("Sandboxed run repository pin does not match the Product git Source")
        return {"source_id": source["id"], **pin}, result
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        return None, {**result, "status": "ERROR", "content": str(exc)}
