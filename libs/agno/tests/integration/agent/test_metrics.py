import time

import pytest

from agno.agent import Agent, RunOutput  # noqa
from agno.culture.manager import CultureManager
from agno.db.base import SessionType
from agno.eval.accuracy import AccuracyEval
from agno.eval.agent_as_judge import AgentAsJudgeEval
from agno.memory.manager import MemoryManager
from agno.metrics import ModelMetrics, RunMetrics, SessionMetrics, ToolCallMetrics
from agno.models.openai import OpenAIChat
from agno.tools.websearch import WebSearchTools


def add(a: int, b: int) -> str:
    """Add two numbers."""
    return str(a + b)


def multiply(a: int, b: int) -> str:
    """Multiply two numbers."""
    return str(a * b)


def test_run_response_metrics():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        markdown=True,
    )

    response1 = agent.run("Hello my name is John")
    response2 = agent.run("I live in New York")

    assert response1.metrics.input_tokens >= 1
    assert response2.metrics.input_tokens >= 1

    assert response1.metrics.output_tokens >= 1
    assert response2.metrics.output_tokens >= 1

    assert response1.metrics.total_tokens >= 1
    assert response2.metrics.total_tokens >= 1


def test_session_metrics(shared_db):
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[WebSearchTools(cache_results=True)],
        db=shared_db,
        markdown=True,
        telemetry=False,
    )

    response = agent.run("Hi, my name is John")

    total_input_tokens = response.metrics.input_tokens
    total_output_tokens = response.metrics.output_tokens
    total_tokens = response.metrics.total_tokens

    assert response.metrics.input_tokens > 0
    assert response.metrics.output_tokens > 0
    assert response.metrics.total_tokens > 0
    assert response.metrics.total_tokens == response.metrics.input_tokens + response.metrics.output_tokens

    session_from_db = agent.db.get_session(session_id=agent.session_id, session_type=SessionType.AGENT)
    assert session_from_db.session_data["session_metrics"]["input_tokens"] == total_input_tokens
    assert session_from_db.session_data["session_metrics"]["output_tokens"] == total_output_tokens
    assert session_from_db.session_data["session_metrics"]["total_tokens"] == total_tokens

    response = agent.run("What is current news in France?")

    assert response.metrics.input_tokens > 0
    assert response.metrics.output_tokens > 0
    assert response.metrics.total_tokens > 0
    assert response.metrics.total_tokens == response.metrics.input_tokens + response.metrics.output_tokens

    total_input_tokens += response.metrics.input_tokens
    total_output_tokens += response.metrics.output_tokens
    total_tokens += response.metrics.total_tokens

    # Ensure the total session metrics are updated
    session_from_db = agent.db.get_session(session_id=agent.session_id, session_type=SessionType.AGENT)
    assert session_from_db.session_data["session_metrics"]["input_tokens"] == total_input_tokens
    assert session_from_db.session_data["session_metrics"]["output_tokens"] == total_output_tokens
    assert session_from_db.session_data["session_metrics"]["total_tokens"] == total_tokens


def test_session_metrics_with_add_history(shared_db):
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        add_history_to_context=True,
        num_history_runs=3,
        markdown=True,
        telemetry=False,
    )

    response = agent.run("Hi, my name is John")

    total_input_tokens = response.metrics.input_tokens
    total_output_tokens = response.metrics.output_tokens
    total_tokens = response.metrics.total_tokens

    assert response.metrics.input_tokens > 0
    assert response.metrics.output_tokens > 0
    assert response.metrics.total_tokens > 0
    assert response.metrics.total_tokens == response.metrics.input_tokens + response.metrics.output_tokens

    session_from_db = agent.db.get_session(session_id=agent.session_id, session_type=SessionType.AGENT)
    assert session_from_db.session_data["session_metrics"]["input_tokens"] == total_input_tokens
    assert session_from_db.session_data["session_metrics"]["output_tokens"] == total_output_tokens
    assert session_from_db.session_data["session_metrics"]["total_tokens"] == total_tokens

    response = agent.run("What did I just tell you?")

    assert response.metrics.input_tokens > 0
    assert response.metrics.output_tokens > 0
    assert response.metrics.total_tokens > 0
    assert response.metrics.total_tokens == response.metrics.input_tokens + response.metrics.output_tokens

    total_input_tokens += response.metrics.input_tokens
    total_output_tokens += response.metrics.output_tokens
    total_tokens += response.metrics.total_tokens

    # Ensure the total session metrics are updated
    session_from_db = agent.db.get_session(session_id=agent.session_id, session_type=SessionType.AGENT)
    assert session_from_db.session_data["session_metrics"]["input_tokens"] == total_input_tokens
    assert session_from_db.session_data["session_metrics"]["output_tokens"] == total_output_tokens
    assert session_from_db.session_data["session_metrics"]["total_tokens"] == total_tokens


