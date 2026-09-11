"""Application debug output must not enable pool chatter or terminal wrapping."""

import io
import logging
import subprocess
import sys
import textwrap
from uuid import uuid4

import pytest
from rich.logging import RichHandler
from sqlalchemy import create_engine

from agno.db.postgres._bounded import bounded_engine
from agno.utils.log import build_logger, center_header


def test_import_and_headers_without_stdout():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent("""
            import sys
            sys.stdout = None
            from agno.agent import Agent
            from agno.utils.log import center_header
            assert center_header("probe") == "probe"
        """),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_jupyter_keeps_rich_handler():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent("""
            import builtins
            builtins.get_ipython = lambda: type("ZMQInteractiveShell", (), {})()
            from agno.utils.log import agent_logger
            from rich.logging import RichHandler
            handler = agent_logger.handlers[0]
            assert isinstance(handler, RichHandler)
            assert handler.console.is_jupyter
        """),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("terminal", [False, True])
def test_default_handler_matches_output_destination(monkeypatch, terminal):
    output = io.StringIO()
    monkeypatch.setattr(output, "isatty", lambda: terminal)
    monkeypatch.setattr("sys.stdout", output)
    logger = build_logger("agno.test_" + uuid4().hex)
    try:
        assert isinstance(logger.handlers[0], RichHandler) is terminal
        message = "Storage ready: " + "x" * 200
        logger.info(message)
        if not terminal:
            assert output.getvalue() == f"INFO    {message}\n"
            assert center_header("Session: example") == "Session: example"
    finally:
        logger.handlers.clear()


def test_existing_application_handler_and_level_are_preserved():
    logger = logging.getLogger("agno.test_" + uuid4().hex)
    handler = logging.NullHandler()
    logger.addHandler(handler)
    logger.setLevel(logging.ERROR)
    assert build_logger(logger.name) is logger
    assert logger.handlers == [handler]
    assert logger.level == logging.ERROR


def test_pool_debug_is_independent_and_remains_opt_in(caplog):
    source = create_engine("postgresql+psycopg://unused:unused@localhost/unused")
    pool = bounded_engine(source, capacity=1).pool
    assert pool.logger.name.startswith("sqlalchemy.pool.")
    with caplog.at_level(logging.DEBUG, logger="agno"):
        assert not pool.logger.isEnabledFor(logging.DEBUG)
        pool.logger.debug("pool noise")
        pool.logger.warning("pool unavailable")
    assert "pool noise" not in caplog.text
    assert "pool unavailable" in caplog.text
    with caplog.at_level(logging.DEBUG, logger="sqlalchemy.pool"):
        pool.logger.debug("explicit pool diagnostics")
        assert pool.recreate().logger.isEnabledFor(logging.DEBUG)
    assert "explicit pool diagnostics" in caplog.text


def test_bounded_pool_preserves_explicit_echo():
    source = create_engine("postgresql+psycopg://unused:unused@localhost/unused", echo_pool="debug")
    assert bounded_engine(source, capacity=1).pool.echo == "debug"
