from typing import Optional


class FileSystemError(Exception):
    """Base class for all FileSystem errors."""


class InvalidPathError(FileSystemError):
    """Raised for an invalid path, namespace name, directory parameter, or check-lines record."""


class QuotaExceededError(FileSystemError):
    """Raised when a write or append would exceed a size cap.

    ``scope`` is ``"file"`` or ``"namespace"``; ``current`` and ``limit`` are byte counts.
    For ``scope="file"``, ``current`` is the size the file would have reached.
    """

    def __init__(self, message: str, *, scope: str, current: int, limit: int) -> None:
        super().__init__(message)
        self.scope = scope
        self.current = current
        self.limit = limit


class VersionConflictError(FileSystemError):
    """Raised when a compare-and-swap write finds a version other than ``expected``.

    ``actual`` is ``None`` when the file does not exist.
    """

    def __init__(self, message: str, *, expected: int, actual: Optional[int]) -> None:
        super().__init__(message)
        self.expected = expected
        self.actual = actual


class UnsupportedOperationError(FileSystemError):
    """Raised by a backend that does not support the requested operation."""

    def __init__(self, message: str, *, operation: str, backend: str) -> None:
        super().__init__(message)
        self.operation = operation
        self.backend = backend