def test_run_metrics_details_structure():
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))
    response = agent.run("Hello")

    assert response.metrics is not None
    assert isinstance(response.metrics, RunMetrics)
    assert response.metrics.total_tokens > 0
    assert response.metrics.details is not None
    assert "model" in response.metrics.details

    model_metrics = response.metrics.details["model"]
    assert len(model_metrics) >= 1
    assert isinstance(model_metrics[0], ModelMetrics)
    assert model_metrics[0].id == "gpt-4o-mini"
    assert model_metrics[0].provider == "OpenAI"
    assert model_metrics[0].input_tokens > 0
    assert model_metrics[0].total_tokens > 0


def test_run_metrics_details_sum_matches_total():
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))
    response = agent.run("What is 2+2?")

    detail_total = 0
    for entries in response.metrics.details.values():
        detail_total += sum(entry.total_tokens for entry in entries)

    assert detail_total == response.metrics.total_tokens


def test_eval_metrics_sync():
    eval_hook = AgentAsJudgeEval(
        name="Sync Eval",
        model=OpenAIChat(id="gpt-4o-mini"),
        criteria="Response should be factually correct",
        scoring_strategy="binary",
    )
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), post_hooks=[eval_hook])
    response = agent.run("What is the capital of Japan?")

    assert "model" in response.metrics.details
    assert "eval_model" in response.metrics.details

    agent_tokens = sum(metric.total_tokens for metric in response.metrics.details["model"])
    eval_tokens = sum(metric.total_tokens for metric in response.metrics.details["eval_model"])

    assert agent_tokens > 0
    assert eval_tokens > 0

    detail_total = sum(entry.total_tokens for entries in response.metrics.details.values() for entry in entries)
    assert detail_total == response.metrics.total_tokens


@pytest.mark.asyncio
async def test_eval_metrics_async():
    eval_hook = AgentAsJudgeEval(
        name="Async Eval",
        model=OpenAIChat(id="gpt-4o-mini"),
        criteria="Response should be helpful",
        scoring_strategy="binary",
    )
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), post_hooks=[eval_hook])
    response = await agent.arun("What is 5 + 3?")

    assert "model" in response.metrics.details
    assert "eval_model" in response.metrics.details
    assert sum(metric.total_tokens for metric in response.metrics.details["eval_model"]) > 0


def test_eval_metrics_streaming():
    eval_hook = AgentAsJudgeEval(
        name="Stream Eval",
        model=OpenAIChat(id="gpt-4o-mini"),
        criteria="Response should be concise",
        scoring_strategy="binary",
    )
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), post_hooks=[eval_hook])

    final = None
    for event in agent.run("Say hi.", stream=True, yield_run_output=True):
        if isinstance(event, RunOutput):
            final = event

    assert final is not None
    assert "model" in final.metrics.details
    assert "eval_model" in final.metrics.details


def test_eval_metrics_numeric_scoring():
    eval_hook = AgentAsJudgeEval(
        name="Numeric Eval",
        model=OpenAIChat(id="gpt-4o-mini"),
        criteria="Rate the quality of the response",
        scoring_strategy="numeric",
        threshold=5,
    )
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), post_hooks=[eval_hook])
    response = agent.run("Explain gravity in one sentence.")

    assert "eval_model" in response.metrics.details
    assert sum(metric.total_tokens for metric in response.metrics.details["eval_model"]) > 0


def test_accuracy_eval_metrics_sync():
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))
    evaluation = AccuracyEval(
        agent=agent,
        input="What is 2+2?",
        expected_output="4",
        num_iterations=1,
        model=OpenAIChat(id="gpt-4o-mini"),
    )
    result = evaluation.run(print_summary=False, print_results=False)

    assert result is not None
    assert result.avg_score is not None
    if result.results:
        assert result.results[0].score is not None


