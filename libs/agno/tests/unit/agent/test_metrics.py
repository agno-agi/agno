from agno.agent.agent import Agent
from agno.models.message import Message
from agno.models.metrics import Metrics
from agno.utils.timer import Timer


def test_calculate_run_metrics_does_not_double_count():
    agent = Agent()

    assistant_message = Message(role="assistant", content="hello")
    assistant_message.metrics = Metrics(input_tokens=100, output_tokens=25, total_tokens=125)

    initial_metrics = agent._calculate_run_metrics([assistant_message])
    initial_metrics.provider_metrics = {"service_tier": "default"}
    initial_metrics.additional_metrics = {"custom": "value"}
    initial_metrics.timer = Timer()
    initial_metrics.duration = 0.5
    initial_metrics.time_to_first_token = 0.1

    recomputed_metrics = agent._calculate_run_metrics(
        [assistant_message], current_run_metrics=initial_metrics
    )

    assert recomputed_metrics.input_tokens == 100
    assert recomputed_metrics.output_tokens == 25
    assert recomputed_metrics.total_tokens == 125
    assert recomputed_metrics.provider_metrics == {"service_tier": "default"}
    assert recomputed_metrics.additional_metrics == {"custom": "value"}
    assert recomputed_metrics.timer is initial_metrics.timer
    assert recomputed_metrics.duration == 0.5
    assert recomputed_metrics.time_to_first_token == 0.1
