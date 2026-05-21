"""Integration tests for Agent reasoning with all supported reasoning model providers.

This test verifies that Agent reasoning works with:
- Anthropic Claude models with extended thinking
- Gemini 2.5+ models with thinking support
- VertexAI Claude models with extended thinking
- OpenAI reasoning models (o1, o3, o4, 4.1, 4.5)
- DeepSeek reasoning model (deepseek-reasoner)
- Groq reasoning models (deepseek variants)
- Ollama reasoning models (qwq, deepseek-r1, etc.)
- Azure AI Foundry reasoning models
"""

from textwrap import dedent

import pytest

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.azure import AzureAIFoundry
from agno.models.deepseek import DeepSeek
from agno.models.google import Gemini
from agno.models.groq import Groq
from agno.models.ollama import Ollama
from agno.models.openai import OpenAIChat


@pytest.fixture(autouse=True)
def _show_output(capfd):
    """Force pytest to show print output for all tests in this module."""
    yield
    # Print captured output after test completes
    captured = capfd.readouterr()
    if captured.out:
        print(captured.out)
    if captured.err:
        print(captured.err)


# ============================================================================
# Anthropic Claude Reasoning Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.skip(reason="Requires Anthropic API key and actual API call")
def test_agent_anthropic_claude_reasoning_non_streaming():
    """Test that Agent reasoning works with Anthropic Claude (extended thinking) in non-streaming mode."""
    # Create an Agent with Anthropic Claude reasoning model
    agent = Agent(
        model=Claude(id="claude-sonnet-4-5-20250929"),
        reasoning_model=Claude(
            id="claude-sonnet-4-5-20250929",
            thinking={"type": "enabled", "budget_tokens": 512},
        ),
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Run the agent in non-streaming mode
    response = agent.run("What is the sum of the first 10 natural numbers?", stream=False)

    # Print the reasoning_content when received
    if hasattr(response, "reasoning_content") and response.reasoning_content:
        print("\n=== Anthropic Claude reasoning (non-streaming) reasoning_content ===")
        print(response.reasoning_content)
        print("====================================================================\n")

    # Assert that reasoning_content exists and is populated
    assert hasattr(response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(response.reasoning_content) > 0, "reasoning_content should not be empty"


@pytest.mark.integration
@pytest.mark.skip(reason="Requires Anthropic API key and actual API call")
def test_agent_anthropic_claude_reasoning_streaming(shared_db):
    """Test that Agent reasoning works with Anthropic Claude (extended thinking) in streaming mode."""
    # Create an Agent with Anthropic Claude reasoning model
    agent = Agent(
        model=Claude(id="claude-sonnet-4-5-20250929"),
        reasoning_model=Claude(
            id="claude-sonnet-4-5-20250929",
            thinking={"type": "enabled", "budget_tokens": 512},
        ),
        db=shared_db,
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Consume all streaming responses
    _ = list(agent.run("What is the value of 5! (factorial)?", stream=True, stream_events=True))

    run_response = agent.get_last_run_output()
    # Print the reasoning_content when received
    if run_response and hasattr(run_response, "reasoning_content") and run_response.reasoning_content:
        print("\n=== Anthropic Claude reasoning (streaming) reasoning_content ===")
        print(run_response.reasoning_content)
        print("================================================================\n")

    # Check the agent's run_response directly after streaming is complete
    assert run_response is not None, "run_response should not be None"
    assert hasattr(run_response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert run_response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(run_response.reasoning_content) > 0, "reasoning_content should not be empty"


# ============================================================================
# Gemini 2.5+ Reasoning Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.skip(reason="Requires Google API key and actual API call")
def test_agent_gemini_reasoning_non_streaming():
    """Test that Agent reasoning works with Gemini 2.5+ (thinking support) in non-streaming mode."""
    # Create an Agent with Gemini 2.5+ reasoning model
    agent = Agent(
        model=Gemini(id="gemini-2.5-flash"),
        reasoning_model=Gemini(id="gemini-2.5-flash", thinking_budget=1024),
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Run the agent in non-streaming mode
    response = agent.run("What is the sum of the first 10 natural numbers?", stream=False)

    # Print the reasoning_content when received
    if hasattr(response, "reasoning_content") and response.reasoning_content:
        print("\n=== Gemini 2.5 reasoning (non-streaming) reasoning_content ===")
        print(response.reasoning_content)
        print("==============================================================\n")

    # Assert that reasoning_content exists and is populated
    assert hasattr(response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(response.reasoning_content) > 0, "reasoning_content should not be empty"


@pytest.mark.integration
@pytest.mark.skip(reason="Requires Google API key and actual API call")
def test_agent_gemini_reasoning_streaming(shared_db):
    """Test that Agent reasoning works with Gemini 2.5+ (thinking support) in streaming mode."""
    # Create an Agent with Gemini 2.5+ reasoning model
    agent = Agent(
        model=Gemini(id="gemini-2.5-flash"),
        reasoning_model=Gemini(id="gemini-2.5-flash", thinking_budget=1024),
        db=shared_db,
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Consume all streaming responses
    _ = list(agent.run("What is the value of 5! (factorial)?", stream=True, stream_events=True))

    run_response = agent.get_last_run_output()
    # Print the reasoning_content when received
    if run_response and hasattr(run_response, "reasoning_content") and run_response.reasoning_content:
        print("\n=== Gemini 2.5 reasoning (streaming) reasoning_content ===")
        print(run_response.reasoning_content)
        print("=========================================================\n")

    # Check the agent's run_response directly after streaming is complete
    assert run_response is not None, "run_response should not be None"
    assert hasattr(run_response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert run_response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(run_response.reasoning_content) > 0, "reasoning_content should not be empty"


# ============================================================================
# VertexAI Claude Reasoning Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.skip(reason="Requires VertexAI credentials and actual API call")
def test_agent_vertexai_claude_reasoning_non_streaming():
    """Test that Agent reasoning works with VertexAI Claude (extended thinking) in non-streaming mode."""
    # Create an Agent with VertexAI Claude reasoning model
    # Note: VertexAI Claude uses the same Claude class but with VertexAI provider
    agent = Agent(
        model=Claude(id="claude-sonnet-4-5-20250929", provider="VertexAI"),
        reasoning_model=Claude(
            id="claude-sonnet-4-5-20250929",
            provider="VertexAI",
            thinking={"type": "enabled", "budget_tokens": 512},
        ),
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Run the agent in non-streaming mode
    response = agent.run("What is the sum of the first 10 natural numbers?", stream=False)

    # Print the reasoning_content when received
    if hasattr(response, "reasoning_content") and response.reasoning_content:
        print("\n=== VertexAI Claude reasoning (non-streaming) reasoning_content ===")
        print(response.reasoning_content)
        print("===================================================================\n")

    # Assert that reasoning_content exists and is populated
    assert hasattr(response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(response.reasoning_content) > 0, "reasoning_content should not be empty"


@pytest.mark.integration
@pytest.mark.skip(reason="Requires VertexAI credentials and actual API call")
def test_agent_vertexai_claude_reasoning_streaming(shared_db):
    """Test that Agent reasoning works with VertexAI Claude (extended thinking) in streaming mode."""
    # Create an Agent with VertexAI Claude reasoning model
    agent = Agent(
        model=Claude(id="claude-sonnet-4-5-20250929", provider="VertexAI"),
        reasoning_model=Claude(
            id="claude-sonnet-4-5-20250929",
            provider="VertexAI",
            thinking={"type": "enabled", "budget_tokens": 512},
        ),
        db=shared_db,
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Consume all streaming responses
    _ = list(agent.run("What is the value of 5! (factorial)?", stream=True, stream_events=True))

    run_response = agent.get_last_run_output()
    # Print the reasoning_content when received
    if run_response and hasattr(run_response, "reasoning_content") and run_response.reasoning_content:
        print("\n=== VertexAI Claude reasoning (streaming) reasoning_content ===")
        print(run_response.reasoning_content)
        print("===============================================================\n")

    # Check the agent's run_response directly after streaming is complete
    assert run_response is not None, "run_response should not be None"
    assert hasattr(run_response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert run_response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(run_response.reasoning_content) > 0, "reasoning_content should not be empty"


# ============================================================================
# OpenAI Reasoning Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.skip(reason="Requires OpenAI API key and actual API call")
def test_agent_openai_reasoning_non_streaming():
    """Test that Agent reasoning works with OpenAI reasoning models (o1/o3/o4) in non-streaming mode."""
    # Create an Agent with OpenAI reasoning model
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        reasoning_model=OpenAIChat(id="o1-mini"),
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Run the agent in non-streaming mode
    response = agent.run("What is the sum of the first 10 natural numbers?", stream=False)

    # Print the reasoning_content when received
    if hasattr(response, "reasoning_content") and response.reasoning_content:
        print("\n=== OpenAI reasoning (non-streaming) reasoning_content ===")
        print(response.reasoning_content)
        print("==========================================================\n")

    # Assert that reasoning_content exists and is populated
    assert hasattr(response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(response.reasoning_content) > 0, "reasoning_content should not be empty"


@pytest.mark.integration
@pytest.mark.skip(reason="Requires OpenAI API key and actual API call")
def test_agent_openai_reasoning_streaming(shared_db):
    """Test that Agent reasoning works with OpenAI reasoning models (o1/o3/o4) in streaming mode."""
    # Create an Agent with OpenAI reasoning model
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        reasoning_model=OpenAIChat(id="o1-mini"),
        db=shared_db,
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Consume all streaming responses
    _ = list(agent.run("What is the value of 5! (factorial)?", stream=True, stream_events=True))

    run_response = agent.get_last_run_output()
    # Print the reasoning_content when received
    if run_response and hasattr(run_response, "reasoning_content") and run_response.reasoning_content:
        print("\n=== OpenAI reasoning (streaming) reasoning_content ===")
        print(run_response.reasoning_content)
        print("======================================================\n")

    # Check the agent's run_response directly after streaming is complete
    assert run_response is not None, "run_response should not be None"
    assert hasattr(run_response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert run_response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(run_response.reasoning_content) > 0, "reasoning_content should not be empty"


# ============================================================================
# DeepSeek Reasoning Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.skip(reason="Requires DeepSeek API key and actual API call")
def test_agent_deepseek_reasoning_non_streaming():
    """Test that Agent reasoning works with DeepSeek reasoning model in non-streaming mode."""
    # Create an Agent with DeepSeek reasoning model
    agent = Agent(
        model=DeepSeek(id="deepseek-chat"),
        reasoning_model=DeepSeek(id="deepseek-reasoner"),
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Run the agent in non-streaming mode
    response = agent.run("What is the sum of the first 10 natural numbers?", stream=False)

    # Print the reasoning_content when received
    if hasattr(response, "reasoning_content") and response.reasoning_content:
        print("\n=== DeepSeek reasoning (non-streaming) reasoning_content ===")
        print(response.reasoning_content)
        print("============================================================\n")

    # Assert that reasoning_content exists and is populated
    assert hasattr(response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(response.reasoning_content) > 0, "reasoning_content should not be empty"


@pytest.mark.integration
@pytest.mark.skip(reason="Requires DeepSeek API key and actual API call")
def test_agent_deepseek_reasoning_streaming(shared_db):
    """Test that Agent reasoning works with DeepSeek reasoning model in streaming mode."""
    # Create an Agent with DeepSeek reasoning model
    agent = Agent(
        model=DeepSeek(id="deepseek-chat"),
        reasoning_model=DeepSeek(id="deepseek-reasoner"),
        db=shared_db,
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Consume all streaming responses
    _ = list(agent.run("What is the value of 5! (factorial)?", stream=True, stream_events=True))

    run_response = agent.get_last_run_output()
    # Print the reasoning_content when received
    if run_response and hasattr(run_response, "reasoning_content") and run_response.reasoning_content:
        print("\n=== DeepSeek reasoning (streaming) reasoning_content ===")
        print(run_response.reasoning_content)
        print("========================================================\n")

    # Check the agent's run_response directly after streaming is complete
    assert run_response is not None, "run_response should not be None"
    assert hasattr(run_response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert run_response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(run_response.reasoning_content) > 0, "reasoning_content should not be empty"


# ============================================================================
# Groq Reasoning Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.skip(reason="Requires Groq API key and actual API call")
def test_agent_groq_reasoning_non_streaming():
    """Test that Agent reasoning works with Groq reasoning models (deepseek variants) in non-streaming mode."""
    # Create an Agent with Groq reasoning model
    agent = Agent(
        model=Groq(id="llama-3.3-70b-versatile"),
        reasoning_model=Groq(id="deepseek-r1-distill-llama-70b"),
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Run the agent in non-streaming mode
    response = agent.run("What is the sum of the first 10 natural numbers?", stream=False)

    # Print the reasoning_content when received
    if hasattr(response, "reasoning_content") and response.reasoning_content:
        print("\n=== Groq reasoning (non-streaming) reasoning_content ===")
        print(response.reasoning_content)
        print("========================================================\n")

    # Assert that reasoning_content exists and is populated
    assert hasattr(response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(response.reasoning_content) > 0, "reasoning_content should not be empty"


@pytest.mark.integration
@pytest.mark.skip(reason="Requires Groq API key and actual API call")
def test_agent_groq_reasoning_streaming(shared_db):
    """Test that Agent reasoning works with Groq reasoning models (deepseek variants) in streaming mode."""
    # Create an Agent with Groq reasoning model
    agent = Agent(
        model=Groq(id="llama-3.3-70b-versatile"),
        reasoning_model=Groq(id="deepseek-r1-distill-llama-70b"),
        db=shared_db,
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Consume all streaming responses
    _ = list(agent.run("What is the value of 5! (factorial)?", stream=True, stream_events=True))

    run_response = agent.get_last_run_output()
    # Print the reasoning_content when received
    if run_response and hasattr(run_response, "reasoning_content") and run_response.reasoning_content:
        print("\n=== Groq reasoning (streaming) reasoning_content ===")
        print(run_response.reasoning_content)
        print("====================================================\n")

    # Check the agent's run_response directly after streaming is complete
    assert run_response is not None, "run_response should not be None"
    assert hasattr(run_response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert run_response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(run_response.reasoning_content) > 0, "reasoning_content should not be empty"


# ============================================================================
# Ollama Reasoning Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.skip(reason="Requires Ollama running locally and actual API call")
def test_agent_ollama_reasoning_non_streaming():
    """Test that Agent reasoning works with Ollama reasoning models (qwq, deepseek-r1, etc.) in non-streaming mode."""
    # Create an Agent with Ollama reasoning model
    agent = Agent(
        model=Ollama(id="llama3.2"),
        reasoning_model=Ollama(id="qwq"),
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Run the agent in non-streaming mode
    response = agent.run("What is the sum of the first 10 natural numbers?", stream=False)

    # Print the reasoning_content when received
    if hasattr(response, "reasoning_content") and response.reasoning_content:
        print("\n=== Ollama reasoning (non-streaming) reasoning_content ===")
        print(response.reasoning_content)
        print("==========================================================\n")

    # Assert that reasoning_content exists and is populated
    assert hasattr(response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(response.reasoning_content) > 0, "reasoning_content should not be empty"


@pytest.mark.integration
@pytest.mark.skip(reason="Requires Ollama running locally and actual API call")
def test_agent_ollama_reasoning_streaming(shared_db):
    """Test that Agent reasoning works with Ollama reasoning models (qwq, deepseek-r1, etc.) in streaming mode."""
    # Create an Agent with Ollama reasoning model
    agent = Agent(
        model=Ollama(id="llama3.2"),
        reasoning_model=Ollama(id="qwq"),
        db=shared_db,
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Consume all streaming responses
    _ = list(agent.run("What is the value of 5! (factorial)?", stream=True, stream_events=True))

    run_response = agent.get_last_run_output()
    # Print the reasoning_content when received
    if run_response and hasattr(run_response, "reasoning_content") and run_response.reasoning_content:
        print("\n=== Ollama reasoning (streaming) reasoning_content ===")
        print(run_response.reasoning_content)
        print("======================================================\n")

    # Check the agent's run_response directly after streaming is complete
    assert run_response is not None, "run_response should not be None"
    assert hasattr(run_response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert run_response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(run_response.reasoning_content) > 0, "reasoning_content should not be empty"


# ============================================================================
# Azure AI Foundry Reasoning Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.skip(reason="Requires Azure AI Foundry credentials and actual API call")
def test_agent_azure_ai_foundry_reasoning_non_streaming():
    """Test that Agent reasoning works with Azure AI Foundry reasoning models in non-streaming mode."""
    # Create an Agent with Azure AI Foundry reasoning model
    agent = Agent(
        model=AzureAIFoundry(id="gpt-4o"),
        reasoning_model=AzureAIFoundry(id="o1-mini"),
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Run the agent in non-streaming mode
    response = agent.run("What is the sum of the first 10 natural numbers?", stream=False)

    # Print the reasoning_content when received
    if hasattr(response, "reasoning_content") and response.reasoning_content:
        print("\n=== Azure AI Foundry reasoning (non-streaming) reasoning_content ===")
        print(response.reasoning_content)
        print("===================================================================\n")

    # Assert that reasoning_content exists and is populated
    assert hasattr(response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(response.reasoning_content) > 0, "reasoning_content should not be empty"


@pytest.mark.integration
@pytest.mark.skip(reason="Requires Azure AI Foundry credentials and actual API call")
def test_agent_azure_ai_foundry_reasoning_streaming(shared_db):
    """Test that Agent reasoning works with Azure AI Foundry reasoning models in streaming mode."""
    # Create an Agent with Azure AI Foundry reasoning model
    agent = Agent(
        model=AzureAIFoundry(id="gpt-4o"),
        reasoning_model=AzureAIFoundry(id="o1-mini"),
        db=shared_db,
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Consume all streaming responses
    _ = list(agent.run("What is the value of 5! (factorial)?", stream=True, stream_events=True))

    run_response = agent.get_last_run_output()
    # Print the reasoning_content when received
    if run_response and hasattr(run_response, "reasoning_content") and run_response.reasoning_content:
        print("\n=== Azure AI Foundry reasoning (streaming) reasoning_content ===")
        print(run_response.reasoning_content)
        print("===============================================================\n")

    # Check the agent's run_response directly after streaming is complete
    assert run_response is not None, "run_response should not be None"
    assert hasattr(run_response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert run_response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(run_response.reasoning_content) > 0, "reasoning_content should not be empty"


# ============================================================================
# Model Detection Tests (Unit-like tests without API calls)
# ============================================================================


def test_agent_accepts_anthropic_claude_reasoning_model():
    """Test that Agent can be instantiated with Anthropic Claude reasoning model."""
    try:
        agent = Agent(
            model=Claude(id="claude-sonnet-4-5-20250929"),
            reasoning_model=Claude(
                id="claude-sonnet-4-5-20250929",
                thinking={"type": "enabled", "budget_tokens": 512},
            ),
        )
        assert agent.reasoning_model is not None
        assert agent.reasoning_model.id == "claude-sonnet-4-5-20250929"
    except Exception as e:
        pytest.fail(f"Failed to create Agent with Anthropic Claude reasoning model: {e}")


def test_agent_accepts_gemini_reasoning_model():
    """Test that Agent can be instantiated with Gemini 2.5+ reasoning model."""
    try:
        agent = Agent(
            model=Gemini(id="gemini-2.5-flash"),
            reasoning_model=Gemini(id="gemini-2.5-flash", thinking_budget=1024),
        )
        assert agent.reasoning_model is not None
        assert agent.reasoning_model.id == "gemini-2.5-flash"
    except Exception as e:
        pytest.fail(f"Failed to create Agent with Gemini reasoning model: {e}")


def test_agent_accepts_vertexai_claude_reasoning_model():
    """Test that Agent can be instantiated with VertexAI Claude reasoning model."""
    try:
        agent = Agent(
            model=Claude(id="claude-sonnet-4-5-20250929", provider="VertexAI"),
            reasoning_model=Claude(
                id="claude-sonnet-4-5-20250929",
                provider="VertexAI",
                thinking={"type": "enabled", "budget_tokens": 512},
            ),
        )
        assert agent.reasoning_model is not None
        assert agent.reasoning_model.id == "claude-sonnet-4-5-20250929"
    except Exception as e:
        pytest.fail(f"Failed to create Agent with VertexAI Claude reasoning model: {e}")


def test_agent_accepts_openai_reasoning_model():
    """Test that Agent can be instantiated with OpenAI reasoning model."""
    try:
        agent = Agent(
            model=OpenAIChat(id="gpt-4o"),
            reasoning_model=OpenAIChat(id="o1-mini"),
        )
        assert agent.reasoning_model is not None
        assert agent.reasoning_model.id == "o1-mini"
    except Exception as e:
        pytest.fail(f"Failed to create Agent with OpenAI reasoning model: {e}")


def test_agent_accepts_deepseek_reasoning_model():
    """Test that Agent can be instantiated with DeepSeek reasoning model."""
    try:
        agent = Agent(
            model=DeepSeek(id="deepseek-chat"),
            reasoning_model=DeepSeek(id="deepseek-reasoner"),
        )
        assert agent.reasoning_model is not None
        assert agent.reasoning_model.id == "deepseek-reasoner"
    except Exception as e:
        pytest.fail(f"Failed to create Agent with DeepSeek reasoning model: {e}")


def test_agent_accepts_groq_reasoning_model():
    """Test that Agent can be instantiated with Groq reasoning model."""
    try:
        agent = Agent(
            model=Groq(id="llama-3.3-70b-versatile"),
            reasoning_model=Groq(id="deepseek-r1-distill-llama-70b"),
        )
        assert agent.reasoning_model is not None
        assert agent.reasoning_model.id == "deepseek-r1-distill-llama-70b"
    except Exception as e:
        pytest.fail(f"Failed to create Agent with Groq reasoning model: {e}")


def test_agent_accepts_ollama_reasoning_model():
    """Test that Agent can be instantiated with Ollama reasoning model."""
    try:
        agent = Agent(
            model=Ollama(id="llama3.2"),
            reasoning_model=Ollama(id="qwq"),
        )
        assert agent.reasoning_model is not None
        assert agent.reasoning_model.id == "qwq"
    except Exception as e:
        pytest.fail(f"Failed to create Agent with Ollama reasoning model: {e}")


def test_agent_accepts_azure_ai_foundry_reasoning_model():
    """Test that Agent can be instantiated with Azure AI Foundry reasoning model."""
    try:
        agent = Agent(
            model=AzureAIFoundry(id="gpt-4o"),
            reasoning_model=AzureAIFoundry(id="o1-mini"),
        )
        assert agent.reasoning_model is not None
        assert agent.reasoning_model.id == "o1-mini"
    except Exception as e:
        pytest.fail(f"Failed to create Agent with Azure AI Foundry reasoning model: {e}")
