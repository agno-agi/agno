"""Checkpoint objects in an S3 bucket, for deployments whose replicas share no filesystem.

Objects are content-addressed under ``<prefix><sha256>.tar.gz`` and carry their digest
and size as object metadata. Credentials come from the standard AWS environment and the
deployment's role, never from this module.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from contextlib import ExitStack, asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterator, Optional, Tuple

from agno.sandbox.base import SandboxError
from agno.sandbox.checkpoint import (
    _CHUNK,
    CheckpointArchive,
    CheckpointObjectNotFound,
    CheckpointRef,
    FileCheckpointStore,
    _regular,
    _thread,
)

_MIN_PART = 5 * 1024 * 1024  # S3 refuses smaller parts, except the last one.
_MISSING = {"404", "NoSuchKey", "NotFound"}
_FORBIDDEN = {"403", "AccessDenied", "Forbidden"}


def _client_error_code(error: BaseException) -> str:
    response = getattr(error, "response", None)
    return str(response.get("Error", {}).get("Code", "")) if isinstance(response, dict) else ""


class S3CheckpointStore:
    """Content-addressed immutable checkpoint objects in an S3-compatible bucket.

    ``put`` hashes the archive, skips the upload when the object already exists, and
    otherwise uploads it, in parts above ``part_size``. An upload is complete only once
    the object is readable, so a crash mid-upload leaves nothing a reader could restore.
    ``verify`` compares the object's size and the digest recorded at ``put`` without
    reading its bytes; ``open_archive`` downloads the object, checks its bytes against
    the reference, and yields a read-only local path. Without a cache the copy lives
    under ``scratch`` only for the duration of the context. With ``cache_dir`` set,
    downloaded objects are kept there under their digest, so opening the same checkpoint
    again costs a local hash instead of a download; the cache is bounded by
    ``cache_bytes`` and evicts the least recently opened objects, never one that a caller
    still holds open. Every replica with access to the bucket can restore what another
    one captured, which is what a durable queue needs.

    The credentials need ``s3:GetObject``, ``s3:PutObject`` and ``s3:DeleteObject`` on
    the prefix, and ``s3:AbortMultipartUpload`` for uploads above ``part_size``. Without
    ``s3:ListBucket`` S3 answers a HEAD on a missing key with 403 rather than 404; ``put``
    treats that as unknown and uploads, but ``verify`` reports it as the error it is.

    Args:
        bucket: The bucket name.
        prefix: Key prefix for every object, with a trailing slash added when missing.
        region: AWS region. Defaults to the SDK's resolution from the environment.
        endpoint_url: An S3-compatible service such as MinIO, Cloudflare R2 or a local
            test server. Unset for AWS.
        max_bytes: The largest object the store accepts, the checkpoint archive limit.
        part_size: Bytes per part for multipart uploads, and the size above which an
            upload uses them. At least 5 MiB.
        boto_session: A ``boto3.session.Session`` to build the client from; the default
            session otherwise, which reads the environment and the instance role.
        scratch: Directory for the temporary copy an uncached open downloads into. The
            system temporary directory otherwise, which may be small on a container.
        cache_dir: Keep downloaded objects here, keyed by digest, for later opens on this
            host. Unset, nothing is kept between opens.
        cache_bytes: The most the cache may hold before the least recently opened objects
            are evicted. Default 4 GiB. Objects a caller holds open are never removed
            from under it.
    """

    def __init__(
        self,
        bucket: str,
        *,
        prefix: str = "agno/sandbox/checkpoints/",
        region: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        max_bytes: int = 1024 * 1024 * 1024,
        part_size: int = 64 * 1024 * 1024,
        boto_session: Optional[Any] = None,
        scratch: Optional[Path] = None,
        cache_dir: Optional[Path] = None,
        cache_bytes: int = 4 * 1024 * 1024 * 1024,
    ) -> None:
        if not isinstance(bucket, str) or not bucket or "/" in bucket:
            raise ValueError("Checkpoint bucket must be a nonempty bucket name")
        if type(max_bytes) is not int or max_bytes < 1:
            raise ValueError("Checkpoint object limit must be positive")
        if type(part_size) is not int or part_size < _MIN_PART:
            raise ValueError("Checkpoint upload part size must be at least 5 MiB")
        prefix = prefix.strip("/")
        self.bucket = bucket
        self.prefix = f"{prefix}/" if prefix else ""
        self.region = region
        self.endpoint_url = endpoint_url
        self.max_bytes = max_bytes
        self.part_size = part_size
        self._boto_session = boto_session
        self._client: Optional[Any] = None
        if type(cache_bytes) is not int or cache_bytes < 1:
            raise ValueError("Checkpoint cache limit must be positive")
        self.scratch = Path(scratch) if scratch is not None else None
        if self.scratch is not None:
            self.scratch.mkdir(parents=True, exist_ok=True)
        self.cache_bytes = cache_bytes
        # The cache is itself a content-addressed file store: read-only objects, leases
        # that outlive eviction, and the same byte check on every open.
        self.cache = FileCheckpointStore(Path(cache_dir), max_bytes=max_bytes) if cache_dir is not None else None

    def key(self, reference: CheckpointRef) -> str:
        return f"{self.prefix}{reference.sha256}.tar.gz"

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                import boto3
                from botocore.config import Config
            except ImportError as error:
                raise ImportError("Install agno[s3] to store sandbox checkpoints in S3") from error
            session = self._boto_session or boto3.session.Session()
            kwargs: Dict[str, Any] = {"config": Config(signature_version="s3v4", retries={"mode": "standard"})}
            if self.region:
                kwargs["region_name"] = self.region
            if self.endpoint_url:
                kwargs["endpoint_url"] = self.endpoint_url
            self._client = session.client("s3", **kwargs)
        return self._client

    # ------------------------------------------------------------------ put

    def _digest(self, source: Path) -> CheckpointRef:
        digest, size = hashlib.sha256(), 0
        with _regular(Path(source)) as stream:
            while chunk := stream.read(_CHUNK):
                size += len(chunk)
                if size > self.max_bytes:
                    raise SandboxError("Checkpoint object exceeds its limit")
                digest.update(chunk)
        if size == 0:
            raise SandboxError("Checkpoint object is empty")
        return CheckpointRef(digest.hexdigest(), size)

    def _head(self, reference: CheckpointRef) -> Optional[Tuple[int, str]]:
        """The stored object's size and recorded digest, or None when the bucket has no such key."""
        from botocore.exceptions import ClientError

        try:
            response = self.client.head_object(Bucket=self.bucket, Key=self.key(reference))
        except ClientError as error:
            if _client_error_code(error) in _MISSING:
                return None
            raise
        metadata = response.get("Metadata") or {}
        return int(response["ContentLength"]), str(metadata.get("sha256", ""))

    def _check(self, reference: CheckpointRef, head: Optional[Tuple[int, str]]) -> None:
        if head is None:
            raise CheckpointObjectNotFound("Checkpoint object is missing")
        size, recorded = head
        if size != reference.size:
            raise SandboxError("Checkpoint size mismatch")
        if recorded != reference.sha256:
            raise SandboxError("Checkpoint checksum mismatch")

    def put(self, source: Path) -> CheckpointRef:
        from botocore.exceptions import ClientError

        reference = self._digest(Path(source))
        try:
            existing = self._head(reference)
        except ClientError as error:
            # Without s3:ListBucket a missing key answers 403; the upload settles it either
            # way, and the HEAD that confirms it needs only s3:GetObject.
            if _client_error_code(error) not in _FORBIDDEN:
                raise
            existing = None
        if existing is not None:
            # Content-addressed: the same bytes are already there, or something else sits
            # under the name they would take, which the check reports.
            self._check(reference, existing)
            return reference
        if reference.size > self.part_size:
            self._upload_parts(Path(source), reference)
        else:
            with _regular(Path(source)) as stream:
                self.client.put_object(
                    Bucket=self.bucket,
                    Key=self.key(reference),
                    Body=stream,
                    ContentLength=reference.size,
                    Metadata=self._metadata(reference),
                )
        # Readable, with the size and digest the reference promises, or the put did not happen.
        self._check(reference, self._head(reference))
        return reference

    @staticmethod
    def _metadata(reference: CheckpointRef) -> Dict[str, str]:
        return {"sha256": reference.sha256, "size": str(reference.size)}

    def _upload_parts(self, source: Path, reference: CheckpointRef) -> None:
        key = self.key(reference)
        upload = self.client.create_multipart_upload(Bucket=self.bucket, Key=key, Metadata=self._metadata(reference))
        upload_id = upload["UploadId"]
        parts = []
        try:
            with _regular(source) as stream:
                number = 1
                while chunk := stream.read(self.part_size):
                    response = self.client.upload_part(
                        Bucket=self.bucket, Key=key, UploadId=upload_id, PartNumber=number, Body=chunk
                    )
                    parts.append({"PartNumber": number, "ETag": response["ETag"]})
                    number += 1
            self.client.complete_multipart_upload(
                Bucket=self.bucket, Key=key, UploadId=upload_id, MultipartUpload={"Parts": parts}
            )
        except BaseException:
            # Nothing is readable under the key until completion; abort so the parts do
            # not linger as billable storage either.
            try:
                self.client.abort_multipart_upload(Bucket=self.bucket, Key=key, UploadId=upload_id)
            except Exception:
                pass
            raise

    async def aput(self, source: Path) -> CheckpointRef:
        return await _thread(self.put, source)

    # --------------------------------------------------------------- verify

    def verify(self, reference: CheckpointRef) -> None:
        if reference.size > self.max_bytes:
            raise SandboxError("Checkpoint object exceeds its limit")
        self._check(reference, self._head(reference))

    async def averify(self, reference: CheckpointRef) -> None:
        await _thread(self.verify, reference)

    # --------------------------------------------------------- open_archive

    def _download(self, reference: CheckpointRef) -> Path:
        """Fetch the object into a private temporary file whose bytes match the reference."""
        from botocore.exceptions import ClientError

        self.verify(reference)
        descriptor, name = tempfile.mkstemp(prefix=".checkpoint-", suffix=".tar", dir=self.scratch)
        path = Path(name)
        try:
            try:
                response = self.client.get_object(Bucket=self.bucket, Key=self.key(reference))
            except ClientError as error:
                if _client_error_code(error) in _MISSING:
                    raise CheckpointObjectNotFound("Checkpoint object is missing") from error
                raise
            digest, size = hashlib.sha256(), 0
            with os.fdopen(descriptor, "wb") as output:
                descriptor = -1
                for chunk in response["Body"].iter_chunks(_CHUNK):
                    size += len(chunk)
                    if size > reference.size:
                        raise SandboxError("Checkpoint size mismatch")
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if size != reference.size:
                raise SandboxError("Checkpoint size mismatch")
            if digest.hexdigest() != reference.sha256:
                raise SandboxError("Checkpoint checksum mismatch")
            # The copy is the caller's to read, never to edit: a consumer that wrote through
            # it would read back something the reference no longer describes.
            path.chmod(0o400)
            return path
        except BaseException:
            if descriptor != -1:
                os.close(descriptor)
            path.unlink(missing_ok=True)
            raise

    def _open_cached(self, reference: CheckpointRef) -> Tuple[ExitStack, Path]:
        """Lease the object from the cache, filling it from the bucket when it is not there.

        The bucket is still asked whether the object exists, so a checkpoint retention
        removed is reported missing even while a copy lingers here. The lease checks the
        cached bytes against the digest, once; an entry that fails that check is dropped
        and fetched again, and one evicted between the fill and the lease is fetched again.
        The returned stack holds the lease; closing it releases the lease, never the object.
        """
        assert self.cache is not None
        self.verify(reference)
        target = self.cache.root / reference.sha256
        for attempt in range(2):
            if not target.exists():
                self._fill(reference)
            stack = ExitStack()
            try:
                path = stack.enter_context(self.cache.open_archive(reference))
            except CheckpointObjectNotFound:
                if attempt:
                    raise
                continue
            except SandboxError:
                if attempt:
                    raise
                self.cache.delete(reference)
                continue
            os.utime(target)
            return stack, path
        raise AssertionError("unreachable")

    def _fill(self, reference: CheckpointRef) -> None:
        path = self._download(reference)
        try:
            self.cache.put(path)  # type: ignore[union-attr]
        finally:
            path.unlink(missing_ok=True)
        # Every lease the cache hands out is a hard link to this object, so its mode is
        # what keeps a consumer from editing the bytes the reference describes.
        (self.cache.root / reference.sha256).chmod(0o400)  # type: ignore[union-attr]
        self._evict(keep=reference)

    def _evict(self, *, keep: CheckpointRef) -> None:
        """Drop the least recently opened objects until the cache fits its budget.

        Only canonical names are removed; a lease an open caller holds keeps its bytes.
        """
        assert self.cache is not None
        objects = []
        for path in self.cache.root.iterdir():
            if path.name.startswith(".") or path.name == keep.sha256:
                continue
            try:
                info = path.stat()
            except FileNotFoundError:
                continue
            objects.append((info.st_mtime, info.st_size, path))
        total = sum(size for _, size, _ in objects) + (self.cache.root / keep.sha256).stat().st_size
        for _, size, path in sorted(objects):
            if total <= self.cache_bytes:
                break
            path.unlink(missing_ok=True)
            total -= size

    @contextmanager
    def open_archive(self, reference: CheckpointRef) -> Iterator[Path]:
        if self.cache is not None:
            stack, path = self._open_cached(reference)
            with stack:
                yield path
            return
        path = self._download(reference)
        try:
            yield path
        finally:
            path.unlink(missing_ok=True)

    @asynccontextmanager
    async def aopen_archive(self, reference: CheckpointRef) -> AsyncIterator[Path]:
        # _thread drains the work before a cancellation propagates and releases what it
        # finished, so nothing is left behind and nothing is removed while still in use.
        if self.cache is not None:
            # Entered in the thread: the lease verifies the cached object's digest.
            stack, path = await _thread(self._open_cached, reference, release=lambda opened: opened[0].close())
            with stack:
                yield path
            return
        path = await _thread(self._download, reference, release=lambda copy: copy.unlink(missing_ok=True))
        try:
            yield path
        finally:
            path.unlink(missing_ok=True)

    # --------------------------------------------------------------- delete

    def delete(self, reference: CheckpointRef) -> None:
        # S3 deletes are idempotent: a key that is already gone answers success.
        self.client.delete_object(Bucket=self.bucket, Key=self.key(reference))

    async def adelete(self, reference: CheckpointRef) -> None:
        await _thread(self.delete, reference)

    # -------------------------------------------------------------- restore

    def restore(
        self, reference: CheckpointRef, destination: Path, *, archive: Optional[CheckpointArchive] = None
    ) -> Dict[str, Any]:
        with self.open_archive(reference) as source:
            return (archive or CheckpointArchive()).restore(source, destination)

    async def arestore(
        self, reference: CheckpointRef, destination: Path, *, archive: Optional[CheckpointArchive] = None
    ) -> Dict[str, Any]:
        return await _thread(self.restore, reference, destination, archive=archive)
