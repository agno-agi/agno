"""Cookbook-only BaseFS adapter for UTF-8 files in one dedicated E2B sandbox.

Use through FileSystem, which normalizes paths and applies quotas. This adapter
does not provide durable storage, file versions, or atomic append/move. BaseFS
supplies search, usage, and async methods using its synchronous implementations.
"""

from pathlib import PurePosixPath
from typing import List, Optional
from urllib.parse import quote

from e2b import FileType, Sandbox
from e2b.exceptions import NotFoundException

from agno.fs.base import BaseFS
from agno.fs.errors import InvalidPathError, UnsupportedOperationError
from agno.fs.types import FileMeta


class E2BFileSystem(BaseFS):
    """File tools for a fresh sandbox used exclusively by this application.

    Namespaces are separate directory components under /home/user/agno-files.
    This path layout is not a security boundary against other sandbox processes;
    do not share this sandbox with untrusted users or arbitrary shell tools.
    """

    def __init__(self, sandbox: Sandbox) -> None:
        self._sandbox = sandbox
        self._base_path = PurePosixPath("/home/user/agno-files")

    def _target(self, namespace: str, path: str = "") -> PurePosixPath:
        if not namespace or namespace in (".", ".."):
            raise InvalidPathError("A non-empty namespace is required")
        if path and (path.startswith("/") or any(part in ("", ".", "..") for part in path.split("/"))):
            raise InvalidPathError("Use a relative file path without traversal")
        # Encode slashes so a namespace cannot become nested inside another one.
        return self._base_path / quote(namespace, safe="") / path

    def read(self, namespace: str, path: str) -> Optional[str]:
        target = str(self._target(namespace, path))
        try:
            if self._sandbox.files.get_info(target).type != FileType.FILE:
                return None
            return self._sandbox.files.read(target, format="text")
        except NotFoundException:
            return None

    def write(self, namespace: str, path: str, content: str, *, expected_version: Optional[int] = None) -> FileMeta:
        if expected_version is not None:
            raise UnsupportedOperationError(
                "This E2B backend does not support file versions",
                operation="write",
                backend="E2BFileSystem",
            )
        target = str(self._target(namespace, path))
        # E2B creates missing parent directories during a write.
        self._sandbox.files.write(target, content)
        return FileMeta(path=path, size_bytes=len(content.encode("utf-8")))

    def list(self, namespace: str, directory: str = "") -> List[FileMeta]:
        namespace_root = self._target(namespace)
        pending = [self._target(namespace, directory)]
        entries: List[FileMeta] = []
        while pending:
            current = pending.pop()
            try:
                children = self._sandbox.files.list(str(current), depth=1)
            except NotFoundException:
                continue
            for item in children:
                target = PurePosixPath(item.path)
                # Only visit direct children; do not follow symbolic links.
                if target.parent != current:
                    continue
                if item.type == FileType.DIR:
                    pending.append(target)
                elif item.type == FileType.FILE:
                    entries.append(
                        FileMeta(
                            path=target.relative_to(namespace_root).as_posix(),
                            size_bytes=item.size,
                            updated_at=int(item.modified_time.timestamp()),
                        )
                    )
        return entries

    def delete(self, namespace: str, path: str) -> bool:
        target = str(self._target(namespace, path))
        try:
            # E2B remove also accepts directories; expose only file deletion here.
            if self._sandbox.files.get_info(target).type != FileType.FILE:
                return False
            self._sandbox.files.remove(target)
            return True
        except NotFoundException:
            return False