@pytest.mark.asyncio
async def test_accuracy_eval_metrics_async():
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))
    evaluation = AccuracyEval(
        agent=agent,
        input="What is 3+3?",
        expected_output="6",
        num_iterations=1,
        model=OpenAIChat(id="gpt-4o-mini"),
    )
    result = await evaluation.arun(print_summary=False, print_results=False)

    assert result is not None
    assert result.avg_score is not None


def test_memory_metrics_sync(shared_db):
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        memory_manager=MemoryManager(model=OpenAIChat(id="gpt-4o-mini"), db=shared_db),
        update_memory_on_run=True,
        db=shared_db,
    )
    response = agent.run("My name is Bob and I live in New York.")

    assert "model" in response.metrics.details
    assert "memory_model" in response.metrics.details
    assert sum(metric.total_tokens for metric in response.metrics.details["memory_model"]) > 0

    detail_total = sum(entry.total_tokens for entries in response.metrics.details.values() for entry in entries)
    assert detail_total == response.metrics.total_tokens


@pytest.mark.asyncio
async def test_memory_metrics_async(shared_db):
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        memory_manager=MemoryManager(model=OpenAIChat(id="gpt-4o-mini"), db=shared_db),
        update_memory_on_run=True,
        db=shared_db,
    )
    response = await agent.arun("My favorite color is blue.")

    assert "memory_model" in response.metrics.details
    assert sum(metric.total_tokens for metric in response.metrics.details["memory_model"]) > 0


def test_memory_metrics_streaming(shared_db):
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        memory_manager=MemoryManager(model=OpenAIChat(id="gpt-4o-mini"), db=shared_db),
        update_memory_on_run=True,
        db=shared_db,
    )

    final = None
    for event in agent.run("I work at Microsoft as a designer.", stream=True, yield_run_output=True):
        if isinstance(event, RunOutput):
            final = event

    assert final is not None
    assert "memory_model" in final.metrics.details


def test_memory_model_metrics_fields(shared_db):
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        memory_manager=MemoryManager(model=OpenAIChat(id="gpt-4o-mini"), db=shared_db),
        update_memory_on_run=True,
        db=shared_db,
    )
    response = agent.run("I have a dog named Max.")

    memory_entries = response.metrics.details.get("memory_model", [])
    assert len(memory_entries) >= 1

    for entry in memory_entries:
        assert isinstance(entry, ModelMetrics)
        assert entry.id is not None
        assert entry.provider is not None
        assert entry.input_tokens > 0


def test_culture_metrics_sync(shared_db):
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        culture_manager=CultureManager(model=OpenAIChat(id="gpt-4o-mini"), db=shared_db),
        update_cultural_knowledge=True,
        db=shared_db,
    )
    response = agent.run("Our team always does code reviews before merging PRs.")

    assert "culture_model" in response.metrics.details
    assert sum(metric.total_tokens for metric in response.metrics.details["culture_model"]) > 0


@pytest.mark.asyncio
async def test_culture_metrics_async(shared_db):
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        culture_manager=CultureManager(model=OpenAIChat(id="gpt-4o-mini"), db=shared_db),
        update_cultural_knowledge=True,
        db=shared_db,
    )
    response = await agent.arun("We use trunk-based development with feature flags.")

    assert "culture_model" in response.metrics.details
    assert sum(metric.total_tokens for metric in response.metrics.details["culture_model"]) > 0


def test_culture_model_metrics_fields(shared_db):
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        culture_manager=CultureManager(model=OpenAIChat(id="gpt-4o-mini"), db=shared_db),
        update_cultural_knowledge=True,
        db=shared_db,
    )
    response = agent.run("We deploy to production on Tuesdays.")

    culture_entries = response.metrics.details.get("culture_model", [])
    assert len(culture_entries) >= 1

    for entry in culture_entries:
        assert isinstance(entry, ModelMetrics)
        assert entry.id is not None
        assert entry.provider is not None


def test_tool_call_metrics_sync():
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), tools=[add])
    response = agent.run("Add 10 and 20.")

    assert response.tools is not None
    assert len(response.tools) > 0

    tool = response.tools[0]
    assert isinstance(tool.metrics, ToolCallMetrics)
    assert tool.metrics.duration > 0
    assert tool.metrics.start_time is not None
    assert tool.metrics.end_time is not None


