"""S3 connector using boto3.

Connects to a real S3 bucket. Defaults to the public ``agno-scout-public``
bucket which requires no credentials. Set ``S3_BUCKET``, ``S3_REGION``, and
optionally ``S3_ACCESS_KEY_ID`` / ``S3_SECRET_ACCESS_KEY`` env vars to point
at a different bucket.
"""

from os import getenv
from typing import Any

import boto3
from botocore import UNSIGNED
from botocore.config import Config

from .base import BaseConnector

_TEXT_EXTENSIONS = {".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".xml", ".html"}

_VIRTUAL_BUCKET_DESCRIPTIONS: dict[str, str] = {
    "company-docs": "Company documents and policies",
    "engineering-docs": "Engineering documentation",
    "data-exports": "Data exports and reports",
}


class S3Connector(BaseConnector):
    """S3 connector backed by boto3."""

    def __init__(
        self,
        bucket: str | None = None,
        region: str | None = None,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        allowed_prefixes: list[str] | None = None,
    ):
        self._bucket = bucket or getenv("S3_BUCKET", "agno-scout-public")
        self._region = region or getenv("S3_REGION", "us-east-1")
        self._endpoint_url = endpoint_url or getenv("S3_ENDPOINT", "")
        self._access_key_id = access_key_id or getenv("S3_ACCESS_KEY_ID", "")
        self._secret_access_key = secret_access_key or getenv(
            "S3_SECRET_ACCESS_KEY", ""
        )
        self._allowed_prefixes = allowed_prefixes
        self._client: Any = None

    def _is_allowed(self, key: str) -> bool:
        if self._allowed_prefixes is None:
            return True
        return any(key.startswith(p) for p in self._allowed_prefixes)

    @property
    def source_type(self) -> str:
        return "s3"

    @property
    def source_name(self) -> str:
        return "S3"

    def authenticate(self) -> bool:
        kwargs: dict[str, Any] = {"region_name": self._region}

        if self._access_key_id and self._secret_access_key:
            kwargs["aws_access_key_id"] = self._access_key_id
            kwargs["aws_secret_access_key"] = self._secret_access_key
        else:
            kwargs["config"] = Config(signature_version=UNSIGNED)

        if self._endpoint_url:
            kwargs["endpoint_url"] = self._endpoint_url

        self._client = boto3.client("s3", **kwargs)
        return True

    # ------------------------------------------------------------------
    # list_buckets  — top-level prefixes as virtual buckets
    # ------------------------------------------------------------------

    def list_buckets(self) -> list[dict[str, Any]]:
        result = self._client.list_objects_v2(
            Bucket=self._bucket,
            Delimiter="/",
        )
        buckets: list[dict[str, Any]] = []
        for prefix in result.get("CommonPrefixes", []):
            name = prefix["Prefix"].rstrip("/")
            if not self._is_allowed(name + "/"):
                continue
            buckets.append(
                {
                    "name": name,
                    "region": self._region,
                    "description": _VIRTUAL_BUCKET_DESCRIPTIONS.get(name, ""),
                }
            )
        return buckets

    # ------------------------------------------------------------------
    # list_items
    # ------------------------------------------------------------------

    def list_items(
        self,
        parent_id: str | None = None,
        item_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if not parent_id:
            return [
                {"id": b["name"], "name": b["name"], "type": "bucket"}
                for b in self.list_buckets()
            ]

        prefix = parent_id.rstrip("/") + "/"

        result = self._client.list_objects_v2(
            Bucket=self._bucket,
            Prefix=prefix,
            Delimiter="/",
        )

        items: list[dict[str, Any]] = []

        for cp in result.get("CommonPrefixes", []):
            dir_name = cp["Prefix"][len(prefix) :].rstrip("/")
            full_prefix = cp["Prefix"]
            if not self._is_allowed(full_prefix):
                continue
            items.append(
                {
                    "id": f"{parent_id}/{dir_name}",
                    "name": dir_name,
                    "type": "directory",
                }
            )

        for obj in result.get("Contents", []):
            key = obj["Key"]
            if not self._is_allowed(key):
                continue
            name = key[len(prefix) :]
            if not name:
                continue
            items.append(
                {
                    "id": f"s3://{self._bucket}/{key}",
                    "name": name,
                    "type": "file",
                    "size": obj.get("Size", 0),
                    "modified": obj["LastModified"].strftime("%Y-%m-%d")
                    if obj.get("LastModified")
                    else "",
                }
            )

        return items[:limit]

    # ------------------------------------------------------------------
    # search  — download text objects and grep
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        query_lower = query.lower()
        results: list[dict[str, Any]] = []

        target_bucket = filters.get("bucket") if filters else None
        prefix = (target_bucket.rstrip("/") + "/") if target_bucket else ""

        paginator = self._client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=self._bucket, Prefix=prefix)

        for page in pages:
            for obj in page.get("Contents", []):
                if len(results) >= limit:
                    return results

                key = obj["Key"]
                if key.endswith("/"):
                    continue
                if not self._is_allowed(key):
                    continue

                parts = key.split("/", 1)
                bucket_name = parts[0] if len(parts) > 1 else ""
                relative_key = parts[1] if len(parts) > 1 else parts[0]
                file_name = key.rsplit("/", 1)[-1]
                modified = (
                    obj["LastModified"].strftime("%Y-%m-%d")
                    if obj.get("LastModified")
                    else ""
                )

                if query_lower in relative_key.lower():
                    results.append(
                        {
                            "id": f"s3://{self._bucket}/{key}",
                            "bucket": bucket_name,
                            "key": relative_key,
                            "name": file_name,
                            "match_type": "filename",
                            "modified": modified,
                        }
                    )
                    continue

                ext = "." + file_name.rsplit(".", 1)[-1] if "." in file_name else ""
                if ext not in _TEXT_EXTENSIONS:
                    continue

                try:
                    resp = self._client.get_object(Bucket=self._bucket, Key=key)
                    content = resp["Body"].read().decode("utf-8", errors="replace")
                except Exception:
                    continue

                if query_lower in content.lower():
                    snippet = _extract_snippet_with_context(content, query)
                    results.append(
                        {
                            "id": f"s3://{self._bucket}/{key}",
                            "bucket": bucket_name,
                            "key": relative_key,
                            "name": file_name,
                            "match_type": "content",
                            "snippet": snippet,
                            "modified": modified,
                        }
                    )

        return results[:limit]

    # ------------------------------------------------------------------
    # read
    # ------------------------------------------------------------------

    def read(
        self,
        item_id: str,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        key = item_id
        if key.startswith("s3://"):
            key = key[5:]
            # Remove bucket name prefix if it matches
            if key.startswith(self._bucket + "/"):
                key = key[len(self._bucket) + 1 :]

        parts = key.split("/", 1)
        if len(parts) < 2:
            return {"error": f"Invalid S3 path: {item_id}"}

        if not self._is_allowed(key):
            return {"error": f"Access denied: {item_id}"}

        bucket_name = parts[0]

        try:
            resp = self._client.get_object(Bucket=self._bucket, Key=key)
            content = resp["Body"].read().decode("utf-8", errors="replace")
        except self._client.exceptions.NoSuchKey:
            return {"error": f"File not found: s3://{self._bucket}/{key}"}
        except Exception as e:
            return {"error": f"Error reading {key}: {e}"}

        if options and options.get("offset"):
            lines = content.split("\n")
            offset = options.get("offset", 0)
            line_limit = options.get("limit", 100)
            content = "\n".join(lines[offset : offset + line_limit])

        return {
            "id": f"s3://{self._bucket}/{key}",
            "bucket": bucket_name,
            "key": key,
            "content": content,
            "metadata": {
                "size": len(content),
                "modified": resp["LastModified"].strftime("%Y-%m-%d")
                if resp.get("LastModified")
                else "",
            },
        }

    # ------------------------------------------------------------------
    # write
    # ------------------------------------------------------------------

    def write(
        self,
        parent_id: str,
        title: str,
        content: str,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        parent = parent_id
        if parent.startswith("s3://"):
            parent = parent[5:]
        if parent.startswith(self._bucket + "/"):
            parent = parent[len(self._bucket) + 1 :]

        key = f"{parent}/{title}" if parent else title

        if not self._is_allowed(key):
            return {"error": f"Access denied: {key}"}

        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=content.encode("utf-8"),
            )
        except Exception as e:
            return {"error": f"Error writing {key}: {e}"}

        bucket_name = key.split("/")[0]
        return {
            "id": f"s3://{self._bucket}/{key}",
            "bucket": bucket_name,
            "key": key,
        }

    # ------------------------------------------------------------------
    # update
    # ------------------------------------------------------------------

    def update(
        self,
        item_id: str,
        content: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if content is None:
            return {"id": item_id, "message": "No content to update"}

        key = item_id
        if key.startswith("s3://"):
            key = key[5:]
        if key.startswith(self._bucket + "/"):
            key = key[len(self._bucket) + 1 :]

        if not self._is_allowed(key):
            return {"error": f"Access denied: {key}"}

        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=content.encode("utf-8"),
            )
        except Exception as e:
            return {"error": f"Error updating {key}: {e}"}

        return {"id": f"s3://{self._bucket}/{key}"}


def _extract_snippet_with_context(
    content: str,
    query: str,
    context_lines: int = 2,
) -> str:
    query_lower = query.lower()
    lines = content.split("\n")

    for i, line in enumerate(lines):
        if query_lower in line.lower():
            start = max(0, i - context_lines)
            end = min(len(lines), i + context_lines + 1)

            snippet_lines = []
            for j in range(start, end):
                prefix = ">" if j == i else " "
                snippet_lines.append(f"{prefix} {lines[j]}")

            return "\n".join(snippet_lines)

    return content[:200] + "..."
