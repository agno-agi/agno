"""The read-back tools an offloaded result is reachable through.

``owner`` is the Agent or Team the tool is registered on; the store is read
off it at call time so a store built later in the run is still picked up.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from agno.run import RunContext
from agno.tools.function import Function

OFFLOAD_INSTRUCTION = (
    "Large tool results are stored as files and shown to you as a short preview with a "
    "result id. The preview is not the whole result. Use search_result to locate what you "
    "need and read_result to read that range; do not answer from the preview when the "
    "preview was truncated."
)


def _access_error(result_id: str, row: Optional[Dict[str, Any]], run_context: RunContext) -> Optional[str]:
    """The error string when the id is unknown or out of reach, else None."""
    if row is None:
        return f"Error: unknown result id {result_id}"
    # A stored result is served only to its own session. A team leader and its
    # members share one session id, so a member reads what another member
    # stored and nothing from any other session.
    if str(row.get("session_id")) != str(run_context.session_id):
        return f"Error: result {result_id} belongs to a different session"
    # A session id can be supplied by the caller, so one session id can be
    # reached by two users. When both sides name a user, they must match.
    row_user = row.get("user_id")
    if row_user is not None and run_context.user_id is not None and str(row_user) != str(run_context.user_id):
        return f"Error: result {result_id} belongs to a different user"
    return None


def get_read_result_function(owner: Any, run_context: RunContext, async_mode: bool = False) -> Function:
    """Factory for the read_result tool (result offloading)."""

    owner_kind = type(owner).__name__.lower()

    def _resolve(result_id: str, row: Optional[Dict[str, Any]]) -> Optional[str]:
        return _access_error(result_id, row, run_context)

    def _render(result_id: str, page: Any) -> str:
        header = f"Result {result_id}, lines {page.start_line}-{page.end_line} of {page.line_count}."
        if page.next_start_line is not None:
            if page.next_start_char:
                header += (
                    f" More follows: line {page.next_start_line} continues; read from line "
                    f"{page.next_start_line} with start_char={page.next_start_char}."
                )
            else:
                header += f" More follows: read from line {page.next_start_line}."
        return f"{header}\n{page.text}"

    def read_result(result_id: str, start_line: int = 1, end_line: Optional[int] = None, start_char: int = 0) -> str:
        """Read a stored tool result. Lines are 1-indexed and inclusive.

        Output is capped at 400 lines or 16000 characters, whichever comes first;
        the reply names where to continue when there is more. A line longer than
        one page is read in pieces: continue with the start_char the reply names.

        Args:
            result_id: The id from the result envelope, e.g. "res_a91c4f20b3".
            start_line: First line to read (1-indexed, default 1).
            end_line: Last line to read (inclusive). Defaults to the end.
            start_char: Character offset into start_line to begin at (0-indexed, default 0).

        Returns:
            str: The requested lines, or an error message starting with "Error".
        """
        store = owner._result_store
        if store is None:
            return f"Error: result offloading is not enabled for this {owner_kind}"
        try:
            error = _resolve(result_id, store.get_row(result_id))
            if error is not None:
                return error
            return _render(result_id, store.read(result_id, start_line, end_line, start_char))
        except Exception as e:
            return f"Error reading result: {e}"

    async def aread_result(
        result_id: str, start_line: int = 1, end_line: Optional[int] = None, start_char: int = 0
    ) -> str:
        """Read a stored tool result. Lines are 1-indexed and inclusive.

        Output is capped at 400 lines or 16000 characters, whichever comes first;
        the reply names where to continue when there is more. A line longer than
        one page is read in pieces: continue with the start_char the reply names.

        Args:
            result_id: The id from the result envelope, e.g. "res_a91c4f20b3".
            start_line: First line to read (1-indexed, default 1).
            end_line: Last line to read (inclusive). Defaults to the end.
            start_char: Character offset into start_line to begin at (0-indexed, default 0).

        Returns:
            str: The requested lines, or an error message starting with "Error".
        """
        store = owner._result_store
        if store is None:
            return f"Error: result offloading is not enabled for this {owner_kind}"
        try:
            error = _resolve(result_id, await store.aget_row(result_id))
            if error is not None:
                return error
            return _render(result_id, await store.aread(result_id, start_line, end_line, start_char))
        except Exception as e:
            return f"Error reading result: {e}"

    entrypoint = aread_result if async_mode else read_result
    return Function.from_callable(entrypoint, name="read_result")  # type: ignore[arg-type]


def get_search_result_function(owner: Any, run_context: RunContext, async_mode: bool = False) -> Function:
    """Factory for the search_result tool (result offloading)."""

    owner_kind = type(owner).__name__.lower()

    def _resolve(result_id: str, row: Optional[Dict[str, Any]]) -> Optional[str]:
        return _access_error(result_id, row, run_context)

    def _render(result_id: str, matches: Any) -> str:
        from agno.offload.store import SEARCH_MAX_MATCHES

        if not matches:
            return f"No matches in {result_id}."
        if matches[-1].more or len(matches) >= SEARCH_MAX_MATCHES:
            lines = [f"First {len(matches)} matches in {result_id} (more follow; narrow the pattern):"]
        else:
            lines = [f"{len(matches)} match(es) in {result_id}:"]
        for match in matches:
            if "\n" in match.line:
                lines.append(f"match at line {match.line_number} (char {match.char_offset}):\n{match.line}")
            elif match.line.startswith("...") or match.line.endswith("..."):
                lines.append(f"{match.line_number} (char {match.char_offset}): {match.line}")
            else:
                lines.append(f"{match.line_number}: {match.line}")
        return "\n".join(lines)

    def search_result(result_id: str, pattern: str, context_lines: int = 0) -> str:
        """Search a stored tool result with a regular expression.

        Returns at most 20 matches as line-number/line pairs, each line clipped to 500
        characters. Use read_result with the reported line numbers to read around a match.

        Args:
            result_id: The id from the result envelope, e.g. "res_a91c4f20b3".
            pattern: A Python regular expression.
            context_lines: Lines of context to include around each match (at most 20).

        A long line is shown as a window around the match with its character
        offset; read the rest with read_result(start_line, start_char=offset).

        Returns:
            str: The matches, or an error message starting with "Error".
        """
        store = owner._result_store
        if store is None:
            return f"Error: result offloading is not enabled for this {owner_kind}"
        try:
            error = _resolve(result_id, store.get_row(result_id))
            if error is not None:
                return error
            return _render(result_id, store.search(result_id, pattern, context_lines))
        except re.error as e:
            return f"Error: invalid regular expression: {e}"
        except Exception as e:
            return f"Error searching result: {e}"

    async def asearch_result(result_id: str, pattern: str, context_lines: int = 0) -> str:
        """Search a stored tool result with a regular expression.

        Returns at most 20 matches as line-number/line pairs, each line clipped to 500
        characters. Use read_result with the reported line numbers to read around a match.

        Args:
            result_id: The id from the result envelope, e.g. "res_a91c4f20b3".
            pattern: A Python regular expression.
            context_lines: Lines of context to include around each match (at most 20).

        A long line is shown as a window around the match with its character
        offset; read the rest with read_result(start_line, start_char=offset).

        Returns:
            str: The matches, or an error message starting with "Error".
        """
        store = owner._result_store
        if store is None:
            return f"Error: result offloading is not enabled for this {owner_kind}"
        try:
            error = _resolve(result_id, await store.aget_row(result_id))
            if error is not None:
                return error
            return _render(result_id, await store.asearch(result_id, pattern, context_lines))
        except re.error as e:
            return f"Error: invalid regular expression: {e}"
        except Exception as e:
            return f"Error searching result: {e}"

    entrypoint = asearch_result if async_mode else search_result
    return Function.from_callable(entrypoint, name="search_result")  # type: ignore[arg-type]


__all__ = ["OFFLOAD_INSTRUCTION", "get_read_result_function", "get_search_result_function"]