@pytest.mark.asyncio
async def test_tool_call_metrics_async():
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), tools=[add])
    response = await agent.arun("Add 7 and 8.")

    assert response.tools is not None
    assert len(response.tools) > 0
    assert isinstance(response.tools[0].metrics, ToolCallMetrics)
    assert response.tools[0].metrics.duration > 0


def test_tool_call_metrics_streaming():
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), tools=[add])

    final = None
    for event in agent.run("Add 3 and 4.", stream=True, yield_run_output=True):
        if isinstance(event, RunOutput):
            final = event

    assert final is not None
    assert final.tools is not None
    assert isinstance(final.tools[0].metrics, ToolCallMetrics)
    assert final.tools[0].metrics.duration > 0


def test_tool_call_metrics_multiple_tools():
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), tools=[add, multiply])
    response = agent.run("Add 2 and 3, then multiply 4 and 5.")

    assert response.tools is not None
    assert len(response.tools) >= 2

    for tool in response.tools:
        assert isinstance(tool.metrics, ToolCallMetrics)
        assert tool.metrics.duration > 0

    # Same (provider, id) accumulates into a single ModelMetrics entry
    assert len(response.metrics.details["model"]) >= 1
    assert response.metrics.details["model"][0].total_tokens > 0


def test_tool_call_metrics_latency():
    def slow_lookup(query: str) -> str:
        """Look up information (slow)."""
        time.sleep(0.15)
        return f"Result for {query}"

    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), tools=[slow_lookup])
    response = agent.run("Look up information about Python.")

    assert response.tools is not None
    assert response.tools[0].metrics.duration >= 0.1


def test_provider_metrics_openai():
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))
    response = agent.run("Hello")

    model_metric = response.metrics.details["model"][0]
    assert model_metric.provider == "OpenAI"
    assert model_metric.id == "gpt-4o-mini"
    assert model_metric.input_tokens > 0
    assert model_metric.output_tokens > 0
    assert model_metric.total_tokens == model_metric.input_tokens + model_metric.output_tokens


def test_provider_metrics_openai_with_tools():
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), tools=[add])
    response = agent.run("Add 5 and 10.")

    model_entries = response.metrics.details["model"]
    # Same (provider, id) accumulates into a single entry
    assert len(model_entries) >= 1

    for entry in model_entries:
        assert entry.provider == "OpenAI"
        assert entry.id == "gpt-4o-mini"
        assert entry.total_tokens > 0


def test_provider_metrics_gemini():
    from agno.models.google import Gemini

    agent = Agent(model=Gemini(id="gemini-2.5-flash"))
    response = agent.run("Hello")

    model_metric = response.metrics.details["model"][0]
    assert model_metric.provider == "Google"
    assert model_metric.id == "gemini-2.5-flash"
    assert model_metric.input_tokens > 0
    assert model_metric.total_tokens > 0


def test_session_metrics_type(shared_db):
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), db=shared_db)
    agent.run("First run.")
    agent.run("Second run.")

    session_metrics = agent.get_session_metrics()
    assert isinstance(session_metrics, SessionMetrics)
    assert session_metrics.input_tokens > 0
    assert session_metrics.total_tokens > 0
    assert isinstance(session_metrics.details, dict)
    assert len(session_metrics.details) > 0
    for model_type, metrics_list in session_metrics.details.items():
        assert isinstance(metrics_list, list)
        for metric in metrics_list:
            assert isinstance(metric, ModelMetrics)


def test_session_metrics_with_memory(shared_db):
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        memory_manager=MemoryManager(model=OpenAIChat(id="gpt-4o-mini"), db=shared_db),
        update_memory_on_run=True,
        db=shared_db,
    )
    agent.run("My name is Charlie.")
    agent.run("I live in London.")

    session_metrics = agent.get_session_metrics()
    assert isinstance(session_metrics, SessionMetrics)
    assert session_metrics.total_tokens > 0

    for model_type, metrics_list in session_metrics.details.items():
        for detail in metrics_list:
            assert isinstance(detail, ModelMetrics)
            assert detail.id is not None


