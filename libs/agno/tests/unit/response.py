import json

from agno.models.message import Message, MessageMetrics
from agno.run.response import RunResponse


def test_timer_serialization():
    message_1 = Message(role="user", content="Hello, world!")
    message_2 = Message(role="assistant", metrics=MessageMetrics())

    message_2.metrics.start_timer()
    message_2.metrics.stop_timer()

    run_response = RunResponse(messages=[message_1, message_2])

    assert json.dumps(run_response.to_dict()) is not None
