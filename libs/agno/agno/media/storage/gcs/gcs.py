import hashlib
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import quote

from agno.media.storage.base import MediaStorage
from agno.media.storage.utils import build_storage_key
from agno.utils.log import log_debug, log_warning

# GCS caps all custom metadata keys and values at 8 KiB per object; the budget here leaves
# room for the content-sha256 entry upload() adds outside the cap.
_GCS_METADATA_MAX_BYTES = 8000


def _sanitize_gcs_metadata(items: Dict[str, Any], *, max_bytes: int = _GCS_METADATA_MAX_BYTES) -> Dict[str, str]:
    """Coerce metadata to the string values GCS accepts, within its size budget.

    GCS metadata travels in a JSON body, so unlike S3 it takes newlines and non-ASCII
    verbatim and only the size needs bounding — an oversized dict fails the whole upload,
    leaving the bytes inline for the database to store as base64. Entries that would exceed
    the budget are dropped; the full metadata is preserved on the MediaReference, so
    nothing is permanently lost.
    """
    safe: Dict[str, str] = {}
    total = 0
    for k, v in items.items():
        key, val = str(k), str(v)
        total += len(key.encode()) + len(val.encode())
        if total > max_bytes:
            break
        safe[key] = val
    return safe


class GCSMediaStorage(MediaStorage):
    """Google Cloud Storage media storage backend (google-cloud-storage).

    ``public=True`` only changes which URL ``get_url`` returns — it does not grant
    anyone access. GCS has no per-object equivalent of S3's ``acl="public-read"``
    once uniform bucket-level access is on (the default for new buckets), so the
    bucket must already grant ``roles/storage.objectViewer`` to ``allUsers`` or the
    returned URL answers 403.

    Signing needs a private key, which the ambient application-default credentials used
    when ``credentials_path`` is unset do not carry. With those, ``get_url`` returns ``""``
    and readers fall back to streaming through ``download`` — pass ``credentials_path`` to
    a service-account JSON to get signed URLs.
    """

    backend_name = "gcs"

    def __init__(
        self,
        bucket: str,
        *,
        prefix: str = "agno/media/",
        credentials_path: Optional[str] = None,
        project: Optional[str] = None,
        presigned_url_expiry: int = 3600,
        public: bool = False,
        persist_remote_urls: bool = False,
    ):
        self.bucket = bucket
        self.prefix = prefix
        self.credentials_path = credentials_path
        self.project = project
        self.presigned_url_expiry = presigned_url_expiry
        self.public = public
        self.persist_remote_urls = persist_remote_urls
        self._client: Optional[Any] = None
        self._bucket: Optional[Any] = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from google.cloud import storage  # type: ignore
            except ImportError:
                raise ImportError(
                    "google-cloud-storage is required for GCSMediaStorage. Install it with: pip install 'agno[gcs]'"
                )
            if self.credentials_path:
                if not Path(self.credentials_path).is_file():
                    raise ValueError(
                        f"credentials_path '{self.credentials_path}' does not exist, so GCSMediaStorage "
                        "cannot authenticate."
                    )
                self._client = storage.Client.from_service_account_json(self.credentials_path)
            elif self.project:
                self._client = storage.Client(project=self.project)
            else:
                self._client = storage.Client()
        return self._client

    def _get_bucket(self) -> Any:
        if self._bucket is None:
            self._bucket = self._get_client().bucket(self.bucket)
        return self._bucket

    def upload(
        self,
        media_id: str,
        content: bytes,
        *,
        mime_type: Optional[str] = None,
        filename: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        key = build_storage_key(media_id, prefix=self.prefix, filename=filename, mime_type=mime_type)
        blob = self._get_bucket().blob(key)

        gcs_metadata: Dict[str, str] = {"content-sha256": hashlib.sha256(content).hexdigest()}
        # original-filename first: the sanitizer stops at the size budget, so a large caller
        # value would otherwise push the framework's own key out. A caller key of the same name
        # still wins, because dict(metadata) overwrites it.
        extra: Dict[str, Any] = {"original-filename": filename} if filename else {}
        extra.update(dict(metadata) if metadata else {})
        gcs_metadata.update(_sanitize_gcs_metadata(extra))
        blob.metadata = gcs_metadata

        blob.upload_from_string(content, content_type=mime_type)
        log_debug(f"Uploaded media {media_id} to gs://{self.bucket}/{key}")
        return key

    def download(self, storage_key: str) -> bytes:
        try:
            return self._get_bucket().blob(storage_key).download_as_bytes()
        except Exception as e:
            # Normalize a missing object to FileNotFoundError so callers (e.g. the media
            # router) can distinguish "gone" (404) from a real fetch failure (502).
            from google.api_core.exceptions import NotFound  # type: ignore

            # GCS answers NotFound for a missing bucket too, and only a missing object means
            # "gone". NotFound carries no code to discriminate on, so match the object case
            # positively: GCS names the bucket inside every missing-object message, so
            # ruling the bucket case out by looking for the word turned every missing object in
            # a bucket like "prod-bucket-eu" into a 502. Anything unrecognized still propagates,
            # so a misconfiguration is never reported back as absent media.
            if isinstance(e, NotFound) and "no such object" in str(e).lower():
                raise FileNotFoundError(storage_key) from e
            raise

    def get_url(self, storage_key: str, *, expires_in: Optional[int] = None) -> str:
        if expires_in is None:
            expires_in = self.presigned_url_expiry

        if self.public:
            return f"https://storage.googleapis.com/{self.bucket}/{quote(storage_key)}"

        try:
            return (
                self._get_bucket()
                .blob(storage_key)
                .generate_signed_url(
                    expiration=timedelta(seconds=expires_in),
                    version="v4",
                )
            )
        except AttributeError as e:
            # What google-cloud-storage raises for a credential with no private key. Return no
            # URL rather than break offload — the media router streams bytes via download().
            log_debug(f"Could not sign GCS URL for {storage_key} (non-signing credentials); will stream instead: {e}")
            return ""
        except Exception as e:
            # Anything else is a misconfiguration, not a limitation of the credential — a
            # presigned_url_expiry above GCS's V4 ceiling of seven days, say.
            log_warning(f"Could not sign GCS URL for {storage_key}; will stream instead: {e}")
            return ""

    def delete(self, storage_key: str) -> bool:
        try:
            self._get_bucket().blob(storage_key).delete()
            return True
        except Exception as e:
            # An object already gone counts as deleted, per delete()'s idempotency contract.
            from google.api_core.exceptions import NotFound  # type: ignore

            # Same discriminator download() uses, and for the same reason: GCS answers NotFound
            # for a missing bucket too, so accepting every NotFound reported a typo'd bucket as
            # a successful delete forever.
            if isinstance(e, NotFound) and "no such object" in str(e).lower():
                return True
            log_warning(f"Failed to delete {storage_key}: {e}")
            return False

    # delete_many is inherited, at one round trip per key: delete_blobs is itself a client-side
    # loop, and Client.batch(), which does pipeline sub-requests into one HTTP call, raises on
    # the first already-missing key and abandons the rest — losing delete()'s idempotency.

    def exists(self, storage_key: str) -> bool:
        try:
            return self._get_bucket().blob(storage_key).exists()
        except Exception:
            return False
