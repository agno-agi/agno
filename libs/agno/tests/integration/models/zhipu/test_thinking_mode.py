import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.models.zhipu import Zhipu


def test_basic_thinking_mode():
    """Test basic thinking mode functionality"""
    agent = Agent(
        model=Zhipu(id="glm-4.7", enable_thinking=True),
        markdown=True,
        telemetry=False,
    )

    response = agent.run("Solve this step by step: What is 15 * 23?")

    assert response.content is not None
    # The thinking mode should provide more detailed reasoning
    assert len(response.content) > 20
    # Should contain the final answer
    assert "345" in response.content


def test_thinking_mode_with_math_problems():
    """Test thinking mode with complex math problems"""
    agent = Agent(
        model=Zhipu(id="glm-4.7", enable_thinking=True),
        markdown=True,
        telemetry=False,
    )

    response = agent.run("If a train travels 120 km in 2 hours, what is its average speed? Show your work.")

    assert response.content is not None
    # Should contain detailed reasoning
    assert len(response.content) > 30
    # Should contain the correct answer
    assert "60" in response.content


def test_thinking_mode_with_logic_puzzles():
    """Test thinking mode with logic puzzles"""
    agent = Agent(
        model=Zhipu(id="glm-4.7", enable_thinking=True),
        markdown=True,
        telemetry=False,
    )

    response = agent.run("""
    Three friends Alex, Ben, and Carol have different favorite colors: red, blue, and green.
    Alex doesn't like red. Ben's favorite color is not blue. The person who likes green is not Alex.
    What is each person's favorite color? Explain your reasoning.
    """)

    assert response.content is not None
    # Should contain detailed reasoning
    assert len(response.content) > 50
    # Should mention all three people
    assert "Alex" in response.content
    assert "Ben" in response.content
    assert "Carol" in response.content


def test_thinking_mode_with_code_generation():
    """Test thinking mode with code generation"""
    agent = Agent(
        model=Zhipu(id="glm-4.7", enable_thinking=True),
        markdown=True,
        telemetry=False,
    )

    response = agent.run(
        "Write a Python function to find the factorial of a number using recursion. Explain your approach."
    )

    assert response.content is not None
    # Should contain detailed explanation and code
    assert len(response.content) > 50
    assert "def " in response.content  # Should contain function definition
    assert "recursion" in response.content.lower() or "recursive" in response.content.lower()


def test_thinking_mode_with_structured_output():
    """Test thinking mode combined with structured output"""

    class Solution(BaseModel):
        problem: str = Field(..., description="The problem statement")
        approach: str = Field(..., description="Approach to solve the problem")
        steps: list = Field(..., description="Step-by-step solution")
        answer: str = Field(..., description="Final answer")

    agent = Agent(
        model=Zhipu(id="glm-4.7", enable_thinking=True),
        output_schema=Solution,
        telemetry=False,
    )

    response = agent.run("What is the sum of the first 10 natural numbers?")

    assert response.content is not None
    assert isinstance(response.content, Solution)
    assert response.content.problem is not None
    assert response.content.approach is not None
    assert isinstance(response.content.steps, list)
    assert response.content.answer is not None
    # Should contain the correct answer
    assert "55" in response.content.answer


@pytest.mark.asyncio
async def test_async_thinking_mode():
    """Test thinking mode with async calls"""
    agent = Agent(
        model=Zhipu(id="glm-4.7", enable_thinking=True),
        markdown=True,
        telemetry=False,
    )

    response = await agent.arun("Explain how photosynthesis works step by step.")

    assert response.content is not None
    # Should contain detailed explanation
    assert len(response.content) > 50


@pytest.mark.asyncio
async def test_async_thinking_mode_stream():
    """Test thinking mode with async streaming"""
    agent = Agent(
        model=Zhipu(id="glm-4.7", enable_thinking=True),
        markdown=True,
        telemetry=False,
    )

    responses = []
    async for chunk in agent.arun("Explain the process of cellular respiration step by step.", stream=True):
        responses.append(chunk)

    full_content = "".join(r.content or "" for r in responses)
    assert len(full_content) > 50


def test_thinking_mode_with_tools():
    """Test thinking mode combined with tool use"""

    def get_stock_price(symbol: str) -> str:
        """Get the current price of a stock.

        Args:
            symbol: The stock symbol (e.g. TSLA, AAPL)
        """
        return f"The current price of {symbol} is $100.00"

    agent = Agent(
        model=Zhipu(id="glm-4.7", enable_thinking=True),
        tools=[get_stock_price],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("Analyze TSLA stock and provide investment advice with detailed reasoning.")

    assert response.content is not None
    # Should contain tool calls
    assert any(msg.tool_calls for msg in response.messages)
    # Should contain detailed analysis
    assert len(response.content) > 50


def test_thinking_mode_vs_regular_mode():
    """Compare thinking mode vs regular mode responses"""
    thinking_agent = Agent(
        model=Zhipu(id="glm-4.7", enable_thinking=True),
        markdown=True,
        telemetry=False,
    )

    regular_agent = Agent(
        model=Zhipu(id="glm-4.7", enable_thinking=False),
        markdown=True,
        telemetry=False,
    )

    thinking_response = thinking_agent.run("Explain why the sky is blue in detail.")
    regular_response = regular_agent.run("Explain why the sky is blue in detail.")

    # Both should have content
    assert thinking_response.content is not None
    assert regular_response.content is not None

    # Thinking mode should generally provide more detailed response
    # (This is a heuristic test, actual length may vary)
    assert len(thinking_response.content) >= len(regular_response.content) * 0.8


def test_thinking_mode_with_json_mode():
    """Test thinking mode combined with simple JSON mode"""
    from pydantic import BaseModel, Field

    class Analysis(BaseModel):
        topic: str = Field(..., description="Topic being analyzed")
        reasoning: str = Field(..., description="Step-by-step reasoning")
        conclusion: str = Field(..., description="Final conclusion")

    agent = Agent(
        model=Zhipu(id="glm-4.7", enable_thinking=True),
        output_schema=Analysis,
        use_json_mode=True,  # Use simple JSON mode instead of native structured outputs
        telemetry=False,
    )

    response = agent.run("Analyze the impact of renewable energy on climate change.")

    assert response.content is not None
    assert isinstance(response.content, Analysis)
    assert response.content.topic is not None
    assert response.content.reasoning is not None
    assert response.content.conclusion is not None
    # Should contain detailed reasoning
    assert len(response.content.reasoning) > 20


def test_thinking_mode_with_complex_problem_solving():
    """Test thinking mode with complex problem solving"""
    agent = Agent(
        model=Zhipu(id="glm-4.7", enable_thinking=True),
        markdown=True,
        telemetry=False,
    )

    response = agent.run("""
    You have a 5-gallon jug and a 3-gallon jug, and unlimited water. 
    How can you measure exactly 4 gallons of water? Explain your step-by-step solution.
    """)

    assert response.content is not None
    # Should contain detailed step-by-step solution
    assert len(response.content) > 50
    # Should mention the jugs
    assert "gallon" in response.content.lower()
    # Should contain the solution
    assert "4" in response.content
