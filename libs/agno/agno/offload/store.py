"""ResultStore — big tool results become AgentFS files, not messages.

When a tool result crosses the threshold, the full payload is written to
AgentFS (one namespace per session) and the transcript gets a
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
from agno.offload.types import NEVER_OFFLOADED_TOOLS, ResultMatch, ResultPage, ResultRef
from agno.utils.log import log_debug, log_warning
from agno.utils.string import hash_string_sha256

# Per-result and per-session-namespace quotas, raised from the AgentFS
# defaults for this store.
MAX_RESULT_BYTES = 8_000_000
MAX_SESSION_NAMESPACE_BYTES = 200_000_000
MAX_CALL_ID_ATTEMPTS = 1000

# read_result caps: whichever binds first.
READ_MAX_LINES = 400
READ_MAX_CHARS = 16_000
# A result below one read_result page costs more to read back than to keep inline.
DEFAULT_THRESHOLD_CHARS = READ_MAX_CHARS
SEARCH_MAX_CHARS = READ_MAX_CHARS
DEFAULT_PREVIEW_LINES = 20
DEFAULT_PREVIEW_CHARS = 1200

# search_result caps.
SEARCH_MAX_MATCHES = 20
SEARCH_MAX_CONTEXT_LINES = 20
SEARCH_LINE_CLIP = 500
_MATCH_HEADER_CHARS = 48
# The pattern is model-supplied and Python's re has no timeout, so a pattern
# that backtracks catastrophically would otherwise hang the run for good. A
# pattern that can backtrack runs in a subprocess killed at this deadline.
SEARCH_TIMEOUT_SECONDS = 10.0
# A pattern with none of these cannot blow up: backtracking needs repetition
# (or a group a repetition can apply to), so everything else scans in-process.
_BACKTRACKING_CHARS = frozenset("*+?{(")

_TAIL_LINES = 5

# The longest one store instance waits between TTL sweeps. A shorter TTL
# sweeps at its own length instead.
SWEEP_INTERVAL_SECONDS = 300
DELETE_BATCH_SIZE = 500


def _canonical_args_hash(tool_args: Optional[Dict[str, Any]]) -> str:
    try:
        canonical = json.dumps(tool_args or {}, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        canonical = str(tool_args)
    return hash_string_sha256(canonical)


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


def _clip_around(line: str, char_offset: int, match_len: int = 1) -> str:
    """The line clipped to the search clip, as a window around the match.

    A line shorter than the clip is returned whole. A longer one is shown
    from a little before the match, with ellipses marking cut ends, so the
    match itself is always inside the window whatever its position.
    """
    if len(line) <= SEARCH_LINE_CLIP:
        return line
    width = SEARCH_LINE_CLIP - 6
    lead = width // 4
    start = max(0, min(char_offset - lead, len(line) - width))
    need_end = char_offset + min(max(match_len, 1), width)
    if start + width < need_end:
        start = min(need_end - width, len(line) - width)
    head = "..." if start > 0 else ""
    tail = "..." if start + width < len(line) else ""
    return f"{head}{line[start : start + width]}{tail}"


def _find_match_positions(
    lines: List[str], compiled: "re.Pattern[str]", limit: int
) -> Tuple[List[Tuple[int, int, int]], bool]:
    """(1-indexed line number, char offset, match length) for each matching
    line, capped at ``limit``; the flag is True when one more match exists."""
    positions: List[Tuple[int, int, int]] = []
    for index, line in enumerate(lines):
        found = compiled.search(line)
        if found is None:
            continue
        if len(positions) >= limit:
            return positions, True
        positions.append((index + 1, found.start(), found.end() - found.start()))
    return positions, False


def _render_matches(
    lines: List[str], positions: List[Tuple[int, int, int]], more: bool, context_lines: int
) -> List[ResultMatch]:
    """Match positions become the clipped, budgeted reply.

    One renderer serves the in-process and the subprocess scans, so the reply
    is the same whichever lane found the positions. The whole reply stays
    within one read_result page, whatever the context asked for, so a search
    can never put back what offloading took out.
    """
    context_lines = max(0, min(int(context_lines or 0), SEARCH_MAX_CONTEXT_LINES))
    matches: List[ResultMatch] = []
    budget = SEARCH_MAX_CHARS
    stopped_early = False
    for line_number, char_offset, match_len in positions:
        if matches and budget <= _MATCH_HEADER_CHARS:
            # This match exists but no longer fits the reply budget.
            stopped_early = True
            break
        index = line_number - 1
        if context_lines > 0:
            start = max(0, index - context_lines)
            end = min(len(lines), index + context_lines + 1)
            # Each row carries its own line number, so the block reads the
            # same way a read_result page does and the match line is clear.
            text = "\n".join(
                f"{start + offset + 1}: {_clip_around(context_line, char_offset if start + offset == index else 0, match_len)}"
                for offset, context_line in enumerate(lines[start:end])
            )
        else:
            text = _clip_around(lines[index], char_offset, match_len)
        # Each match is rendered with a short header line; reserve room
        # for it so the reply the model sees stays within one page.
        budget -= _MATCH_HEADER_CHARS
        if len(text) > budget:
            text = text[:budget]
        budget -= len(text) + 1
        matches.append(ResultMatch(line_number=line_number, line=text, char_offset=char_offset))
    if matches and (more or stopped_early):
        matches[-1].more = True
    return matches


def _scan_for_matches(content: str, pattern: str, context_lines: int) -> List[ResultMatch]:
    """The search scan itself: at most 20 matches, one read_result page in total."""
    lines = content.split("\n")
    positions, more = _find_match_positions(lines, re.compile(pattern), SEARCH_MAX_MATCHES)
    return _render_matches(lines, positions, more, context_lines)


def _scan_in_subprocess(content: str, pattern: str, context_lines: int) -> List[ResultMatch]:
    """Run the match scan in a separate interpreter, killed at ``SEARCH_TIMEOUT_SECONDS``.

    A thread stuck inside the regex engine cannot be interrupted, so a pattern
    that can backtrack runs where a deadline can actually kill it. The child is
    ``agno/offload/_scan.py`` run in isolated mode: it imports the standard
    library only, so nothing of the caller is re-executed and nothing of the
    caller's environment is visible. The pattern and the payload travel as one
    JSON document on stdin. ``communicate`` owns the pipes, so the deadline
    covers the whole exchange, including a payload larger than one pipe buffer.
    """
    import subprocess
    import sys
    from pathlib import Path

    scan_script = Path(__file__).with_name("_scan.py")
    if not scan_script.is_file():
        # An installation this file cannot read from disk (a zipapp, say)
        # keeps working, without the deadline.
        log_warning(f"Result search: {scan_script} is missing; the scan runs in-process without a time limit")
        return _scan_for_matches(content, pattern, context_lines)

    payload = json.dumps({"pattern": pattern, "content": content, "limit": SEARCH_MAX_MATCHES})
    process = subprocess.Popen(
        [sys.executable, "-I", str(scan_script)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = process.communicate(payload, timeout=SEARCH_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise TimeoutError(
            f"the search did not finish within {int(SEARCH_TIMEOUT_SECONDS)}s; the pattern "
            "backtracks too much on this result - simplify it or search with a plainer pattern"
        )
    detail = (stderr or "").strip()[:300]
    if process.returncode != 0:
        raise RuntimeError(f"the search scan failed: {detail or f'exit code {process.returncode}'}")
    try:
        data = json.loads(stdout)
    except ValueError:
        raise RuntimeError(f"the search scan returned no result: {detail or 'empty reply'}")
    lines = content.split("\n")
    positions = [
        (int(line_number), int(char_offset), int(match_len))
        for line_number, char_offset, match_len in data["positions"]
    ]
    return _render_matches(lines, positions, bool(data["more"]), context_lines)


def _head_preview(output: str, preview_lines: int, preview_chars: int) -> str:
    """First ``preview_lines`` lines or ``preview_chars`` chars, whichever binds first."""
    head = "\n".join(output.split("\n")[:preview_lines])
    if len(head) > preview_chars:
        head = head[:preview_chars]
    return head


def _preview_block(output: str, preview_lines: int, preview_chars: int) -> str:
    """The preview an envelope shows: the head, and the tail when lines were cut.

    Errors, totals and summaries live at the end of a result, so a head-only
    preview hides exactly the lines a model most often needs. The tail is
    capped like the head, and the omitted count says what sits between them.
    """
    lines = output.split("\n")
    head = _head_preview(output, preview_lines, preview_chars)
    lines_omitted = len(lines) - len(head.split("\n")) - _TAIL_LINES
    # The head can also be cut mid-stream by the character cap, on a payload
    # of a few very long lines - the common oversized single-line JSON case -
    # where no whole line was dropped but most of the bytes were.
    chars_omitted = len(output) - len(head) - min(len(output), preview_chars)
    if lines_omitted <= 0 and chars_omitted <= 0:
        return head
    if lines_omitted > 0:
        tail = "\n".join(lines[-_TAIL_LINES:])
        marker = f"[... {lines_omitted} lines omitted ...]"
    else:
        tail = output[-min(len(output), preview_chars) :]
        marker = "[... omitted ...]"
    if len(tail) > preview_chars:
        tail = "..." + tail[-preview_chars:]
    return f"{head}\n{marker}\n{tail}"


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
        tail = "\n".join(lines[-_TAIL_LINES:])
        # The tail is capped like the head: a refused envelope must never be
        # the size of the payload it stands in for.
        if len(tail) > preview_chars:
            tail = "..." + tail[-preview_chars:]
        parts.append(tail)
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


def _safe_segment(value: str) -> str:
    """Make a caller-supplied id safe as one path segment."""
    cleaned = re.sub(r"[\\/\x00-\x1f]", "_", value) or "_"
    return cleaned[:120]


_NAMESPACE_UNSAFE = re.compile(r"[^a-z0-9._@+-]")
_NAMESPACE_HASH_CHARS = 8


def namespace_for(session_id: str, scope: str = "") -> str:
    """The AgentFS namespace holding one session's payloads.

    The readable part is lowercased and reduced to the characters AgentFS keeps
    as they are, so the namespace written on an index row is the one AgentFS
    resolves on read and delete. Two session ids can reduce to the same text;
    the hash suffix keeps them apart. Without it, deleting one session would
    delete the other's payloads and leave its index rows pointing at nothing.
    ``scope`` is the database schema the index lives in: on PostgreSQL the
    payload table is shared by every schema of one database, and the scope
    keeps two schemas that reuse a session id from sharing payload rows.
    The segment stays within the AgentFS segment limit with the suffix added.
    """
    limit = MAX_SEGMENT_CHARS - _NAMESPACE_HASH_CHARS - 1
    readable = _NAMESPACE_UNSAFE.sub("_", session_id.lower())[:limit] or "_"
    digest = hash_string_sha256(f"{scope}:{session_id}" if scope else session_id)
    return f"tool-results/{readable}-{digest[:_NAMESPACE_HASH_CHARS]}"


class ResultStore:
    """Stores oversized tool results as AgentFS files with a small index table.

    This is also the settings object: pass one as
    ``Agent(offload_tool_results=ResultStore(...))`` or
    ``Team(offload_tool_results=ResultStore(...))`` to set the threshold, the
    preview size, the lifetime, or where payloads live. ``db`` is taken from
    the agent or team when unset. The object passed is never modified: it is
    bound to the owner's db as a copy, and that copy is the owner's
    ``.result_store``. A member store inside a team keeps its settings only;
    payloads go to the team's database so the whole team can read them.

    Usable without an agent. The sync and ``a``-prefixed async surfaces are
    equivalent; the async one uses the db's native async methods when the db
    is async, and worker threads otherwise.
    """

    def __init__(
        self,
        *,
        db: Optional[Any] = None,
        fs: Optional[FileSystem] = None,
        threshold_chars: int = DEFAULT_THRESHOLD_CHARS,
        preview_lines: int = DEFAULT_PREVIEW_LINES,
        preview_chars: int = DEFAULT_PREVIEW_CHARS,
        ttl_seconds: Optional[int] = None,
        member_responses: bool = True,
    ) -> None:
        if threshold_chars < 1:
            raise ValueError("ResultStore threshold_chars must be at least 1")
        self._fs = fs
        self.db = db
        # Results longer than this many characters are stored. The default
        # matches what one read_result call returns, so a stored result is
        # never cheaper to read back in one piece than it was to leave inline.
        self.threshold_chars = threshold_chars
        self.preview_lines = preview_lines
        self.preview_chars = preview_chars
        self.ttl_seconds = ttl_seconds
        # Team only. A member's answer reaches the leader as a tool result and
        # is offloaded either way; this covers the member's own stored run.
        self.member_responses = member_responses
        self._last_sweep_at: float = 0.0

    @property
    def fs(self) -> FileSystem:
        """The filesystem, built from ``db`` on first use when none was given."""
        if self._fs is None:
            if self.db is None:
                raise RuntimeError("ResultStore needs a db or a FileSystem")
            from agno.fs import FileSystem as _FileSystem

            self._fs = _FileSystem(backend=self.db, namespace="tool-results")
        return self._fs

    def bound(self, db: Optional[Any]) -> "ResultStore":
        """A copy of these settings bound to ``db`` when this store has none.

        The settings object a user passes is never modified, so one
        ``ResultStore`` can configure several agents on different databases.
        """
        return ResultStore(
            db=self.db if self.db is not None else db,
            fs=self._fs,
            threshold_chars=self.threshold_chars,
            preview_lines=self.preview_lines,
            preview_chars=self.preview_chars,
            ttl_seconds=self.ttl_seconds,
            member_responses=self.member_responses,
        )

    def to_dict(self) -> Dict[str, Any]:
        """The settings, without db or fs; those are supplied at build time."""
        data: Dict[str, Any] = {}
        if self.threshold_chars != DEFAULT_THRESHOLD_CHARS:
            data["threshold_chars"] = self.threshold_chars
        if self.preview_lines != DEFAULT_PREVIEW_LINES:
            data["preview_lines"] = self.preview_lines
        if self.preview_chars != DEFAULT_PREVIEW_CHARS:
            data["preview_chars"] = self.preview_chars
        if self.ttl_seconds is not None:
            data["ttl_seconds"] = self.ttl_seconds
        if not self.member_responses:
            data["member_responses"] = False
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResultStore":
        return cls(**data)

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

    @property
    def _namespace_scope(self) -> str:
        return str(getattr(self.db, "db_schema", None) or "")

    def _session_fs(self, session_id: str) -> FileSystem:
        return FileSystem(
            backend=self.fs.backend,
            namespace=namespace_for(session_id, self._namespace_scope),
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
            "preview": _preview_block(output, self.preview_lines, self.preview_chars),
            "user_id": user_id,
            "created_at": created_at,
            "expires_at": created_at + self.ttl_seconds if self.ttl_seconds else None,
        }

    def _plan(self, *, session_id: str, run_id: str, tool_call_id: str, output: str, shared: bool) -> Tuple[str, str]:
        """(path, content_type) for a payload.

        The file is named by the result id, so two results can never share a
        path: the index has a unique constraint on (namespace, path), and a
        path built from a sanitised tool call id would collide for two ids that
        differ only in a character sanitising replaces.
        """
        content_type = "json" if _looks_like_json(output) else "text"
        extension = "json" if content_type == "json" else "txt"
        prefix = "shared" if shared else "results"
        result_id = result_id_for(session_id, run_id, tool_call_id)
        path = f"{prefix}/{_safe_segment(run_id)}/{result_id}.{extension}"
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
        path, content_type = self._plan(
            session_id=session_id, run_id=run_id, tool_call_id=tool_call_id, output=output, shared=shared
        )
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
        path, content_type = self._plan(
            session_id=session_id, run_id=run_id, tool_call_id=tool_call_id, output=output, shared=shared
        )
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
        return len(output) > self.threshold_chars

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
        self.maybe_sweep()
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
            return render_stored_envelope(ref, _preview_block(output, self.preview_lines, self.preview_chars))
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
        await self.amaybe_sweep()
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
            return render_stored_envelope(ref, _preview_block(output, self.preview_lines, self.preview_chars))
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

    def _page_from_content(
        self, content: str, start_line: int, end_line: Optional[int], start_char: int = 0
    ) -> ResultPage:
        lines = content.split("\n")
        line_count = len(lines)
        start = min(max(1, start_line), line_count)
        end = line_count if end_line is None else min(max(end_line, start), line_count)
        offset = max(0, start_char)
        pieces: List[str] = []
        chars = 0
        truncated = False
        last_included = start - 1
        next_line: Optional[int] = None
        next_char = 0
        current = start
        while current <= end:
            if len(pieces) >= READ_MAX_LINES:
                truncated = True
                next_line = current
                break
            skip = offset if current == start else 0
            line = lines[current - 1][skip:]
            separator = 1 if pieces else 0
            room = READ_MAX_CHARS - chars - separator
            if len(line) > room:
                # The line does not fit. Take what fits and continue inside
                # this line on the next page, so no character is ever lost.
                if room > 0:
                    pieces.append(line[:room])
                    chars += room + separator
                    last_included = current
                truncated = True
                next_line = current
                next_char = skip + max(room, 0)
                break
            pieces.append(line)
            chars += len(line) + separator
            last_included = current
            current += 1
        if next_line is None and end < line_count:
            next_line, next_char = end + 1, 0
        return ResultPage(
            text="\n".join(pieces),
            start_line=start,
            end_line=last_included,
            line_count=line_count,
            truncated=truncated,
            next_start_line=next_line,
            next_start_char=next_char,
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

    def payload(self, result_id: str) -> str:
        """The full stored text of a result. For code, not for a transcript.

        The read-back TOOLS stay capped - a page can never put back what
        offloading took out of the model's context - but code computing over
        a result (a CodeMode cell binding it to a variable) needs the whole
        text, bounded only by the per-result store limit.
        """
        row = self.get_row(result_id)
        if row is None:
            raise KeyError(f"unknown result id {result_id}")
        return self._read_payload(row)

    async def apayload(self, result_id: str) -> str:
        """Async variant of ``payload``."""
        row = await self.aget_row(result_id)
        if row is None:
            raise KeyError(f"unknown result id {result_id}")
        return await self._aread_payload(row)

    def read(
        self, result_id: str, start_line: int = 1, end_line: Optional[int] = None, start_char: int = 0
    ) -> ResultPage:
        """Read a page of a stored result. Lines are 1-indexed and inclusive;
        ``start_char`` is the 0-indexed offset into ``start_line`` to begin at."""
        row = self.get_row(result_id)
        if row is None:
            raise KeyError(f"unknown result id {result_id}")
        return self._page_from_content(self._read_payload(row), start_line, end_line, start_char)

    async def aread(
        self, result_id: str, start_line: int = 1, end_line: Optional[int] = None, start_char: int = 0
    ) -> ResultPage:
        """Async variant of ``read``."""
        row = await self.aget_row(result_id)
        if row is None:
            raise KeyError(f"unknown result id {result_id}")
        content = await self._aread_payload(row)
        return await asyncio.to_thread(self._page_from_content, content, start_line, end_line, start_char)

    def _matches_from_content(self, content: str, pattern: str, context_lines: int) -> List[ResultMatch]:
        # Compiled here first so an invalid pattern raises re.error in the
        # caller, where the tool layer names it, never out of the subprocess.
        re.compile(pattern)
        if _BACKTRACKING_CHARS.isdisjoint(pattern):
            return _scan_for_matches(content, pattern, context_lines)
        # The pattern can repeat, so it can backtrack without bound. It runs
        # in a subprocess a deadline can actually kill: a thread stuck inside
        # the regex engine cannot be interrupted.
        return _scan_in_subprocess(content, pattern, context_lines)

    def search(self, result_id: str, pattern: str, context_lines: int = 0) -> List[ResultMatch]:
        """Regex search over a stored result; at most 20 matches, lines clipped, one page in total."""
        row = self.get_row(result_id)
        if row is None:
            raise KeyError(f"unknown result id {result_id}")
        return self._matches_from_content(self._read_payload(row), pattern, context_lines)

    async def asearch(self, result_id: str, pattern: str, context_lines: int = 0) -> List[ResultMatch]:
        """Async variant of ``search``."""
        row = await self.aget_row(result_id)
        if row is None:
            raise KeyError(f"unknown result id {result_id}")
        # The regex scan is CPU work over the whole payload; it runs off the loop.
        content = await self._aread_payload(row)
        return await asyncio.to_thread(self._matches_from_content, content, pattern, context_lines)

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
        # Index rows are deleted in batches: the delete binds one parameter per
        # id and SQLite allows 32,766 of them. Each batch removes its payloads
        # and its rows together, so a failure part way leaves no row whose
        # payload is already gone.
        for batch_start in range(0, len(rows), DELETE_BATCH_SIZE):
            batch = rows[batch_start : batch_start + DELETE_BATCH_SIZE]
            for row in batch:
                try:
                    self._fs_for_namespace(str(row["namespace"])).delete(str(row["path"]))
                except Exception as e:
                    log_warning(f"Result payload delete failed for {row.get('result_id')}: {e}")
            self._db_call("delete_tool_results", [str(row["result_id"]) for row in batch])
        return len(rows)

    async def _adelete_rows_and_payloads(self, rows: List[Dict[str, Any]]) -> int:
        for batch_start in range(0, len(rows), DELETE_BATCH_SIZE):
            batch = rows[batch_start : batch_start + DELETE_BATCH_SIZE]
            for row in batch:
                try:
                    await self._fs_for_namespace(str(row["namespace"])).adelete(str(row["path"]))
                except Exception as e:
                    log_warning(f"Result payload delete failed for {row.get('result_id')}: {e}")
            await self._adb_call("delete_tool_results", [str(row["result_id"]) for row in batch])
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

    def _sweep_is_due(self) -> bool:
        """True at most once every SWEEP_INTERVAL_SECONDS, and only with a TTL.

        The sweep is store-wide, not per session, so it is paced by time rather
        than by how many sessions the store has seen.
        """
        if not self.ttl_seconds:
            return False
        now = time.time()
        if now - self._last_sweep_at < min(SWEEP_INTERVAL_SECONDS, self.ttl_seconds):
            return False
        self._last_sweep_at = now
        return True

    def maybe_sweep(self) -> None:
        """Run the TTL sweep when one is due."""
        if not self._sweep_is_due():
            return
        try:
            swept = self.sweep_expired()
            if swept:
                log_debug(f"Result offloading: swept {swept} expired results")
        except Exception as e:
            log_warning(f"Result TTL sweep failed: {e}")

    async def amaybe_sweep(self) -> None:
        """Async variant of ``maybe_sweep``."""
        if not self._sweep_is_due():
            return
        try:
            swept = await self.asweep_expired()
            if swept:
                log_debug(f"Result offloading: swept {swept} expired results")
        except Exception as e:
            log_warning(f"Result TTL sweep failed: {e}")
