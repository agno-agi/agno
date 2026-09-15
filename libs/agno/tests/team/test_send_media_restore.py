"""
Regression test for agno issue #9989:
Team.send_media_to_model=False permanently mutates member agents.

Both _default_tools.py and _task_tools.py wrote
    member_agent.send_media_to_model = False
without ever restoring the original value. After a team delegation the
member's own setting was permanently overwritten.

Fix: save the original value before the delegation and restore it in a
finally block so the mutation never outlives the run.
"""
import inspect
import pytest


def _get_source(module_path: str) -> str:
    import importlib.util, pathlib
    p = pathlib.Path(module_path)
    return p.read_text()


def _agno_team_path(filename: str) -> str:
    import agno.team._default_tools as _dt
    import pathlib
    base = pathlib.Path(_dt.__file__).parent
    return str(base / filename)


def test_default_tools_saves_and_restores_send_media_to_model():
    """
    _default_tools.py must save send_media_to_model before overwriting it
    and restore it in a finally block.
    """
    src = _get_source(_agno_team_path("_default_tools.py"))
    lines = src.split("\n")

    save_line = next(
        (i for i, l in enumerate(lines) if "_orig_send_media_dt = member_agent.send_media_to_model" in l),
        None,
    )
    restore_line = next(
        (i for i, l in enumerate(lines) if "member_agent.send_media_to_model = _orig_send_media_dt" in l),
        None,
    )
    finally_line = next(
        (i for i, l in enumerate(lines) if l.strip() == "finally:" and restore_line is not None and i < restore_line),
        None,
    )

    assert save_line is not None, (
        "_default_tools.py must save member_agent.send_media_to_model before overwriting it"
    )
    assert restore_line is not None, (
        "_default_tools.py must restore member_agent.send_media_to_model after delegation"
    )
    assert finally_line is not None, (
        "_default_tools.py restore must be inside a finally block"
    )
    assert save_line < restore_line, "save must precede restore"


def test_task_tools_saves_and_restores_send_media_to_model():
    """
    _task_tools.py must save send_media_to_model before overwriting it
    and restore it in finally blocks at every call site.
    """
    src = _get_source(_agno_team_path("_task_tools.py"))
    lines = src.split("\n")

    save_lines = [i for i, l in enumerate(lines) if "_orig_send_media" in l and "= member_agent.send_media_to_model" in l]
    restore_lines = [i for i, l in enumerate(lines) if "member_agent.send_media_to_model = _orig_send_media" in l]
    finally_lines = [i for i, l in enumerate(lines) if l.strip() == "finally:"]

    assert len(save_lines) >= 2, (
        f"_task_tools.py must save send_media_to_model at multiple call sites, found {len(save_lines)}"
    )
    assert len(restore_lines) >= 2, (
        f"_task_tools.py must restore send_media_to_model at multiple call sites, found {len(restore_lines)}"
    )
    # Each restore must be preceded by a finally
    for r in restore_lines:
        preceding_finally = any(f < r and f > r - 5 for f in finally_lines)
        assert preceding_finally, f"restore at line {r+1} must be inside a finally block"


def test_send_media_not_mutated_after_delegation():
    """
    Verify the fix at the source level: the if-block that sets
    member_agent.send_media_to_model = False must be preceded by a save
    and followed (eventually) by a restore in a finally.
    """
    for filename in ("_default_tools.py", "_task_tools.py"):
        src = _get_source(_agno_team_path(filename))
        # The mutation line must exist
        assert "member_agent.send_media_to_model = False" in src, (
            f"{filename} must contain the send_media_to_model propagation"
        )
        # A save must exist
        assert "= member_agent.send_media_to_model" in src, (
            f"{filename} must save the original send_media_to_model value"
        )
        # A restore must exist
        assert "member_agent.send_media_to_model = _orig_send_media" in src, (
            f"{filename} must restore send_media_to_model after delegation"
        )
