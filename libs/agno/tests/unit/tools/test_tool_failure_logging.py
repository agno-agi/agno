import logging
from typing import List

import pytest
from pydantic import BaseModel

from agno.exceptions import RetryAgentRun, StopAgentRun
from agno.tools import tool
from agno.tools.function import Function, FunctionCall
from agno.utils.functions import get_function_call


class _Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: List[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def logged():
    """Agno's logger sets propagate=False, so caplog never sees these; attach a handler directly."""
    logger = logging.getLogger("agno")
    handler = _Collect()
    old_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    yield handler.records
    logger.removeHandler(handler)
    logger.setLevel(old_level)


def _warnings_and_up(records: List[logging.LogRecord]) -> List[logging.LogRecord]:
    return [r for r in records if r.levelno >= logging.WARNING]


def _processed(function: Function) -> Function:
    function.process_entrypoint()
    return function


class Order(BaseModel):
    quantity: int


def _refuse(order_id: str) -> str:
    """Refuse the order."""
    raise RetryAgentRun("Refused. Fix the order and call again.")


async def _refuse_async(order_id: str) -> str:
    """Refuse the order."""
    raise RetryAgentRun("Refused. Fix the order and call again.")


async def _stop_async(order_id: str) -> str:
    """Stop the run."""
    raise StopAgentRun("Stop here.")


async def _broken_lookup(order_id: str) -> str:
    """Look an order up."""
    raise ValueError("order has no number")


def _send_reply(reply_text: str) -> str:
    """Send a reply."""
    return "sent"


def _build_order(quantity: str) -> str:
    """Build an order."""
    Order(quantity=quantity)
    return "built"


def test_retry_agent_run_from_a_sync_tool_is_not_logged_as_a_problem(logged):
    call = FunctionCall(function=_processed(tool(_refuse)), arguments={"order_id": "A-1"})

    with pytest.raises(RetryAgentRun):
        call.execute()

    assert _warnings_and_up(logged) == []


@pytest.mark.parametrize(
    "func, exc",
    [(_refuse_async, RetryAgentRun), (_stop_async, StopAgentRun)],
    ids=["retry", "stop"],
)
async def test_control_flow_from_an_async_tool_is_not_logged_as_a_problem(logged, func, exc):
    call = FunctionCall(function=_processed(tool(func)), arguments={"order_id": "A-1"})

    with pytest.raises(exc):
        await call.aexecute()

    assert _warnings_and_up(logged) == []


async def test_a_failing_tool_is_logged_once_with_its_traceback(logged):
    call = FunctionCall(function=_processed(tool(_broken_lookup)), arguments={"order_id": "A-1"})

    result = await call.aexecute()

    assert result.status == "failure"
    problems = _warnings_and_up(logged)
    assert [r.levelno for r in problems] == [logging.ERROR]
    assert problems[0].exc_info is not None
    assert "order has no number" in problems[0].getMessage()


def test_arguments_that_do_not_fit_the_signature_are_one_warning(logged):
    call = FunctionCall(function=_processed(tool(_send_reply)), arguments={"message": "hello"})

    result = call.execute()

    assert result.status == "failure"
    assert "reply_text" in (result.error or "")
    problems = _warnings_and_up(logged)
    assert [r.levelno for r in problems] == [logging.WARNING]
    assert problems[0].exc_info is None


def test_a_validation_error_raised_inside_the_tool_stays_an_error(logged):
    call = FunctionCall(function=_processed(tool(_build_order)), arguments={"quantity": "many"})

    result = call.execute()

    assert result.status == "failure"
    problems = _warnings_and_up(logged)
    assert [r.levelno for r in problems] == [logging.ERROR]
    assert problems[0].exc_info is not None


def test_an_unknown_tool_is_a_warning(logged):
    function_call = get_function_call(name="missing_tool", arguments="{}", functions={"send_reply": tool(_send_reply)})

    assert function_call is None
    assert [r.levelno for r in _warnings_and_up(logged)] == [logging.WARNING]


def test_undecodable_arguments_are_a_warning(logged):
    function_call = get_function_call(
        name="send_reply", arguments="{not json", functions={"send_reply": tool(_send_reply)}
    )

    assert function_call is not None
    assert function_call.error is not None
    assert [r.levelno for r in _warnings_and_up(logged)] == [logging.WARNING]
