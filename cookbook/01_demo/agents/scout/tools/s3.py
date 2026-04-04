"""S3 tools as an Agno Toolkit.

S3 is the primary connector for demos and most enterprise deployments.
Tools mirror Claude Code's approach: list, search (grep-like), read (full docs), write.
"""

from agno.tools import Toolkit, tool

from ..connectors.s3 import S3Connector


class S3Tools(Toolkit):
    """Toolkit for interacting with S3."""

    def __init__(
        self,
        default_bucket: str | None = None,
        allowed_prefixes: list[str] | None = None,
    ):
        super().__init__(name="s3_tools")
        self.connector = S3Connector(
            bucket=default_bucket, allowed_prefixes=allowed_prefixes
        )
        self.connector.authenticate()

        # Register tools
        self.register(self.list_buckets)
        self.register(self.list_files)
        self.register(self.search_files)
        self.register(self.read_file)
        self.register(self.write_file)

    @tool
    def list_buckets(self) -> str:
        """List available S3 buckets.

        Returns a list of buckets with their descriptions.
        Use this to understand what knowledge bases are available.
        """
        buckets = self.connector.list_buckets()

        if not buckets:
            return "No buckets found."

        lines = ["## S3 Buckets", ""]
        for bucket in buckets:
            lines.append(f"**{bucket['name']}**")
            if bucket.get("description"):
                lines.append(f"  {bucket['description']}")
            if bucket.get("region"):
                lines.append(f"  Region: {bucket['region']}")
            lines.append("")

        return "\n".join(lines)

    @tool
    def list_files(
        self,
        path: str | None = None,
        limit: int = 50,
    ) -> str:
        """List files and directories in S3.

        Args:
            path: Bucket or bucket/prefix to list (e.g., "company-docs" or "company-docs/policies").
                  If None, lists all buckets.
            limit: Maximum number of items to return.
        """
        items = self.connector.list_items(parent_id=path, limit=limit)

        if not items:
            return f"No files found in {path or 'S3'}."

        lines = [f"## Contents of {path or 'S3'}", ""]

        for item in items:
            if item["type"] == "bucket":
                lines.append(f"[bucket] **{item['name']}/**")
            elif item["type"] == "directory":
                lines.append(f"[dir] **{item['name']}/**")
            else:
                size = item.get("size", 0)
                size_str = _format_size(size)
                modified = item.get("modified", "")
                lines.append(f"[file] {item['name']} ({size_str}, {modified})")
                lines.append(f"   `{item['id']}`")

        return "\n".join(lines)

    @tool
    def search_files(
        self,
        query: str,
        bucket: str | None = None,
        limit: int = 10,
    ) -> str:
        """Search for files in S3 (grep-like search in filenames and content).

        This searches both filenames and file contents, returning matching
        files with context around the match (like grep -C).

        Args:
            query: Search query. Searches filenames and file contents.
            bucket: Limit search to specific bucket. If None, searches all buckets.
            limit: Maximum number of results.
        """
        filters = {"bucket": bucket} if bucket else None
        results = self.connector.search(query=query, filters=filters, limit=limit)

        if not results:
            return f"No files found matching '{query}'."

        lines = [f"## Search Results for '{query}'", ""]

        for result in results:
            lines.append(f"**{result['key']}**")
            lines.append(f"  Bucket: {result['bucket']}")
            lines.append(f"  Match: {result['match_type']}")

            if result.get("snippet"):
                lines.append("  ```")
                for snippet_line in result["snippet"].split("\n"):
                    lines.append(f"  {snippet_line}")
                lines.append("  ```")

            lines.append(f"  Path: `{result['id']}`")
            lines.append("")

        return "\n".join(lines)

    @tool
    def read_file(
        self,
        path: str,
        offset: int | None = None,
        limit: int | None = None,
    ) -> str:
        """Read the full content of a file from S3.

        Reads the entire file (not chunks). For large files, use offset/limit
        to paginate through the content.

        Args:
            path: S3 path (e.g., "s3://company-docs/policies/employee-handbook.md"
                  or "company-docs/policies/employee-handbook.md")
            offset: Line number to start from (for pagination).
            limit: Maximum number of lines to return (for pagination).
        """
        options = {}
        if offset is not None:
            options["offset"] = offset
        if limit is not None:
            options["limit"] = limit

        result = self.connector.read(path, options=options if options else None)

        if "error" in result:
            return f"Error: {result['error']}"

        lines = [f"# {result['key'].split('/')[-1]}", ""]

        if result.get("metadata"):
            meta = result["metadata"]
            lines.append("---")
            if meta.get("modified"):
                lines.append(f"Modified: {meta['modified']}")
            if meta.get("size"):
                lines.append(f"Size: {_format_size(meta['size'])}")
            lines.append("---")
            lines.append("")

        lines.append(result.get("content", ""))

        return "\n".join(lines)

    @tool
    def write_file(
        self,
        path: str,
        content: str,
    ) -> str:
        """Write content to a file in S3.

        Args:
            path: S3 path for the new file (e.g., "s3://company-docs/policies/new-policy.md")
            content: Content to write to the file.
        """
        # Parse path to get parent and filename
        if path.startswith("s3://"):
            path = path[5:]

        parts = path.rsplit("/", 1)
        if len(parts) == 2:
            parent, filename = parts
        else:
            return "Error: Invalid path format. Use bucket/path/filename.md"

        result = self.connector.write(parent_id=parent, title=filename, content=content)

        if "error" in result:
            return f"Error: {result['error']}"

        return f"Wrote file to `{result['id']}`"


def _format_size(size: int) -> str:
    """Format file size in human-readable format."""
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    else:
        return f"{size / (1024 * 1024):.1f} MB"
