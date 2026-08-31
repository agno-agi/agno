"""Durable storage for the messages a compaction replaced.

The archive is what makes compaction non-lossy. A summary alone is a guess
about what mattered; with the originals still readable, the summary becomes an
index over ground truth and a detail it dropped can still be recovered - by a
developer reading the file, or by the agent itself when ``searchable`` is on.

Files live on AgentFS, which by default means rows in the ``agno_fs`` table of
the agent's own database, not the local disk: an archive travels with the
session and survives a restart that would orphan a temp directory. Passing a
``LocalFileSystem`` puts real files on disk instead, which is the inspection
workflow, not the deployment one.
"""

from __future__ import annotations

import re
from typing import Any, List, Optional

from agno.compaction.types import ARCHIVE_NAMESPACE_PREFIX
from agno.fs._paths import MAX_SEGMENT_CHARS
from agno.fs.errors import FileSystemError, QuotaExceededError
from agno.models.message import Message
from agno.utils.log import log_debug, log_warning
from agno.utils.string import hash_string_sha256

# Characters AgentFS keeps as-is in a namespace segment. Anything else is
# folded to "_", which is not injective - hence the hash suffix below.
_NAMESPACE_UNSAFE = re.compile(r"[^a-z0-9._@+-]")
_NAMESPACE_HASH_CHARS = 8

# Tool results are the bulk of a long transcript and the least useful part to
# read back verbatim. Clip each one in the archive so a single enormous result
# cannot exhaust the per-file quota and cost the whole archive.
MAX_ARCHIVED_TOOL_RESULT_CHARS = 20_000


def namespace_for(session_id: str, scope: str = "") -> str:
    """The AgentFS namespace holding one session's compaction archive.

    The readable part is reduced to the characters AgentFS keeps as they are,
    and the hash suffix keeps two session ids that reduce to the same text
    apart - without it one session could read, and overwrite, another's
    archive. ``scope`` is the database schema, which on PostgreSQL keeps two
    schemas that reuse a session id from sharing files.
    """
    limit = MAX_SEGMENT_CHARS - _NAMESPACE_HASH_CHARS - 1
    readable = _NAMESPACE_UNSAFE.sub("_", session_id.lower())[:limit] or "_"
    digest = hash_string_sha256(f"{scope}:{session_id}" if scope else session_id)
    return f"{ARCHIVE_NAMESPACE_PREFIX}/{readable}-{digest[:_NAMESPACE_HASH_CHARS]}"


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [clipped, {len(text) - limit} more characters]"


def render_messages(messages: List[Message]) -> str:
    """Render messages as readable markdown.

    Written for a human (or an agent) reading with ``search_content``, so the
    role is a heading and tool calls name the tool: a grep for a tool name or a
    phrase from an old answer should land on the turn that produced it.
    """
    blocks: List[str] = []
    for message in messages:
        heading = message.role
        if message.tool_name:
            heading = f"{message.role} ({message.tool_name})"
        parts: List[str] = [f"## {heading}"]

        content = message.get_content_string()
        if content:
            # Tool results dominate the byte count and are the least valuable
            # part to keep in full.
            parts.append(_clip(content, MAX_ARCHIVED_TOOL_RESULT_CHARS) if message.role == "tool" else content)

        for tool_call in message.tool_calls or []:
            function = tool_call.get("function") if isinstance(tool_call, dict) else None
            if isinstance(function, dict):
                parts.append(f"**calls** `{function.get('name')}`: {function.get('arguments')}")

        blocks.append("\n\n".join(parts))
    return "\n\n".join(blocks)


class CompactionArchive:
    """Writes and reads one session's archived history."""

    def __init__(self, fs: Any) -> None:
        self.fs = fs

    # -- naming ---------------------------------------------------------

    def _next_path(self, existing_count: int) -> str:
        return f"{existing_count + 1:04d}.md"

    def _count(self) -> int:
        try:
            return len(self.fs.list())
        except FileSystemError as e:
            log_warning(f"Could not list compaction archive: {e}")
            return 0

    async def _acount(self) -> int:
        try:
            return len(await self.fs.alist())
        except FileSystemError as e:
            log_warning(f"Could not list compaction archive: {e}")
            return 0

    # -- writing --------------------------------------------------------

    def write(self, messages: List[Message]) -> Optional[str]:
        """Archive ``messages`` and return the path, or None if it could not be written.

        A failure here must never fail the run: compaction still proceeds with
        the summary alone. The caller records ``archive_path=None`` so it is
        visible that these messages are not recoverable.
        """
        if not messages:
            return None
        path = self._next_path(self._count())
        try:
            self.fs.write(path, render_messages(messages))
            log_debug(f"Archived {len(messages)} messages to {path}")
            return path
        except QuotaExceededError as e:
            log_warning(f"Compaction archive is full ({e.scope}); keeping the summary only: {e}")
        except FileSystemError as e:
            log_warning(f"Could not write compaction archive; keeping the summary only: {e}")
        return None

    async def awrite(self, messages: List[Message]) -> Optional[str]:
        if not messages:
            return None
        path = self._next_path(await self._acount())
        try:
            await self.fs.awrite(path, render_messages(messages))
            log_debug(f"Archived {len(messages)} messages to {path}")
            return path
        except QuotaExceededError as e:
            log_warning(f"Compaction archive is full ({e.scope}); keeping the summary only: {e}")
        except FileSystemError as e:
            log_warning(f"Could not write compaction archive; keeping the summary only: {e}")
        return None

    # -- reading --------------------------------------------------------

    def read(self, path: str) -> Optional[str]:
        return self.fs.read(path)

    async def aread(self, path: str) -> Optional[str]:
        return await self.fs.aread(path)


__all__ = ["CompactionArchive", "namespace_for", "render_messages"]
