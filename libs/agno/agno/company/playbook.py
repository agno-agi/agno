"""Company wiki namespaces, backed by the existing durable filesystem."""

from typing import Any, Dict, Optional

from agno.context.wiki.backend import DurableWikiBackend
from agno.context.wiki.provider import WikiContextProvider
from agno.fs import FileSystem
from agno.fs._paths import normalize_path
from agno.fs.errors import VersionConflictError


def _wiki(db: Any, product: Optional[Dict[str, Any]] = None) -> WikiContextProvider:
    namespace = "company/wiki" if product is None else f"company/products/{product['id']}/wiki"
    try:
        filesystem = FileSystem(db, namespace=namespace, user_scoped=False)
    except (TypeError, ValueError) as exc:
        raise NotImplementedError("Company wiki requires a supported FileSystem database") from exc
    return WikiContextProvider(
        id="company-wiki" if product is None else f"product-{product['id']}-wiki",
        name="Company playbook" if product is None else f"{product['name']} playbook",
        backend=DurableWikiBackend(filesystem),
        write=False,
    )


def _page_path(path: str) -> str:
    normalized = normalize_path(path)
    if normalized != path or not normalized.endswith(".md"):
        raise ValueError("Wiki paths must be normalized relative Markdown paths")
    return normalized


def _defaults(product: Optional[Dict[str, Any]]) -> Dict[str, str]:
    title = product["name"] if product else "Company"
    purpose = (product.get("purpose") or "") if product else "Shared company context."
    return {"brief.md": f"# {title}\n\n{purpose}\n", "status.md": f"# {title} status\n\nNo status recorded yet.\n"}


def _require_product_scope(record: Dict[str, Any]) -> None:
    """Keep a Routine's authority on its own Product; Company writes are not owner-scoped."""
    from agno.company.routines import _require_routine_product

    _require_routine_product(record.get("product_id") or record.get("id"))


def _seed(provider: WikiContextProvider, product: Optional[Dict[str, Any]]) -> None:
    assert isinstance(provider.backend, DurableWikiBackend)
    for path, content in _defaults(product).items():
        if provider.backend.filesystem.read_with_meta(path) is not None:
            continue
        try:
            provider.backend.filesystem.write(path, content, expected_version=0)
        except VersionConflictError:
            pass


async def _aseed(provider: WikiContextProvider, product: Optional[Dict[str, Any]]) -> None:
    assert isinstance(provider.backend, DurableWikiBackend)
    for path, content in _defaults(product).items():
        if await provider.backend.filesystem.aread_with_meta(path) is not None:
            continue
        try:
            await provider.backend.filesystem.awrite(path, content, expected_version=0)
        except VersionConflictError:
            pass
