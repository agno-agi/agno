from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agno.fs import FileSystem


def _filesystem_backend_key(filesystem: "FileSystem") -> tuple:
    """Identify a shared backend within the current process."""
    backend = filesystem.backend
    db = getattr(backend, "db", None)
    if db is not None:
        return (
            "db",
            getattr(db, "id", None) or id(db),
            getattr(backend, "db_schema", None),
            getattr(backend, "table_name", None),
        )
    root = getattr(backend, "root", None)
    if root is not None:
        return ("local", str(root))
    return ("backend", id(backend))
