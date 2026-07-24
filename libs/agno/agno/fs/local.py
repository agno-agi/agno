"""LocalFileSystem: the disk-based backend for FileSystem."""

import os
import tempfile
from pathlib import Path
from typing import List, Optional, Union

from agno.exceptions import PathSecurityError
from agno.fs._paths import build_chunk, path_in_directory
from agno.fs.base import BaseFS
from agno.fs.errors import InvalidPathError, QuotaExceededError, UnsupportedOperationError
from agno.fs.types import FileMeta
from agno.utils.path_safety import safe_join_relative_path


class LocalFileSystem(BaseFS):
    """Disk-based backend: files live at ``root/<namespace-dir>/<path>``, where
    ``<namespace-dir>`` is the namespace with its slashes percent-encoded into one
    directory component (namespace ``"research/decisions"`` -> ``research%2Fdecisions``).
    Encoding keeps a child namespace from nesting inside a name-prefix parent on disk.
    """

    def __init__(self, root: Union[str, Path]) -> None:
        self.root: Path = Path(root).resolve()

    # ---- helpers ----

    @staticmethod
    def _encode_namespace(namespace: str) -> str:
        # Fold the namespace into ONE on-disk directory component by percent-encoding
        # its slashes. Without this, namespace "radar/alice" nests inside namespace
        # "radar" on disk, so a walk of "radar" leaks "radar/alice"'s files. The
        # namespace and path columns are separate in DbFileSystem but flatten to the
        # same tree here. Namespaces are lowercase and URL-safe, so "%" cannot occur
        # in one and this encoding is unambiguous without escaping it.
        return namespace.replace("/", "%2f")

    def _safe_join(self, rel: str, shown: str) -> Path:
        """Join ``rel`` under root, and REJECT any name that safe_join does not map to
        itself. ``safe_join_relative_path`` NFKC-folds and rstrips ". " per segment, a
        map that is both non-injective and stronger than the D6 grammar: it silently
        collapses distinct legal names (``a.`` and ``a``, ``ﬀ`` and ``ff``) onto one
        directory, and folds NFC-stable fullwidth dots (``．．``) into ``..``, which is
        a cross-namespace traversal escape reachable through model-supplied paths. D5
        promises LocalFileSystem's legal set is a strict subset of D6, so enforce that:
        anything the on-disk map would alter is rejected here, not silently remapped.
        """
        try:
            resolved = safe_join_relative_path(self.root, rel)
        except PathSecurityError:
            # Never surface the host root in the error, since that leaks the absolute path.
            raise InvalidPathError(
                f"invalid path {shown!r}: not representable on this backend. Use relative paths like notes/topic.md."
            ) from None
        if resolved.relative_to(self.root).as_posix() != rel:
            raise InvalidPathError(
                f"invalid path {shown!r}: contains characters this backend cannot store safely "
                "(e.g. fullwidth dots, trailing dots/spaces, or compatibility variants). "
                "Use plain relative paths like notes/topic.md."
            )
        return resolved

    def _target(self, namespace: str, path: str) -> Path:
        return self._safe_join(f"{self._encode_namespace(namespace)}/{path}", path)

    def _namespace_root(self, namespace: str) -> Path:
        return self._safe_join(self._encode_namespace(namespace), namespace)

    @staticmethod
    def _read_text(target: Path) -> str:
        # newline="" disables universal-newline translation: contents round-trip byte-exact.
        with target.open("r", encoding="utf-8", newline="") as f:
            return f.read()

    def _meta(self, path: str, target: Path) -> FileMeta:
        stat = target.stat()
        return FileMeta(path=path, size_bytes=stat.st_size, version=None, updated_at=int(stat.st_mtime))

    # ---- required core ----

    def read(self, namespace: str, path: str) -> Optional[str]:
        target = self._target(namespace, path)
        if not target.is_file():
            return None
        return self._read_text(target)

    def write(self, namespace: str, path: str, content: str, *, expected_version: Optional[int] = None) -> FileMeta:
        if expected_version is not None:
            raise UnsupportedOperationError(
                "LocalFileSystem does not version files, expected_version is unsupported",
                operation="write",
                backend="LocalFileSystem",
            )
        target = self._target(namespace, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        # A per-write unique temp file, not a fixed "<name>.tmp": concurrent writers to
        # one path would otherwise share the temp and unlink it out from under each
        # other (FileNotFoundError instead of last-writer-wins), and writing "a.md"
        # would clobber a pre-existing "a.md.tmp".
        fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp")
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                f.write(content)
            os.replace(tmp_path, target)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()
        return self._meta(path, target)

    def list(self, namespace: str, directory: str = "") -> List[FileMeta]:
        namespace_root = self._namespace_root(namespace)
        if not namespace_root.is_dir():
            return []
        metas: List[FileMeta] = []
        for dirpath, _dirnames, filenames in os.walk(namespace_root):
            for filename in filenames:
                full = Path(dirpath) / filename
                rel = full.relative_to(namespace_root).as_posix()
                if not path_in_directory(rel, directory):
                    continue
                try:
                    metas.append(self._meta(rel, full))
                except OSError:
                    continue
        return metas

    def delete(self, namespace: str, path: str) -> bool:
        target = self._target(namespace, path)
        if not target.is_file():
            return False
        target.unlink()
        return True

    # ---- native overrides ----

    def append(self, namespace: str, path: str, content: str, *, max_file_bytes: Optional[int] = None) -> FileMeta:
        chunk = build_chunk(content)
        target = self._target(namespace, path)
        if not chunk:
            if target.is_file():
                return self._meta(path, target)
            return FileMeta(path=path, size_bytes=0, version=None, updated_at=None)
        chunk_bytes = len(chunk.encode("utf-8"))
        if target.is_file():
            existing = self._read_text(target)
            separator = "\n" if existing and not existing.endswith("\n") else ""
            new_size = len(existing.encode("utf-8")) + len(separator) + chunk_bytes
            if max_file_bytes is not None and new_size > max_file_bytes:
                raise QuotaExceededError(
                    f"{path} would be {new_size} bytes (limit {max_file_bytes} per file)",
                    scope="file",
                    current=new_size,
                    limit=max_file_bytes,
                )
            with target.open("a", encoding="utf-8", newline="") as f:
                f.write(separator + chunk)
        else:
            if max_file_bytes is not None and chunk_bytes > max_file_bytes:
                raise QuotaExceededError(
                    f"{path} would be {chunk_bytes} bytes (limit {max_file_bytes} per file)",
                    scope="file",
                    current=chunk_bytes,
                    limit=max_file_bytes,
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            # Create at 0600, the mode write() gets from mkstemp, so a file's
            # permissions do not depend on which tool created it. The mode applies
            # only to creation; appending to an existing file leaves its mode alone.
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                f.write(chunk)
        return self._meta(path, target)

    def move(self, namespace: str, src: str, dst: str, *, overwrite: bool = False) -> FileMeta:
        src_target = self._target(namespace, src)
        dst_target = self._target(namespace, dst)
        if not src_target.is_file():
            raise FileNotFoundError(f"file not found: {src}")
        if src_target == dst_target:
            # A self-move is a no-op, not a collision with itself. Without this the
            # dst-exists check below rejects move(a, a) here while DbFileSystem and
            # the base emulation both succeed, so the two v1 backends would answer
            # the same model-reachable call differently.
            return self._meta(dst, dst_target)
        if dst_target.exists() and not overwrite:
            raise FileExistsError(f"file exists: {dst}")
        dst_target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src_target, dst_target)
        return self._meta(dst, dst_target)
