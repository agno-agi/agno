from __future__ import annotations

import mimetypes
from typing import TYPE_CHECKING, List, Optional, Tuple

from agno.knowledge.remote_content.base import BaseStorageConfig, ListFilesResult

if TYPE_CHECKING:
    from agno.knowledge.remote_content.remote_content import S3Content


class S3Config(BaseStorageConfig):
    """Configuration for AWS S3 content source."""

    bucket_name: str
    region: Optional[str] = None
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    prefix: Optional[str] = None

    def list_files(
        self,
        prefix: Optional[str] = None,
        delimiter: str = "/",
        limit: int = 100,
        page: int = 1,
    ) -> ListFilesResult:
        """List files and folders in this S3 source with pagination.

        Uses S3's native continuation-token pagination to avoid loading all
        objects into memory. Only fetches the objects needed for the requested
        page (plus objects to skip for earlier pages).

        Args:
            prefix: Path prefix to filter files (e.g., "reports/2024/").
                    Overrides the config's prefix when provided.
            delimiter: Folder delimiter (default "/")
            limit: Max files to return per request (1-1000, clamped)
            page: Page number (1-indexed)

        Returns:
            ListFilesResult with files, folders, and pagination info
        """
        try:
            import boto3
        except ImportError:
            raise ImportError("The `boto3` package is not installed. Please install it via `pip install boto3`.")

        limit = max(1, min(limit, 1000))
        session_kwargs, client_kwargs = self._build_session_and_client_kwargs()
        effective_prefix = prefix if prefix is not None else (self.prefix or "")
        skip_count = (page - 1) * limit
        skipped = 0
        collected: list = []
        folders: list = []
        folders_seen = False
        total_count = 0
        has_more = False

        list_kwargs = self._build_list_kwargs(effective_prefix, delimiter)

        session = boto3.Session(**session_kwargs)
        s3_client = session.client("s3", **client_kwargs)

        while True:
            response = s3_client.list_objects_v2(**list_kwargs)

            folders, folders_seen, collected, skipped, total_count, page_has_more = self._process_list_response(
                response,
                effective_prefix,
                folders,
                folders_seen,
                collected,
                limit,
                skip_count,
                skipped,
                total_count,
            )
            if page_has_more:
                has_more = True
                break

            if response.get("IsTruncated"):
                list_kwargs["ContinuationToken"] = response["NextContinuationToken"]
            else:
                break

        return self._build_result(collected, folders, page, limit, total_count, has_more)

    def _build_session_and_client_kwargs(self) -> Tuple[dict, dict]:
        """Build boto3/aioboto3 session and client kwargs from config."""
        session_kwargs: dict = {}
        if self.region:
            session_kwargs["region_name"] = self.region

        client_kwargs: dict = {}
        if self.aws_access_key_id and self.aws_secret_access_key:
            client_kwargs["aws_access_key_id"] = self.aws_access_key_id
            client_kwargs["aws_secret_access_key"] = self.aws_secret_access_key

        return session_kwargs, client_kwargs

    def _build_list_kwargs(self, effective_prefix: str, delimiter: str) -> dict:
        """Build kwargs for list_objects_v2."""
        list_kwargs: dict = {"Bucket": self.bucket_name, "MaxKeys": 1000}
        if effective_prefix:
            list_kwargs["Prefix"] = effective_prefix
        if delimiter:
            list_kwargs["Delimiter"] = delimiter
        return list_kwargs

    @staticmethod
    def _process_list_response(
        response: dict,
        effective_prefix: str,
        folders: List[dict],
        folders_seen: bool,
        collected: List[dict],
        limit: int,
        skip_count: int,
        skipped: int,
        total_count: int,
    ) -> Tuple[List[dict], bool, List[dict], int, int, bool]:
        """Process a single list_objects_v2 response page.

        Returns (folders, folders_seen, collected, skipped, total_count, has_more).
        """
        has_more = False

        if not folders_seen:
            for prefix_obj in response.get("CommonPrefixes", []):
                folder_prefix = prefix_obj.get("Prefix", "")
                folder_name = folder_prefix.rstrip("/").rsplit("/", 1)[-1]
                if folder_name:
                    folders.append(
                        {
                            "prefix": folder_prefix,
                            "name": folder_name,
                            "is_empty": False,
                        }
                    )
            folders_seen = True

        for obj in response.get("Contents", []):
            key = obj.get("Key", "")
            if key == effective_prefix:
                continue
            name = key.rsplit("/", 1)[-1] if "/" in key else key
            if not name:
                continue

            total_count += 1

            if skipped < skip_count:
                skipped += 1
                continue

            if len(collected) < limit:
                collected.append(
                    {
                        "key": key,
                        "name": name,
                        "size": obj.get("Size"),
                        "last_modified": obj.get("LastModified"),
                        "content_type": mimetypes.guess_type(name)[0],
                    }
                )

        if response.get("IsTruncated") and len(collected) >= limit:
            has_more = True

        return folders, folders_seen, collected, skipped, total_count, has_more

    @staticmethod
    def _build_result(
        collected: list,
        folders: list,
        page: int,
        limit: int,
        total_count: int,
        has_more: bool,
    ) -> ListFilesResult:
        """Build the final ListFilesResult from accumulated data."""
        if has_more:
            total_pages = page + 1
        else:
            total_pages = (total_count + limit - 1) // limit if limit > 0 else 0

        if page > 1:
            folders = []

        return ListFilesResult(
            files=collected,
            folders=folders,
            page=page,
            limit=limit,
            total_count=total_count,
            total_pages=total_pages,
        )

    async def alist_files(
        self,
        prefix: Optional[str] = None,
        delimiter: str = "/",
        limit: int = 100,
        page: int = 1,
    ) -> ListFilesResult:
        """Async version of list_files using aioboto3.

        Args:
            prefix: Path prefix to filter files (e.g., "reports/2024/").
                    Overrides the config's prefix when provided.
            delimiter: Folder delimiter (default "/")
            limit: Max files to return per request (1-1000, clamped)
            page: Page number (1-indexed)

        Returns:
            ListFilesResult with files, folders, and pagination info
        """
        try:
            import aioboto3
        except ImportError:
            raise ImportError("The `aioboto3` package is not installed. Please install it via `pip install aioboto3`.")

        limit = max(1, min(limit, 1000))
        session_kwargs, client_kwargs = self._build_session_and_client_kwargs()
        effective_prefix = prefix if prefix is not None else (self.prefix or "")
        skip_count = (page - 1) * limit
        skipped = 0
        collected: list = []
        folders: list = []
        folders_seen = False
        total_count = 0
        has_more = False

        list_kwargs = self._build_list_kwargs(effective_prefix, delimiter)

        session = aioboto3.Session(**session_kwargs)
        async with session.client("s3", **client_kwargs) as s3_client:
            while True:
                response = await s3_client.list_objects_v2(**list_kwargs)

                folders, folders_seen, collected, skipped, total_count, page_has_more = self._process_list_response(
                    response,
                    effective_prefix,
                    folders,
                    folders_seen,
                    collected,
                    limit,
                    skip_count,
                    skipped,
                    total_count,
                )
                if page_has_more:
                    has_more = True
                    break

                if response.get("IsTruncated"):
                    list_kwargs["ContinuationToken"] = response["NextContinuationToken"]
                else:
                    break

        return self._build_result(collected, folders, page, limit, total_count, has_more)

    def file(self, key: str) -> "S3Content":
        """Create a content reference for a specific file.

        Args:
            key: The S3 object key (path to file).

        Returns:
            S3Content configured with this source's credentials.
        """
        from agno.knowledge.remote_content.remote_content import S3Content

        return S3Content(
            bucket_name=self.bucket_name,
            key=key,
            config_id=self.id,
        )

    def folder(self, prefix: str) -> "S3Content":
        """Create a content reference for a folder (prefix).

        Args:
            prefix: The S3 prefix (folder path).

        Returns:
            S3Content configured with this source's credentials.
        """
        from agno.knowledge.remote_content.remote_content import S3Content

        return S3Content(
            bucket_name=self.bucket_name,
            prefix=prefix,
            config_id=self.id,
        )
