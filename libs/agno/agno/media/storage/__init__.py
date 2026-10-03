from agno.media.reference import MediaReference
from agno.media.storage.base import AsyncMediaStorage, MediaStorage

__all__ = [
    "MediaStorage",
    "AsyncMediaStorage",
    "MediaReference",
    "LocalMediaStorage",
    "AsyncLocalMediaStorage",
    "S3MediaStorage",
    "AsyncS3MediaStorage",
    "GCSMediaStorage",
    "AsyncGCSMediaStorage",
]


def __getattr__(name: str):
    """Lazy import for storage backends so an unused backend's dependency is never required."""
    if name in ("LocalMediaStorage", "AsyncLocalMediaStorage"):
        from agno.media.storage import local

        return getattr(local, name)
    elif name in ("S3MediaStorage", "AsyncS3MediaStorage"):
        from agno.media.storage import s3

        return getattr(s3, name)
    elif name in ("GCSMediaStorage", "AsyncGCSMediaStorage"):
        from agno.media.storage import gcs

        return getattr(gcs, name)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
