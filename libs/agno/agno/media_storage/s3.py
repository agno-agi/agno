import hashlib
import mimetypes
from typing import Any, Dict, Optional

from agno.media_storage.base import MediaStorage
from agno.utils.log import logger


class S3MediaStorage(MediaStorage):
    """S3-compatible media storage backend (boto3).

    Supports AWS S3, MinIO, DigitalOcean Spaces, and other S3-compatible services
    via the ``endpoint_url`` parameter.
    """

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
    ):
        self.bucket = bucket
        self.prefix = prefix
        self.region = region
        self.acl = acl
        self.presigned_url_expiry = presigned_url_expiry
        self.endpoint_url = endpoint_url
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        self._client: Optional[Any] = None

    @property
    def backend_name(self) -> str:
        return "s3"

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import boto3
            except ImportError:
                raise ImportError(
                    "boto3 is required for S3MediaStorage. Install it with: pip install 'agno[media-storage-s3]'"
                )
            kwargs: Dict[str, Any] = {}
            if self.region:
                kwargs["region_name"] = self.region
            if self.endpoint_url:
                kwargs["endpoint_url"] = self.endpoint_url
            if self.aws_access_key_id:
                kwargs["aws_access_key_id"] = self.aws_access_key_id
            if self.aws_secret_access_key:
                kwargs["aws_secret_access_key"] = self.aws_secret_access_key
            self._client = boto3.client("s3", **kwargs)
        return self._client

    def _build_key(self, media_id: str, *, filename: Optional[str] = None, mime_type: Optional[str] = None) -> str:
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
        client = self._get_client()
        key = self._build_key(media_id, filename=filename, mime_type=mime_type)

        put_kwargs: Dict[str, Any] = {"Bucket": self.bucket, "Key": key, "Body": content}
        if mime_type:
            put_kwargs["ContentType"] = mime_type
        if self.acl:
            put_kwargs["ACL"] = self.acl

        s3_metadata: Dict[str, str] = {}
        if filename:
            s3_metadata["original-filename"] = filename
        content_hash = hashlib.sha256(content).hexdigest()
        s3_metadata["content-sha256"] = content_hash
        if metadata:
            for k, v in metadata.items():
                s3_metadata[str(k)] = str(v)
        if s3_metadata:
            put_kwargs["Metadata"] = s3_metadata

        client.put_object(**put_kwargs)
        logger.debug(f"Uploaded media {media_id} to s3://{self.bucket}/{key}")
        return key

    def download(self, storage_key: str) -> bytes:
        client = self._get_client()
        response = client.get_object(Bucket=self.bucket, Key=storage_key)
        return response["Body"].read()

    def get_url(self, storage_key: str, *, expires_in: int = 0) -> str:
        if expires_in <= 0:
            expires_in = self.presigned_url_expiry

        if self.acl == "public-read":
            if self.endpoint_url:
                return f"{self.endpoint_url}/{self.bucket}/{storage_key}"
            return f"https://{self.bucket}.s3.{self.region or 'us-east-1'}.amazonaws.com/{storage_key}"

        client = self._get_client()
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": storage_key},
            ExpiresIn=expires_in,
        )

    def delete(self, storage_key: str) -> bool:
        client = self._get_client()
        try:
            client.delete_object(Bucket=self.bucket, Key=storage_key)
            return True
        except Exception as e:
            logger.warning(f"Failed to delete {storage_key}: {e}")
            return False

    def exists(self, storage_key: str) -> bool:
        client = self._get_client()
        try:
            client.head_object(Bucket=self.bucket, Key=storage_key)
            return True
        except Exception:
            return False
