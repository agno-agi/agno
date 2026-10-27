"""Tests for preserving paused runs during async task teardown."""

import asyncio

import pytest

from agno.run.base import RunStatus
from agno.run.cancel import reraise_if_paused_on_disconnect


@pytest.mark.parametrize("error", [asyncio.CancelledError(), GeneratorExit()])
def test_paused_disconnect_is_reraised(error: BaseException):
    with pytest.raises(type(error)) as exc_info:
        reraise_if_paused_on_disconnect(RunStatus.paused, error)

    assert exc_info.value is error


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (RunStatus.running, asyncio.CancelledError()),
        (RunStatus.cancelled, GeneratorExit()),
        (RunStatus.paused, KeyboardInterrupt()),
    ],
)
def test_non_paused_or_explicit_cancellation_is_not_reraised(status: RunStatus, error: BaseException):
    reraise_if_paused_on_disconnect(status, error)
