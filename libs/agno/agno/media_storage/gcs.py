import hashlib
import mimetypes
from datetime import timedelta
from typing import Any, Dict, Optional
from urllib.parse import quote

from agno.media_storage.base import AsyncMediaStorage, MediaStorage, sanitize_media_id
from agno.utils.log import log_debug, log_warning


class GCSMediaStorage(MediaStorage):
    """Google Cloud Storage media storage backend (google-cloud-storage).

    Authenticates via a service-account JSON (``credentials_path``), an explicit
    ``project``, or ambient application-default credentials.
    """

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

    @property
    def backend_name(self) -> str:
        return "gcs"

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from google.cloud import storage  # type: ignore
            except ImportError:
                raise ImportError(
                    "google-cloud-storage is required for GCSMediaStorage. "
                    "Install it with: pip install 'agno[media-storage-gcs]'"
                )
            if self.credentials_path:
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

    def _build_key(self, media_id: str, *, filename: Optional[str] = None, mime_type: Optional[str] = None) -> str:
        media_id = sanitize_media_id(media_id)
        ext = ""
        if filename and "." in filename:
            ext = "." + filename.rsplit(".", 1)[-1]
        elif mime_type:
            guessed = mimetypes.guess_extension(mime_type)
            if guessed:
                ext = guessed
        return f"{self.prefix}{media_id}{ext}"

    def upload(
        self,
        media_id: str,
        content: bytes,
        *,
        mime_type: Optional[str] = None,
        filename: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        key = self._build_key(media_id, filename=filename, mime_type=mime_type)
        blob = self._get_bucket().blob(key)

        # Custom metadata values must be strings; the full metadata is also preserved on the
        # MediaReference, so coercion here never loses anything.
        gcs_metadata: Dict[str, str] = {"content-sha256": hashlib.sha256(content).hexdigest()}
        if filename:
            gcs_metadata.setdefault("original-filename", filename)
        if metadata:
            for k, v in metadata.items():
                gcs_metadata[str(k)] = str(v)
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
            from google.cloud.exceptions import NotFound  # type: ignore

            if isinstance(e, NotFound):
                raise FileNotFoundError(storage_key) from e
            raise

    def get_url(self, storage_key: str, *, expires_in: int = 0) -> str:
        if expires_in <= 0:
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
        except Exception as e:
            # Signing needs a service-account private key; user/ADC credentials can't sign.
            # Return no URL rather than break offload — the media router streams bytes via
            # download() when a reference has no usable URL.
            log_debug(f"Could not sign GCS URL for {storage_key} (non-signing credentials); will stream instead: {e}")
            return ""

    def delete(self, storage_key: str) -> bool:
        try:
            self._get_bucket().blob(storage_key).delete()
            return True
        except Exception as e:
            log_warning(f"Failed to delete {storage_key}: {e}")
            return False

    def exists(self, storage_key: str) -> bool:
        try:
            return self._get_bucket().blob(storage_key).exists()
        except Exception:
            return False


class AsyncGCSMediaStorage(AsyncMediaStorage):
    """Async Google Cloud Storage media storage.

    Delegates to the synchronous GCSMediaStorage implementation, since
    google-cloud-storage has no native async API.
    """

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
        self._sync = GCSMediaStorage(
            bucket=bucket,
            prefix=prefix,
            credentials_path=credentials_path,
            project=project,
            presigned_url_expiry=presigned_url_expiry,
            public=public,
            persist_remote_urls=persist_remote_urls,
        )
        self.persist_remote_urls = persist_remote_urls

    @property
    def backend_name(self) -> str:
        return "gcs"

    @property
    def bucket(self) -> str:
        return self._sync.bucket

    async def upload(
        self,
        media_id: str,
        content: bytes,
        *,
        mime_type: Optional[str] = None,
        filename: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        return self._sync.upload(media_id, content, mime_type=mime_type, filename=filename, metadata=metadata)

    async def download(self, storage_key: str) -> bytes:
        return self._sync.download(storage_key)

    async def get_url(self, storage_key: str, *, expires_in: int = 3600) -> str:
        return self._sync.get_url(storage_key, expires_in=expires_in)

    async def delete(self, storage_key: str) -> bool:
        return self._sync.delete(storage_key)

    async def exists(self, storage_key: str) -> bool:
        return self._sync.exists(storage_key)