def test_session_metrics_with_eval(shared_db):
    eval_hook = AgentAsJudgeEval(
        name="Session Eval",
        model=OpenAIChat(id="gpt-4o-mini"),
        criteria="Response should be helpful",
        scoring_strategy="binary",
    )
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), post_hooks=[eval_hook], db=shared_db)
    response1 = agent.run("What is 2+2?")
    response2 = agent.run("What is 3+3?")

    assert "eval_model" in response1.metrics.details
    assert "eval_model" in response2.metrics.details

    session_metrics = agent.get_session_metrics()
    assert session_metrics.total_tokens > 0


@pytest.mark.asyncio
async def test_session_metrics_async(shared_db):
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), db=shared_db)
    await agent.arun("First async run.")
    await agent.arun("Second async run.")

    session_metrics = agent.get_session_metrics()
    assert session_metrics.total_tokens > 0


def test_session_metrics_run_independence(shared_db):
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), db=shared_db)
    response1 = agent.run("Say hello.")
    response2 = agent.run("Say goodbye.")

    assert response1.metrics.total_tokens > 0
    assert response2.metrics.total_tokens > 0

    session_metrics = agent.get_session_metrics()
    assert session_metrics.total_tokens >= response1.metrics.total_tokens + response2.metrics.total_tokens


def test_session_metrics_streaming(shared_db):
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), db=shared_db)

    for msg in ["Stream run 1.", "Stream run 2."]:
        for event in agent.run(msg, stream=True, yield_run_output=True):
            if isinstance(event, RunOutput):
                assert event.metrics.total_tokens > 0

    session_metrics = agent.get_session_metrics()
    assert session_metrics.total_tokens > 0


def test_eval_plus_memory_sync(shared_db):
    eval_hook = AgentAsJudgeEval(
        name="Combined Eval",
        model=OpenAIChat(id="gpt-4o-mini"),
        criteria="Response should be accurate",
        scoring_strategy="binary",
    )
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        memory_manager=MemoryManager(model=OpenAIChat(id="gpt-4o-mini"), db=shared_db),
        update_memory_on_run=True,
        post_hooks=[eval_hook],
        db=shared_db,
    )
    response = agent.run("My favorite food is pizza.")

    assert "model" in response.metrics.details
    assert "memory_model" in response.metrics.details
    assert "eval_model" in response.metrics.details

    for key in ["model", "memory_model", "eval_model"]:
        assert sum(metric.total_tokens for metric in response.metrics.details[key]) > 0

    detail_total = sum(entry.total_tokens for entries in response.metrics.details.values() for entry in entries)
    assert detail_total == response.metrics.total_tokens


@pytest.mark.asyncio
async def test_eval_plus_memory_async(shared_db):
    eval_hook = AgentAsJudgeEval(
        name="Async Combined",
        model=OpenAIChat(id="gpt-4o-mini"),
        criteria="Response should be relevant",
        scoring_strategy="binary",
    )
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        memory_manager=MemoryManager(model=OpenAIChat(id="gpt-4o-mini"), db=shared_db),
        update_memory_on_run=True,
        post_hooks=[eval_hook],
        db=shared_db,
    )
    response = await agent.arun("I speak French and English.")

    assert "model" in response.metrics.details
    assert "memory_model" in response.metrics.details
    assert "eval_model" in response.metrics.details


def test_tools_plus_eval_sync():
    eval_hook = AgentAsJudgeEval(
        name="Tool Eval",
        model=OpenAIChat(id="gpt-4o-mini"),
        criteria="Response should include the computed result",
        scoring_strategy="binary",
    )
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), tools=[add], post_hooks=[eval_hook])
    response = agent.run("What is 7 + 8?")

    assert "model" in response.metrics.details
    assert "eval_model" in response.metrics.details
    # Same (provider, id) accumulates into a single entry
    assert len(response.metrics.details["model"]) >= 1
    assert response.metrics.details["model"][0].total_tokens > 0


