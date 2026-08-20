"""ResultStore — big tool results become AgentFS files, not messages.

When a tool result crosses the threshold, the full payload is written to
AgentFS (namespace ``tool-results/{session_id}``) and the transcript gets a
short envelope: a head preview, the total size, and a ``result_id``. Three
properties are non-negotiable: lossless (the full bytes are recoverable),
free (no model call on the write path), and bounded (every read back through
the tools is capped).

Index rows live in ``agno_tool_results`` on the agent's db. PostgreSQL and
SQLite implement it; every other backend runs with offloading off. Failure is
loud, never silent: a refused write produces a head+tail envelope that says
so, and the run continues.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from agno.fs import FileSystem
from agno.fs._paths import MAX_SEGMENT_CHARS
from agno.fs.errors import QuotaExceededError
from agno.offload.types import ResultMatch, ResultPage, ResultRef
from agno.utils.log import log_debug, log_warning
from agno.utils.string import hash_string_sha256

# Tools whose own output is already capped and must never be offloaded.
NEVER_OFFLOADED_TOOLS = ("read_result", "search_result")

# Per-result and per-session-namespace quotas, raised from the AgentFS
# defaults for this store.
MAX_RESULT_BYTES = 8_000_000
MAX_SESSION_NAMESPACE_BYTES = 200_000_000
MAX_CALL_ID_ATTEMPTS = 1000

# read_result caps: whichever binds first.
READ_MAX_LINES = 400
READ_MAX_CHARS = 16_000

# search_result caps.
SEARCH_MAX_MATCHES = 20
SEARCH_LINE_CLIP = 500

_TAIL_LINES = 5


def result_id_for(session_id: str, run_id: str, tool_call_id: str) -> str:
    """Deterministic, re-derivable from the run without a lookup.

    The session id is part of the key because the id is the primary key of one
    shared index table. Two sessions that reuse a run id would otherwise write
    one row, and the second write would take the first session's result away.
    """
    return "res_" + hash_string_sha256(f"{session_id}:{run_id}:{tool_call_id}")[:10]


def _format_size(size: float) -> str:
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{int(size)}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}GB"


def _head_preview(output: str, preview_lines: int, preview_chars: int) -> str:
    """First ``preview_lines`` lines or ``preview_chars`` chars, whichever binds first."""
    head = "\n".join(output.split("\n")[:preview_lines])
    if len(head) > preview_chars:
        head = head[:preview_chars]
    return head


def render_stored_envelope(ref: ResultRef, preview: str) -> str:
    return (
        f'<result id="{ref.result_id}" tool="{ref.tool_name}" lines="{ref.line_count}" '
        f'size="{_format_size(ref.size_bytes)}">\n'
        f"{preview}\n"
        "</result>\n"
        f'Full result stored; read with read_result("{ref.result_id}") or '
        f'search_result("{ref.result_id}", pattern).'
    )


def render_refused_envelope(*, tool_name: str, output: str, reason: str, preview_lines: int, preview_chars: int) -> str:
    lines = output.split("\n")
    line_count = len(lines)
    size = _format_size(len(output.encode("utf-8")))
    head = _head_preview(output, preview_lines, preview_chars)
    head_line_count = len(head.split("\n"))
    parts = [
        f'<result tool="{tool_name}" lines="{line_count}" size="{size}" stored="false" reason="{reason}">',
        head,
    ]
    omitted = line_count - head_line_count - _TAIL_LINES
    if omitted > 0:
        parts.append(f"[... {omitted} lines omitted ...]")
        parts.append("\n".join(lines[-_TAIL_LINES:]))
    parts.append("</result>")
    parts.append("Full result was NOT stored. Re-run the tool with a narrower query if you need the rest.")
    return "\n".join(parts)


def _looks_like_json(output: str) -> bool:
    stripped = output.lstrip()
    if not stripped or stripped[0] not in "[{":
        return False
    try:
        json.loads(output)
        return True
    except (ValueError, RecursionError):
        return False


def _canonical_args_hash(tool_args: Optional[Dict[str, Any]]) -> str:
    try:
        canonical = json.dumps(tool_args or {}, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        canonical = str(tool_args)
    return hash_string_sha256(canonical)


def _safe_segment(value: str) -> str:
    """Make a caller-supplied id safe as one path segment."""
    cleaned = re.sub(r"[\\/\x00-\x1f]", "_", value) or "_"
    return cleaned[:120]


_NAMESPACE_UNSAFE = re.compile(r"[^a-z0-9._@+-]")
_NAMESPACE_HASH_CHARS = 8


def namespace_for(session_id: str) -> str:
    """The AgentFS namespace holding one session's payloads.

    The readable part is lowercased and reduced to the characters AgentFS keeps
    as they are, so the namespace written on an index row is the one AgentFS
    resolves on read and delete. Two session ids can reduce to the same text;
    the hash suffix keeps them apart. Without it, deleting one session would
    delete the other's payloads and leave its index rows pointing at nothing.
    The segment stays within the AgentFS segment limit with the suffix added.
    """
    limit = MAX_SEGMENT_CHARS - _NAMESPACE_HASH_CHARS - 1
    readable = _NAMESPACE_UNSAFE.sub("_", session_id.lower())[:limit] or "_"
    return f"tool-results/{readable}-{hash_string_sha256(session_id)[:_NAMESPACE_HASH_CHARS]}"


class ResultStore:
    """Stores oversized tool results as AgentFS files with a small index table.

    Usable without an agent. The sync and ``a``-prefixed async surfaces are
    equivalent; the async one uses the db's native async methods when the db
    is async, and worker threads otherwise.
    """

    def __init__(
        self,
        fs: FileSystem,
        *,
        db: Optional[Any] = None,
        threshold: int = 4000,
        preview_lines: int = 20,
        preview_chars: int = 1200,
        ttl_seconds: Optional[int] = None,
    ) -> None:
        self.fs = fs
        self.db = db
        self.threshold = threshold
        self.preview_lines = preview_lines
        self.preview_chars = preview_chars
        self.ttl_seconds = ttl_seconds
        self._swept_sessions: set = set()

    # ------------------------------------------------------------------
    # db bridging (sync callers need a sync db; async callers take either)
    # ------------------------------------------------------------------

    def _db_call(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        if self.db is None:
            raise RuntimeError("ResultStore has no db; index operations are unavailable")
        fn = getattr(self.db, method_name)
        if asyncio.iscoroutinefunction(fn):
            raise RuntimeError(
                f"ResultStore: '{method_name}' is async on {type(self.db).__name__}; use the a-prefixed store method"
            )
        return fn(*args, **kwargs)

    async def _adb_call(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        if self.db is None:
            raise RuntimeError("ResultStore has no db; index operations are unavailable")
        fn = getattr(self.db, method_name)
        if asyncio.iscoroutinefunction(fn):
            return await fn(*args, **kwargs)
        return await asyncio.to_thread(fn, *args, **kwargs)

    # ------------------------------------------------------------------
    # Namespaces and rows
    # ------------------------------------------------------------------

    def _session_fs(self, session_id: str) -> FileSystem:
        return FileSystem(
            backend=self.fs.backend,
            namespace=namespace_for(session_id),
            max_file_bytes=MAX_RESULT_BYTES,
            max_namespace_bytes=MAX_SESSION_NAMESPACE_BYTES,
        )

    def _fs_for_namespace(self, namespace: str) -> FileSystem:
        return FileSystem(
            backend=self.fs.backend,
            namespace=namespace,
            max_file_bytes=MAX_RESULT_BYTES,
            max_namespace_bytes=MAX_SESSION_NAMESPACE_BYTES,
        )

    def _build_row(
        self,
        *,
        session_id: str,
        run_id: str,
        tool_call_id: str,
        tool_name: str,
        tool_args: Optional[Dict[str, Any]],
        output: str,
        namespace: str,
        path: str,
        content_type: str,
        user_id: Optional[str],
    ) -> Dict[str, Any]:
        created_at = int(time.time())
        return {
            "result_id": result_id_for(session_id, run_id, tool_call_id),
            "namespace": namespace,
            "path": path,
            "session_id": session_id,
            "run_id": run_id,
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "args_hash": _canonical_args_hash(tool_args),
            "content_type": content_type,
            "size_bytes": len(output.encode("utf-8")),
            "line_count": len(output.split("\n")),
            "preview": _head_preview(output, self.preview_lines, self.preview_chars),
            "user_id": user_id,
            "created_at": created_at,
            "expires_at": created_at + self.ttl_seconds if self.ttl_seconds else None,
        }

    def _plan(self, *, run_id: str, tool_call_id: str, output: str, shared: bool) -> Tuple[str, str]:
        """(path, content_type) for a payload."""
        content_type = "json" if _looks_like_json(output) else "text"
        extension = "json" if content_type == "json" else "txt"
        prefix = "shared" if shared else "results"
        path = f"{prefix}/{_safe_segment(run_id)}/{_safe_segment(tool_call_id)}.{extension}"
        return path, content_type

    @staticmethod
    def _ref_from_row(row: Dict[str, Any]) -> ResultRef:
        return ResultRef(
            result_id=str(row["result_id"]),
            path=str(row["path"]),
            tool_name=str(row["tool_name"]),
            size_bytes=int(row["size_bytes"]),
            line_count=int(row["line_count"]),
            content_type=str(row["content_type"]),
            created_at=int(row["created_at"]),
        )

    # ------------------------------------------------------------------
    # Offload
    # ------------------------------------------------------------------

    def _free_call_id(self, session_id: str, run_id: str, tool_call_id: str) -> str:
        """A call id whose result id is not yet taken in this session.

        The result id is derived from the call, so one call stored once keeps
        a predictable id. A paused run continued more than once executes the
        same call again under the same ids; each later write gets a suffix so
        it cannot replace an earlier payload that a transcript still points to.
        """
        candidate = tool_call_id
        for attempt in range(2, MAX_CALL_ID_ATTEMPTS + 2):
            if self.get_row(result_id_for(session_id, run_id, candidate)) is None:
                return candidate
            candidate = f"{tool_call_id}~{attempt}"
        return candidate

    async def _afree_call_id(self, session_id: str, run_id: str, tool_call_id: str) -> str:
        """Async variant of ``_free_call_id``."""
        candidate = tool_call_id
        for attempt in range(2, MAX_CALL_ID_ATTEMPTS + 2):
            if await self.aget_row(result_id_for(session_id, run_id, candidate)) is None:
                return candidate
            candidate = f"{tool_call_id}~{attempt}"
        return candidate

    def offload(
        self,
        *,
        session_id: str,
        run_id: str,
        tool_call_id: str,
        tool_name: str,
        tool_args: dict,
        output: str,
        user_id: Optional[str] = None,
        shared: bool = False,
    ) -> ResultRef:
        """Store one payload and its index row. Raises ``QuotaExceededError``
        when the store refuses the write."""
        tool_call_id = self._free_call_id(session_id, run_id, tool_call_id)
        path, content_type = self._plan(run_id=run_id, tool_call_id=tool_call_id, output=output, shared=shared)
        session_fs = self._session_fs(session_id)
        session_fs.write(path, output)
        row = self._build_row(
            session_id=session_id,
            run_id=run_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_args=tool_args,
            output=output,
            namespace=session_fs.namespace,
            path=path,
            content_type=content_type,
            user_id=user_id,
        )
        try:
            self._db_call("upsert_tool_result", row)
        except Exception:
            # Payload without an index row is unreachable garbage; drop it.
            try:
                session_fs.delete(path)
            except Exception:
                pass
            raise
        return self._ref_from_row(row)

    async def aoffload(
        self,
        *,
        session_id: str,
        run_id: str,
        tool_call_id: str,
        tool_name: str,
        tool_args: dict,
        output: str,
        user_id: Optional[str] = None,
        shared: bool = False,
    ) -> ResultRef:
        """Async variant of ``offload``."""
        tool_call_id = await self._afree_call_id(session_id, run_id, tool_call_id)
        path, content_type = self._plan(run_id=run_id, tool_call_id=tool_call_id, output=output, shared=shared)
        session_fs = self._session_fs(session_id)
        await session_fs.awrite(path, output)
        row = self._build_row(
            session_id=session_id,
            run_id=run_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_args=tool_args,
            output=output,
            namespace=session_fs.namespace,
            path=path,
            content_type=content_type,
            user_id=user_id,
        )
        try:
            await self._adb_call("upsert_tool_result", row)
        except Exception:
            try:
                await session_fs.adelete(path)
            except Exception:
                pass
            raise
        return self._ref_from_row(row)

    # ------------------------------------------------------------------
    # The substitution seam used by the model layer (framework-internal)
    # ------------------------------------------------------------------

    def should_offload(self, tool_name: Optional[str], output: Any) -> bool:
        """The trigger: character length over the threshold, and never for the
        read-back tools' own output."""
        if tool_name in NEVER_OFFLOADED_TOOLS:
            return False
        if not isinstance(output, str):
            output = str(output) if output is not None else ""
        return len(output) > self.threshold

    def _quota_reason(self, error: QuotaExceededError) -> str:
        if error.scope == "namespace":
            return f"session storage is full ({error.current} of {error.limit} bytes)"
        return f"result is too large to store ({error.current} of {error.limit} bytes per result)"

    def offload_for_model(
        self,
        *,
        session_id: str,
        run_id: str,
        tool_call_id: str,
        tool_name: str,
        tool_args: Optional[Dict[str, Any]],
        output: str,
        user_id: Optional[str] = None,
        shared: bool = False,
    ) -> str:
        """Offload and return the envelope; on refusal, the head+tail envelope.

        Never raises: failure is loud in the envelope, and the run continues.
        """
        try:
            ref = self.offload(
                session_id=session_id,
                run_id=run_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                tool_args=dict(tool_args or {}),
                output=output,
                user_id=user_id,
                shared=shared,
            )
            return render_stored_envelope(ref, _head_preview(output, self.preview_lines, self.preview_chars))
        except QuotaExceededError as e:
            reason = self._quota_reason(e)
        except Exception as e:
            log_warning(f"Result offloading failed for {tool_name}: {e}")
            reason = f"the result store refused the write: {e}"
        return render_refused_envelope(
            tool_name=tool_name,
            output=output,
            reason=reason,
            preview_lines=self.preview_lines,
            preview_chars=self.preview_chars,
        )

    async def aoffload_for_model(
        self,
        *,
        session_id: str,
        run_id: str,
        tool_call_id: str,
        tool_name: str,
        tool_args: Optional[Dict[str, Any]],
        output: str,
        user_id: Optional[str] = None,
        shared: bool = False,
    ) -> str:
        """Async variant of ``offload_for_model``."""
        try:
            ref = await self.aoffload(
                session_id=session_id,
                run_id=run_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                tool_args=dict(tool_args or {}),
                output=output,
                user_id=user_id,
                shared=shared,
            )
            return render_stored_envelope(ref, _head_preview(output, self.preview_lines, self.preview_chars))
        except QuotaExceededError as e:
            reason = self._quota_reason(e)
        except Exception as e:
            log_warning(f"Result offloading failed for {tool_name}: {e}")
            reason = f"the result store refused the write: {e}"
        return render_refused_envelope(
            tool_name=tool_name,
            output=output,
            reason=reason,
            preview_lines=self.preview_lines,
            preview_chars=self.preview_chars,
        )

    # ------------------------------------------------------------------
    # Read back
    # ------------------------------------------------------------------

    def get_row(self, result_id: str) -> Optional[Dict[str, Any]]:
        """The index row for a result id, or None. The tool layer uses the
        row's session_id to refuse cross-session reads."""
        return self._db_call("get_tool_result", result_id)

    async def aget_row(self, result_id: str) -> Optional[Dict[str, Any]]:
        """Async variant of ``get_row``."""
        return await self._adb_call("get_tool_result", result_id)

    def _page_from_content(self, content: str, start_line: int, end_line: Optional[int]) -> ResultPage:
        lines = content.split("\n")
        line_count = len(lines)
        start = max(1, start_line)
        end = min(end_line if end_line is not None else line_count, line_count)
        selected = lines[start - 1 : end]
        clipped: List[str] = []
        chars = 0
        truncated = False
        for line in selected:
            if len(clipped) >= READ_MAX_LINES:
                truncated = True
                break
            if chars + len(line) + 1 > READ_MAX_CHARS:
                remaining = READ_MAX_CHARS - chars
                if remaining > 0:
                    clipped.append(line[:remaining])
                truncated = True
                break
            clipped.append(line)
            chars += len(line) + 1
        actual_end = start + len(clipped) - 1 if clipped else start - 1
        has_more = truncated or actual_end < end or end < line_count
        return ResultPage(
            text="\n".join(clipped),
            start_line=start,
            end_line=actual_end,
            line_count=line_count,
            truncated=truncated,
            next_start_line=actual_end + 1 if has_more and actual_end < line_count else None,
        )

    def _read_payload(self, row: Dict[str, Any]) -> str:
        content = self._fs_for_namespace(str(row["namespace"])).read(str(row["path"]))
        if content is None:
            raise KeyError(f"stored payload for {row['result_id']} is missing")
        return content

    async def _aread_payload(self, row: Dict[str, Any]) -> str:
        content = await self._fs_for_namespace(str(row["namespace"])).aread(str(row["path"]))
        if content is None:
            raise KeyError(f"stored payload for {row['result_id']} is missing")
        return content

    def read(self, result_id: str, start_line: int = 1, end_line: Optional[int] = None) -> ResultPage:
        """Read a page of a stored result. Lines are 1-indexed and inclusive."""
        row = self.get_row(result_id)
        if row is None:
            raise KeyError(f"unknown result id {result_id}")
        return self._page_from_content(self._read_payload(row), start_line, end_line)

    async def aread(self, result_id: str, start_line: int = 1, end_line: Optional[int] = None) -> ResultPage:
        """Async variant of ``read``."""
        row = await self.aget_row(result_id)
        if row is None:
            raise KeyError(f"unknown result id {result_id}")
        return self._page_from_content(await self._aread_payload(row), start_line, end_line)

    def _matches_from_content(self, content: str, pattern: str, context_lines: int) -> List[ResultMatch]:
        compiled = re.compile(pattern)
        lines = content.split("\n")
        matches: List[ResultMatch] = []
        for index, line in enumerate(lines):
            if len(matches) >= SEARCH_MAX_MATCHES:
                break
            if compiled.search(line) is None:
                continue
            if context_lines > 0:
                start = max(0, index - context_lines)
                end = min(len(lines), index + context_lines + 1)
                block = "\n".join(context_line[:SEARCH_LINE_CLIP] for context_line in lines[start:end])
                matches.append(ResultMatch(line_number=index + 1, line=block))
            else:
                matches.append(ResultMatch(line_number=index + 1, line=line[:SEARCH_LINE_CLIP]))
        return matches

    def search(self, result_id: str, pattern: str, context_lines: int = 0) -> List[ResultMatch]:
        """Regex search over a stored result; at most 20 matches, lines clipped."""
        row = self.get_row(result_id)
        if row is None:
            raise KeyError(f"unknown result id {result_id}")
        return self._matches_from_content(self._read_payload(row), pattern, context_lines)

    async def asearch(self, result_id: str, pattern: str, context_lines: int = 0) -> List[ResultMatch]:
        """Async variant of ``search``."""
        row = await self.aget_row(result_id)
        if row is None:
            raise KeyError(f"unknown result id {result_id}")
        return self._matches_from_content(await self._aread_payload(row), pattern, context_lines)

    # ------------------------------------------------------------------
    # Listing, cleanup, sweep
    # ------------------------------------------------------------------

    def live_ids(self, session_id: str, limit: int = 20) -> List[ResultRef]:
        """The session's stored results, newest first, capped at ``limit``.

        A context-compaction notice can list these so the model still knows
        which results it can read back after older messages are dropped.
        """
        rows = self._db_call("get_tool_results_for_session", session_id, limit)
        return [self._ref_from_row(row) for row in rows]

    async def alive_ids(self, session_id: str, limit: int = 20) -> List[ResultRef]:
        """Async variant of ``live_ids``."""
        rows = await self._adb_call("get_tool_results_for_session", session_id, limit)
        return [self._ref_from_row(row) for row in rows]

    def _delete_rows_and_payloads(self, rows: List[Dict[str, Any]]) -> int:
        for row in rows:
            try:
                self._fs_for_namespace(str(row["namespace"])).delete(str(row["path"]))
            except Exception as e:
                log_warning(f"Result payload delete failed for {row.get('result_id')}: {e}")
        if rows:
            self._db_call("delete_tool_results", [str(row["result_id"]) for row in rows])
        return len(rows)

    async def _adelete_rows_and_payloads(self, rows: List[Dict[str, Any]]) -> int:
        for row in rows:
            try:
                await self._fs_for_namespace(str(row["namespace"])).adelete(str(row["path"]))
            except Exception as e:
                log_warning(f"Result payload delete failed for {row.get('result_id')}: {e}")
        if rows:
            await self._adb_call("delete_tool_results", [str(row["result_id"]) for row in rows])
        return len(rows)

    def delete_for_sessions(self, session_ids: List[str]) -> int:
        """Delete every stored result of the given sessions: payloads first,
        then index rows. Returns the number of results removed."""
        rows: List[Dict[str, Any]] = []
        for session_id in session_ids:
            rows.extend(self._db_call("get_tool_results_for_session", session_id, None))
        return self._delete_rows_and_payloads(rows)

    async def adelete_for_sessions(self, session_ids: List[str]) -> int:
        """Async variant of ``delete_for_sessions``."""
        rows: List[Dict[str, Any]] = []
        for session_id in session_ids:
            rows.extend(await self._adb_call("get_tool_results_for_session", session_id, None))
        return await self._adelete_rows_and_payloads(rows)

    def sweep_expired(self, now: Optional[int] = None) -> int:
        """Delete results whose ``expires_at`` has passed. Returns the count."""
        rows = self._db_call("get_expired_tool_results", int(now if now is not None else time.time()))
        return self._delete_rows_and_payloads(rows)

    async def asweep_expired(self, now: Optional[int] = None) -> int:
        """Async variant of ``sweep_expired``."""
        rows = await self._adb_call("get_expired_tool_results", int(now if now is not None else time.time()))
        return await self._adelete_rows_and_payloads(rows)

    def maybe_sweep(self, session_id: str) -> None:
        """Run the TTL sweep at most once per session per store instance."""
        if not self.ttl_seconds or session_id in self._swept_sessions:
            return
        self._swept_sessions.add(session_id)
        try:
            swept = self.sweep_expired()
            if swept:
                log_debug(f"Result offloading: swept {swept} expired results")
        except Exception as e:
            log_warning(f"Result TTL sweep failed: {e}")

    async def amaybe_sweep(self, session_id: str) -> None:
        """Async variant of ``maybe_sweep``."""
        if not self.ttl_seconds or session_id in self._swept_sessions:
            return
        self._swept_sessions.add(session_id)
        try:
            swept = await self.asweep_expired()
            if swept:
                log_debug(f"Result offloading: swept {swept} expired results")
        except Exception as e:
            log_warning(f"Result TTL sweep failed: {e}")
