"""Integration tests for Team reasoning with all supported reasoning model providers.

This test verifies that Team reasoning works with:
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

from agno.models.anthropic import Claude
from agno.models.azure import AzureAIFoundry
from agno.models.deepseek import DeepSeek
from agno.models.google import Gemini
from agno.models.groq import Groq
from agno.models.ollama import Ollama
from agno.models.openai import OpenAIChat
from agno.team.team import Team


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
def test_team_anthropic_claude_reasoning_non_streaming():
    """Test that Team reasoning works with Anthropic Claude (extended thinking) in non-streaming mode."""
    # Create a Team with Anthropic Claude reasoning model
    team = Team(
        model=Claude(id="claude-sonnet-4-5-20250929"),
        reasoning_model=Claude(
            id="claude-sonnet-4-5-20250929",
            thinking={"type": "enabled", "budget_tokens": 512},
        ),
        members=[],
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Run the team in non-streaming mode
    response = team.run("What is the sum of the first 10 natural numbers?", stream=False)

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
def test_team_anthropic_claude_reasoning_streaming(shared_db):
    """Test that Team reasoning works with Anthropic Claude (extended thinking) in streaming mode."""
    # Create a Team with Anthropic Claude reasoning model
    team = Team(
        model=Claude(id="claude-sonnet-4-5-20250929"),
        reasoning_model=Claude(
            id="claude-sonnet-4-5-20250929",
            thinking={"type": "enabled", "budget_tokens": 512},
        ),
        db=shared_db,
        members=[],
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Consume all streaming responses
    reasoning_content_found = False
    for event in team.run("What is the value of 5! (factorial)?", stream=True, stream_events=True):
        if hasattr(event, "reasoning_content"):
            reasoning_content_found = True

    assert reasoning_content_found, "reasoning_content should be found in the streaming responses"

    run_response = team.get_last_run_output()
    # Print the reasoning_content when received
    if run_response and hasattr(run_response, "reasoning_content") and run_response.reasoning_content:
        print("\n=== Anthropic Claude reasoning (streaming) reasoning_content ===")
        print(run_response.reasoning_content)
        print("================================================================\n")

    # Check the team's run_response directly after streaming is complete
    assert run_response is not None, "run_response should not be None"
    assert hasattr(run_response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert run_response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(run_response.reasoning_content) > 0, "reasoning_content should not be empty"


# ============================================================================
# Gemini 2.5+ Reasoning Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.skip(reason="Requires Google API key and actual API call")
def test_team_gemini_reasoning_non_streaming():
    """Test that Team reasoning works with Gemini 2.5+ (thinking support) in non-streaming mode."""
    # Create a Team with Gemini 2.5+ reasoning model
    team = Team(
        model=Gemini(id="gemini-2.5-flash"),
        reasoning_model=Gemini(id="gemini-2.5-flash", thinking_budget=1024),
        members=[],
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Run the team in non-streaming mode
    response = team.run("What is the sum of the first 10 natural numbers?", stream=False)

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
def test_team_gemini_reasoning_streaming(shared_db):
    """Test that Team reasoning works with Gemini 2.5+ (thinking support) in streaming mode."""
    # Create a Team with Gemini 2.5+ reasoning model
    team = Team(
        model=Gemini(id="gemini-2.5-flash"),
        reasoning_model=Gemini(id="gemini-2.5-flash", thinking_budget=1024),
        db=shared_db,
        members=[],
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Consume all streaming responses
    reasoning_content_found = False
    for event in team.run("What is the value of 5! (factorial)?", stream=True, stream_events=True):
        if hasattr(event, "reasoning_content"):
            reasoning_content_found = True

    assert reasoning_content_found, "reasoning_content should be found in the streaming responses"

    run_response = team.get_last_run_output()
    # Print the reasoning_content when received
    if run_response and hasattr(run_response, "reasoning_content") and run_response.reasoning_content:
        print("\n=== Gemini 2.5 reasoning (streaming) reasoning_content ===")
        print(run_response.reasoning_content)
        print("=========================================================\n")

    # Check the team's run_response directly after streaming is complete
    assert run_response is not None, "run_response should not be None"
    assert hasattr(run_response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert run_response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(run_response.reasoning_content) > 0, "reasoning_content should not be empty"


# ============================================================================
# VertexAI Claude Reasoning Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.skip(reason="Requires VertexAI credentials and actual API call")
def test_team_vertexai_claude_reasoning_non_streaming():
    """Test that Team reasoning works with VertexAI Claude (extended thinking) in non-streaming mode."""
    # Create a Team with VertexAI Claude reasoning model
    # Note: VertexAI Claude uses the same Claude class but with VertexAI provider
    team = Team(
        model=Claude(id="claude-sonnet-4-5-20250929", provider="VertexAI"),
        reasoning_model=Claude(
            id="claude-sonnet-4-5-20250929",
            provider="VertexAI",
            thinking={"type": "enabled", "budget_tokens": 512},
        ),
        members=[],
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Run the team in non-streaming mode
    response = team.run("What is the sum of the first 10 natural numbers?", stream=False)

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
def test_team_vertexai_claude_reasoning_streaming(shared_db):
    """Test that Team reasoning works with VertexAI Claude (extended thinking) in streaming mode."""
    # Create a Team with VertexAI Claude reasoning model
    team = Team(
        model=Claude(id="claude-sonnet-4-5-20250929", provider="VertexAI"),
        reasoning_model=Claude(
            id="claude-sonnet-4-5-20250929",
            provider="VertexAI",
            thinking={"type": "enabled", "budget_tokens": 512},
        ),
        db=shared_db,
        members=[],
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Consume all streaming responses
    reasoning_content_found = False
    for event in team.run("What is the value of 5! (factorial)?", stream=True, stream_events=True):
        if hasattr(event, "reasoning_content"):
            reasoning_content_found = True

    assert reasoning_content_found, "reasoning_content should be found in the streaming responses"

    run_response = team.get_last_run_output()
    # Print the reasoning_content when received
    if run_response and hasattr(run_response, "reasoning_content") and run_response.reasoning_content:
        print("\n=== VertexAI Claude reasoning (streaming) reasoning_content ===")
        print(run_response.reasoning_content)
        print("===============================================================\n")

    # Check the team's run_response directly after streaming is complete
    assert run_response is not None, "run_response should not be None"
    assert hasattr(run_response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert run_response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(run_response.reasoning_content) > 0, "reasoning_content should not be empty"


# ============================================================================
# OpenAI Reasoning Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.skip(reason="Requires OpenAI API key and actual API call")
def test_team_openai_reasoning_non_streaming():
    """Test that Team reasoning works with OpenAI reasoning models (o1/o3/o4) in non-streaming mode."""
    # Create a Team with OpenAI reasoning model
    team = Team(
        model=OpenAIChat(id="gpt-4o"),
        reasoning_model=OpenAIChat(id="o1-mini"),
        members=[],
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Run the team in non-streaming mode
    response = team.run("What is the sum of the first 10 natural numbers?", stream=False)

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
def test_team_openai_reasoning_streaming(shared_db):
    """Test that Team reasoning works with OpenAI reasoning models (o1/o3/o4) in streaming mode."""
    # Create a Team with OpenAI reasoning model
    team = Team(
        model=OpenAIChat(id="gpt-4o"),
        reasoning_model=OpenAIChat(id="o1-mini"),
        db=shared_db,
        members=[],
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Consume all streaming responses
    reasoning_content_found = False
    for event in team.run("What is the value of 5! (factorial)?", stream=True, stream_events=True):
        if hasattr(event, "reasoning_content"):
            reasoning_content_found = True

    assert reasoning_content_found, "reasoning_content should be found in the streaming responses"

    run_response = team.get_last_run_output()
    # Print the reasoning_content when received
    if run_response and hasattr(run_response, "reasoning_content") and run_response.reasoning_content:
        print("\n=== OpenAI reasoning (streaming) reasoning_content ===")
        print(run_response.reasoning_content)
        print("======================================================\n")

    # Check the team's run_response directly after streaming is complete
    assert run_response is not None, "run_response should not be None"
    assert hasattr(run_response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert run_response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(run_response.reasoning_content) > 0, "reasoning_content should not be empty"


# ============================================================================
# DeepSeek Reasoning Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.skip(reason="Requires DeepSeek API key and actual API call")
def test_team_deepseek_reasoning_non_streaming():
    """Test that Team reasoning works with DeepSeek reasoning model in non-streaming mode."""
    # Create a Team with DeepSeek reasoning model
    team = Team(
        model=DeepSeek(id="deepseek-chat"),
        reasoning_model=DeepSeek(id="deepseek-reasoner"),
        members=[],
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Run the team in non-streaming mode
    response = team.run("What is the sum of the first 10 natural numbers?", stream=False)

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
def test_team_deepseek_reasoning_streaming(shared_db):
    """Test that Team reasoning works with DeepSeek reasoning model in streaming mode."""
    # Create a Team with DeepSeek reasoning model
    team = Team(
        model=DeepSeek(id="deepseek-chat"),
        reasoning_model=DeepSeek(id="deepseek-reasoner"),
        db=shared_db,
        members=[],
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Consume all streaming responses
    reasoning_content_found = False
    for event in team.run("What is the value of 5! (factorial)?", stream=True, stream_events=True):
        if hasattr(event, "reasoning_content"):
            reasoning_content_found = True

    assert reasoning_content_found, "reasoning_content should be found in the streaming responses"

    run_response = team.get_last_run_output()
    # Print the reasoning_content when received
    if run_response and hasattr(run_response, "reasoning_content") and run_response.reasoning_content:
        print("\n=== DeepSeek reasoning (streaming) reasoning_content ===")
        print(run_response.reasoning_content)
        print("========================================================\n")

    # Check the team's run_response directly after streaming is complete
    assert run_response is not None, "run_response should not be None"
    assert hasattr(run_response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert run_response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(run_response.reasoning_content) > 0, "reasoning_content should not be empty"


# ============================================================================
# Groq Reasoning Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.skip(reason="Requires Groq API key and actual API call")
def test_team_groq_reasoning_non_streaming():
    """Test that Team reasoning works with Groq reasoning models (deepseek variants) in non-streaming mode."""
    # Create a Team with Groq reasoning model
    team = Team(
        model=Groq(id="llama-3.3-70b-versatile"),
        reasoning_model=Groq(id="deepseek-r1-distill-llama-70b"),
        members=[],
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Run the team in non-streaming mode
    response = team.run("What is the sum of the first 10 natural numbers?", stream=False)

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
def test_team_groq_reasoning_streaming(shared_db):
    """Test that Team reasoning works with Groq reasoning models (deepseek variants) in streaming mode."""
    # Create a Team with Groq reasoning model
    team = Team(
        model=Groq(id="llama-3.3-70b-versatile"),
        reasoning_model=Groq(id="deepseek-r1-distill-llama-70b"),
        db=shared_db,
        members=[],
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Consume all streaming responses
    reasoning_content_found = False
    for event in team.run("What is the value of 5! (factorial)?", stream=True, stream_events=True):
        if hasattr(event, "reasoning_content"):
            reasoning_content_found = True

    assert reasoning_content_found, "reasoning_content should be found in the streaming responses"

    run_response = team.get_last_run_output()
    # Print the reasoning_content when received
    if run_response and hasattr(run_response, "reasoning_content") and run_response.reasoning_content:
        print("\n=== Groq reasoning (streaming) reasoning_content ===")
        print(run_response.reasoning_content)
        print("====================================================\n")

    # Check the team's run_response directly after streaming is complete
    assert run_response is not None, "run_response should not be None"
    assert hasattr(run_response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert run_response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(run_response.reasoning_content) > 0, "reasoning_content should not be empty"


# ============================================================================
# Ollama Reasoning Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.skip(reason="Requires Ollama running locally and actual API call")
def test_team_ollama_reasoning_non_streaming():
    """Test that Team reasoning works with Ollama reasoning models (qwq, deepseek-r1, etc.) in non-streaming mode."""
    # Create a Team with Ollama reasoning model
    team = Team(
        model=Ollama(id="llama3.2"),
        reasoning_model=Ollama(id="qwq"),
        members=[],
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Run the team in non-streaming mode
    response = team.run("What is the sum of the first 10 natural numbers?", stream=False)

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
def test_team_ollama_reasoning_streaming(shared_db):
    """Test that Team reasoning works with Ollama reasoning models (qwq, deepseek-r1, etc.) in streaming mode."""
    # Create a Team with Ollama reasoning model
    team = Team(
        model=Ollama(id="llama3.2"),
        reasoning_model=Ollama(id="qwq"),
        db=shared_db,
        members=[],
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Consume all streaming responses
    reasoning_content_found = False
    for event in team.run("What is the value of 5! (factorial)?", stream=True, stream_events=True):
        if hasattr(event, "reasoning_content"):
            reasoning_content_found = True

    assert reasoning_content_found, "reasoning_content should be found in the streaming responses"

    run_response = team.get_last_run_output()
    # Print the reasoning_content when received
    if run_response and hasattr(run_response, "reasoning_content") and run_response.reasoning_content:
        print("\n=== Ollama reasoning (streaming) reasoning_content ===")
        print(run_response.reasoning_content)
        print("======================================================\n")

    # Check the team's run_response directly after streaming is complete
    assert run_response is not None, "run_response should not be None"
    assert hasattr(run_response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert run_response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(run_response.reasoning_content) > 0, "reasoning_content should not be empty"


# ============================================================================
# Azure AI Foundry Reasoning Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.skip(reason="Requires Azure AI Foundry credentials and actual API call")
def test_team_azure_ai_foundry_reasoning_non_streaming():
    """Test that Team reasoning works with Azure AI Foundry reasoning models in non-streaming mode."""
    # Create a Team with Azure AI Foundry reasoning model
    team = Team(
        model=AzureAIFoundry(id="gpt-4o"),
        reasoning_model=AzureAIFoundry(id="o1-mini"),
        members=[],
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Run the team in non-streaming mode
    response = team.run("What is the sum of the first 10 natural numbers?", stream=False)

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
def test_team_azure_ai_foundry_reasoning_streaming(shared_db):
    """Test that Team reasoning works with Azure AI Foundry reasoning models in streaming mode."""
    # Create a Team with Azure AI Foundry reasoning model
    team = Team(
        model=AzureAIFoundry(id="gpt-4o"),
        reasoning_model=AzureAIFoundry(id="o1-mini"),
        db=shared_db,
        members=[],
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            \
        """),
    )

    # Consume all streaming responses
    reasoning_content_found = False
    for event in team.run("What is the value of 5! (factorial)?", stream=True, stream_events=True):
        if hasattr(event, "reasoning_content"):
            reasoning_content_found = True

    assert reasoning_content_found, "reasoning_content should be found in the streaming responses"

    run_response = team.get_last_run_output()
    # Print the reasoning_content when received
    if run_response and hasattr(run_response, "reasoning_content") and run_response.reasoning_content:
        print("\n=== Azure AI Foundry reasoning (streaming) reasoning_content ===")
        print(run_response.reasoning_content)
        print("===============================================================\n")

    # Check the team's run_response directly after streaming is complete
    assert run_response is not None, "run_response should not be None"
    assert hasattr(run_response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert run_response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(run_response.reasoning_content) > 0, "reasoning_content should not be empty"


# ============================================================================
# Model Detection Tests (Unit-like tests without API calls)
# ============================================================================


def test_team_accepts_anthropic_claude_reasoning_model():
    """Test that Team can be instantiated with Anthropic Claude reasoning model."""
    try:
        team = Team(
            model=Claude(id="claude-sonnet-4-5-20250929"),
            reasoning_model=Claude(
                id="claude-sonnet-4-5-20250929",
                thinking={"type": "enabled", "budget_tokens": 512},
            ),
            members=[],
        )
        assert team.reasoning_model is not None
        assert team.reasoning_model.id == "claude-sonnet-4-5-20250929"
    except Exception as e:
        pytest.fail(f"Failed to create Team with Anthropic Claude reasoning model: {e}")


def test_team_accepts_gemini_reasoning_model():
    """Test that Team can be instantiated with Gemini 2.5+ reasoning model."""
    try:
        team = Team(
            model=Gemini(id="gemini-2.5-flash"),
            reasoning_model=Gemini(id="gemini-2.5-flash", thinking_budget=1024),
            members=[],
        )
        assert team.reasoning_model is not None
        assert team.reasoning_model.id == "gemini-2.5-flash"
    except Exception as e:
        pytest.fail(f"Failed to create Team with Gemini reasoning model: {e}")


def test_team_accepts_vertexai_claude_reasoning_model():
    """Test that Team can be instantiated with VertexAI Claude reasoning model."""
    try:
        team = Team(
            model=Claude(id="claude-sonnet-4-5-20250929", provider="VertexAI"),
            reasoning_model=Claude(
                id="claude-sonnet-4-5-20250929",
                provider="VertexAI",
                thinking={"type": "enabled", "budget_tokens": 512},
            ),
            members=[],
        )
        assert team.reasoning_model is not None
        assert team.reasoning_model.id == "claude-sonnet-4-5-20250929"
    except Exception as e:
        pytest.fail(f"Failed to create Team with VertexAI Claude reasoning model: {e}")


def test_team_accepts_openai_reasoning_model():
    """Test that Team can be instantiated with OpenAI reasoning model."""
    try:
        team = Team(
            model=OpenAIChat(id="gpt-4o"),
            reasoning_model=OpenAIChat(id="o1-mini"),
            members=[],
        )
        assert team.reasoning_model is not None
        assert team.reasoning_model.id == "o1-mini"
    except Exception as e:
        pytest.fail(f"Failed to create Team with OpenAI reasoning model: {e}")


def test_team_accepts_deepseek_reasoning_model():
    """Test that Team can be instantiated with DeepSeek reasoning model."""
    try:
        team = Team(
            model=DeepSeek(id="deepseek-chat"),
            reasoning_model=DeepSeek(id="deepseek-reasoner"),
            members=[],
        )
        assert team.reasoning_model is not None
        assert team.reasoning_model.id == "deepseek-reasoner"
    except Exception as e:
        pytest.fail(f"Failed to create Team with DeepSeek reasoning model: {e}")


def test_team_accepts_groq_reasoning_model():
    """Test that Team can be instantiated with Groq reasoning model."""
    try:
        team = Team(
            model=Groq(id="llama-3.3-70b-versatile"),
            reasoning_model=Groq(id="deepseek-r1-distill-llama-70b"),
            members=[],
        )
        assert team.reasoning_model is not None
        assert team.reasoning_model.id == "deepseek-r1-distill-llama-70b"
    except Exception as e:
        pytest.fail(f"Failed to create Team with Groq reasoning model: {e}")


def test_team_accepts_ollama_reasoning_model():
    """Test that Team can be instantiated with Ollama reasoning model."""
    try:
        team = Team(
            model=Ollama(id="llama3.2"),
            reasoning_model=Ollama(id="qwq"),
            members=[],
        )
        assert team.reasoning_model is not None
        assert team.reasoning_model.id == "qwq"
    except Exception as e:
        pytest.fail(f"Failed to create Team with Ollama reasoning model: {e}")


def test_team_accepts_azure_ai_foundry_reasoning_model():
    """Test that Team can be instantiated with Azure AI Foundry reasoning model."""
    try:
        team = Team(
            model=AzureAIFoundry(id="gpt-4o"),
            reasoning_model=AzureAIFoundry(id="o1-mini"),
            members=[],
        )
        assert team.reasoning_model is not None
        assert team.reasoning_model.id == "o1-mini"
    except Exception as e:
        pytest.fail(f"Failed to create Team with Azure AI Foundry reasoning model: {e}")
