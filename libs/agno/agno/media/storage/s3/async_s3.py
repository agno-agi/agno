import hashlib
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from agno.media.storage.base import AsyncMediaStorage
from agno.media.storage.s3.utils import (
    S3_DELETE_BATCH_SIZE,
    S3_MAX_PRESIGNED_EXPIRY,
    raise_if_acl_unsupported,
    sanitize_s3_metadata,
)
from agno.media.storage.utils import build_storage_key
from agno.utils.log import log_debug, log_warning


class AsyncS3MediaStorage(AsyncMediaStorage):
    """Async S3-compatible media storage backend (aioboto3).

    Supports AWS S3, MinIO, and other S3-compatible services via the ``endpoint_url``
    parameter. Such a server needs ``region`` set to match its own site region: a presigned
    URL carries the region in its signature and is rejected when the two disagree.
    """

    backend_name = "s3"

    def __init__(
        self,
        bucket: str,
        *,
        prefix: str = "agno/media/",
        region: Optional[str] = None,
        acl: Optional[str] = None,
        presigned_url_expiry: int = 3600,
        endpoint_url: Optional[str] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        persist_remote_urls: bool = False,
    ):
        self.bucket = bucket
        self.prefix = prefix
        self.region = region
        self.acl = acl
        self.presigned_url_expiry = presigned_url_expiry
        self.endpoint_url = endpoint_url
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        self.persist_remote_urls = persist_remote_urls

    def _get_session(self) -> Any:
        try:
            import aioboto3
        except ImportError:
            raise ImportError("`aioboto3` not installed. Please install using `pip install 'agno[s3]'`")
        return aioboto3.Session(
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
            region_name=self.region,
        )

    def _client_kwargs(self) -> Dict[str, Any]:
        from botocore.config import Config

        # Pin SigV4: unpinned, botocore presigns with SigV2 in pre-2014 regions and whenever
        # region is unset, and a bucket with SSE-KMS default encryption rejects every SigV2 URL.
        kwargs: Dict[str, Any] = {"config": Config(signature_version="s3v4")}
        if self.endpoint_url:
            kwargs["endpoint_url"] = self.endpoint_url
        return kwargs

    async def upload(
        self,
        media_id: str,
        content: bytes,
        *,
        mime_type: Optional[str] = None,
        filename: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        session = self._get_session()
        key = build_storage_key(media_id, prefix=self.prefix, filename=filename, mime_type=mime_type)

        put_kwargs: Dict[str, Any] = {"Bucket": self.bucket, "Key": key, "Body": content}
        if mime_type:
            put_kwargs["ContentType"] = mime_type
        if self.acl:
            put_kwargs["ACL"] = self.acl

        s3_metadata: Dict[str, str] = {"content-sha256": hashlib.sha256(content).hexdigest()}
        # original-filename first: the sanitizer stops at the size budget; a caller key of the same name wins.
        extra: Dict[str, Any] = {"original-filename": filename} if filename else {}
        extra.update(dict(metadata) if metadata else {})
        s3_metadata.update(sanitize_s3_metadata(extra))
        put_kwargs["Metadata"] = s3_metadata

        try:
            async with session.client("s3", **self._client_kwargs()) as client:
                await client.put_object(**put_kwargs)
        except Exception as e:
            raise_if_acl_unsupported(e, self.bucket)
            raise
        log_debug(f"Uploaded media {media_id} to s3://{self.bucket}/{key}")
        return key

    async def download(self, storage_key: str) -> bytes:
        session = self._get_session()
        try:
            async with session.client("s3", **self._client_kwargs()) as client:
                response = await client.get_object(Bucket=self.bucket, Key=storage_key)
                return await response["Body"].read()
        except Exception as e:
            # Normalize a missing object to FileNotFoundError so the media router returns 404.
            from botocore.exceptions import ClientError

            if isinstance(e, ClientError) and e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                raise FileNotFoundError(storage_key) from e
            raise

    async def get_url(self, storage_key: str, *, expires_in: Optional[int] = None) -> Optional[str]:
        if expires_in is None:
            expires_in = self.presigned_url_expiry

        if self.acl == "public-read":
            encoded_key = quote(storage_key)
            if self.endpoint_url:
                return f"{self.endpoint_url}/{self.bucket}/{encoded_key}"
            if self.region:
                host = f"{self.bucket}.s3.{self.region}.amazonaws.com"
            else:
                host = f"{self.bucket}.s3.amazonaws.com"
            return f"https://{host}/{encoded_key}"

        if expires_in > S3_MAX_PRESIGNED_EXPIRY:
            # Return no URL rather than one S3 will reject on use.
            log_warning(
                f"presigned_url_expiry {expires_in}s exceeds the SigV4 maximum of "
                f"{S3_MAX_PRESIGNED_EXPIRY}s, falling back to streaming"
            )
            return None

        session = self._get_session()
        async with session.client("s3", **self._client_kwargs()) as client:
            return await client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": storage_key},
                ExpiresIn=expires_in,
            )

    async def delete(self, storage_key: str) -> bool:
        try:
            # Session construction inside the guard: an unusable credential is a failed delete.
            session = self._get_session()
            async with session.client("s3", **self._client_kwargs()) as client:
                await client.delete_object(Bucket=self.bucket, Key=storage_key)
            return True
        except Exception as e:
            log_warning(f"Failed to delete {storage_key}: {e}")
            return False

    async def delete_many(self, storage_keys: List[str]) -> int:
        batches: List[List[str]] = []
        for key in storage_keys:
            if not batches or len(batches[-1]) == S3_DELETE_BATCH_SIZE:
                batches.append([])
            batches[-1].append(key)
        if not batches:
            return 0

        deleted = 0
        try:
            # Inside the guard as in delete(): a client that cannot be built is 0 deleted.
            session = self._get_session()
            async with session.client("s3", **self._client_kwargs()) as client:
                for batch in batches:
                    deleted += await self._delete_batch(client, batch)
        except Exception as e:
            log_warning(f"Failed to delete objects: {e}")
        return deleted

    async def _delete_batch(self, client: Any, keys: List[str]) -> int:
        try:
            response = await client.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": [{"Key": key} for key in keys], "Quiet": True},
            )
        except Exception as e:
            log_warning(f"Failed to delete {len(keys)} objects: {e}")
            return 0
        # Quiet mode reports only failures, and a key that was never there is not one.
        return len(keys) - len(response.get("Errors") or [])

    async def exists(self, storage_key: str) -> bool:
        try:
            session = self._get_session()
            async with session.client("s3", **self._client_kwargs()) as client:
                await client.head_object(Bucket=self.bucket, Key=storage_key)
            return True
        except Exception:
            return False