def test_all_three_combined(shared_db):
    eval_hook = AgentAsJudgeEval(
        name="Full Combo",
        model=OpenAIChat(id="gpt-4o-mini"),
        criteria="Response should be correct",
        scoring_strategy="binary",
    )
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        memory_manager=MemoryManager(model=OpenAIChat(id="gpt-4o-mini"), db=shared_db),
        update_memory_on_run=True,
        tools=[add],
        post_hooks=[eval_hook],
        db=shared_db,
    )
    response = agent.run("Add 100 and 200. Remember the answer for me.")

    for key in ["model", "memory_model", "eval_model"]:
        assert key in response.metrics.details
        assert sum(metric.total_tokens for metric in response.metrics.details[key]) > 0


def test_culture_plus_eval_sync(shared_db):
    eval_hook = AgentAsJudgeEval(
        name="Culture Eval",
        model=OpenAIChat(id="gpt-4o-mini"),
        criteria="Response should acknowledge the cultural practice",
        scoring_strategy="binary",
    )
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        culture_manager=CultureManager(model=OpenAIChat(id="gpt-4o-mini"), db=shared_db),
        update_cultural_knowledge=True,
        post_hooks=[eval_hook],
        db=shared_db,
    )
    response = agent.run("We always write unit tests before merging code.")

    assert "culture_model" in response.metrics.details
    assert "eval_model" in response.metrics.details


def test_culture_plus_memory_sync(shared_db):
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        culture_manager=CultureManager(model=OpenAIChat(id="gpt-4o-mini"), db=shared_db),
        update_cultural_knowledge=True,
        memory_manager=MemoryManager(model=OpenAIChat(id="gpt-4o-mini"), db=shared_db),
        update_memory_on_run=True,
        db=shared_db,
    )
    response = agent.run("My name is Eve. Our team uses pair programming.")

    assert "culture_model" in response.metrics.details
    assert "memory_model" in response.metrics.details


def test_multi_run_memory_session(shared_db):
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        memory_manager=MemoryManager(model=OpenAIChat(id="gpt-4o-mini"), db=shared_db),
        update_memory_on_run=True,
        db=shared_db,
    )

    runs_tokens = []
    for msg in ["I am Dave.", "I work at Apple.", "I like hiking."]:
        response = agent.run(msg)
        runs_tokens.append(response.metrics.total_tokens)
        assert "memory_model" in response.metrics.details

    session_metrics = agent.get_session_metrics()
    assert session_metrics.total_tokens >= sum(runs_tokens)


def test_multi_turn_metrics_independence():
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))

    tokens = []
    for i in range(3):
        response = agent.run(f"Say the number {i}.")
        tokens.append(response.metrics.total_tokens)
        if response.metrics.details and "model" in response.metrics.details:
            assert len(response.metrics.details["model"]) == 1

    assert max(tokens) < min(tokens) * 5


def test_streaming_metrics():
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))

    final = None
    for event in agent.run("Tell me a joke.", stream=True, yield_run_output=True):
        if isinstance(event, RunOutput):
            final = event

    assert final is not None
    assert final.metrics.total_tokens > 0
    assert "model" in final.metrics.details


def test_no_eval_key_without_eval():
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))
    response = agent.run("Hello")

    assert "model" in response.metrics.details
    assert "eval_model" not in response.metrics.details


def test_no_memory_key_without_memory():
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))
    response = agent.run("Hello")

    assert "memory_model" not in response.metrics.details


def test_no_culture_key_without_culture():
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))
    response = agent.run("Hello")

    assert "culture_model" not in response.metrics.details


def test_eval_duration_tracked():
    eval_hook = AgentAsJudgeEval(
        name="Duration Eval",
        model=OpenAIChat(id="gpt-4o-mini"),
        criteria="Response should be factually correct",
        scoring_strategy="binary",
    )
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), post_hooks=[eval_hook])
    response = agent.run("What is the capital of France?")

    assert response.metrics.additional_metrics is not None
    assert "eval_duration" in response.metrics.additional_metrics
    assert response.metrics.additional_metrics["eval_duration"] > 0


def test_detail_keys_reset_between_runs():
    eval_hook = AgentAsJudgeEval(
        name="Reset Test",
        model=OpenAIChat(id="gpt-4o-mini"),
        criteria="Response should be correct",
        scoring_strategy="binary",
    )
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), post_hooks=[eval_hook])

    agent.run("What is 1+1?")

    response2 = agent.run("What is 2+2?")

    assert sum(metric.total_tokens for metric in response2.metrics.details["eval_model"]) > 0
    assert len(response2.metrics.details["eval_model"]) == 1
