from pydantic import BaseModel

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team


def test_route_team_basic():
    """Test basic functionality of a route team."""

    def get_weather(city: str) -> str:
        return f"The weather in {city} is sunny."

    def get_stock_price(symbol: str) -> str:
        return f"The stock price of {symbol} is $100."

    web_agent = Agent(
        name="Weather Agent",
        model=OpenAIChat("gpt-4o"),
        role="Search the web for weather information",
        tools=[get_weather],
    )

    finance_agent = Agent(
        name="Finance Agent",
        model=OpenAIChat("gpt-4o"),
        role="Get financial data",
        tools=[get_stock_price],
    )

    team = Team(name="Router Team", mode="route", model=OpenAIChat("gpt-4o"), members=[web_agent, finance_agent])

    # This should route to the finance agent
    response = team.run("What is the current stock price of AAPL?")

    assert response.content is not None
    assert isinstance(response.content, str)
    assert len(response.content) > 0
    assert len(response.member_responses) == 1
    assert response.member_responses[0].agent_id == finance_agent.agent_id
    assert team.session_id is not None
    assert team.session_id == finance_agent.team_session_id


def test_route_team_structured_output():
    """Test basic functionality of a route team."""

    class StockInfo(BaseModel):
        symbol: str
        price: str

    def get_weather(city: str) -> str:
        return f"The weather in {city} is sunny."

    def get_stock_price(symbol: str) -> str:
        return f"The stock price of {symbol} is $100."

    web_agent = Agent(
        name="Weather Agent",
        model=OpenAIChat("gpt-4o"),
        role="Search the web for weather information",
        tools=[get_weather],
    )

    finance_agent = Agent(
        name="Finance Agent",
        model=OpenAIChat("gpt-4o"),
        response_model=StockInfo,
        role="Get financial data",
        tools=[get_stock_price],
    )

    team = Team(name="Router Team", mode="route", model=OpenAIChat("gpt-4o"), members=[web_agent, finance_agent])

    # This should route to the finance agent
    response = team.run("What is the current stock price of AAPL?")

    assert response.content is not None
    assert isinstance(response.content, StockInfo)
    assert response.content.symbol is not None
    assert response.content.price is not None
    member_responses = response.member_responses
    assert len(member_responses) == 1
    assert response.member_responses[0].agent_id == finance_agent.agent_id


def test_route_team_with_multiple_agents():
    """Test route team routing to multiple agents."""

    def get_weather(city: str) -> str:
        return f"The weather in {city} is sunny."

    def get_stock_price(symbol: str) -> str:
        return f"The stock price of {symbol} is $100."

    web_agent = Agent(
        name="Weather Agent",
        model=OpenAIChat("gpt-4o"),
        role="Search the web for weather information",
        tools=[get_weather],
    )

    finance_agent = Agent(
        name="Finance Agent",
        model=OpenAIChat("gpt-4o"),
        role="Get financial data",
        tools=[get_stock_price],
    )

    analysis_agent = Agent(name="Analysis Agent", model=OpenAIChat("gpt-4o"), role="Analyze data and provide insights")

    team = Team(
        name="Multi-Router Team",
        mode="route",
        model=OpenAIChat("gpt-4o"),
        members=[web_agent, finance_agent, analysis_agent],
    )

    # This should route to both finance and web agents
    response = team.run("Compare the stock performance of AAPL with recent tech industry news")

    assert response.content is not None
    assert isinstance(response.content, str)
    assert len(response.content) > 0
    # Should have routed to at least 2 agents
    assert len(response.member_responses) >= 2


def test_route_team_with_expected_output():
    """Test route team with expected output specification."""
    qa_agent = Agent(name="QA Agent", model=OpenAIChat("gpt-4o"), role="Answer general knowledge questions")

    math_agent = Agent(name="Math Agent", model=OpenAIChat("gpt-4o"), role="Solve mathematical problems")

    team = Team(
        name="Specialized Router Team", mode="route", model=OpenAIChat("gpt-4o"), members=[qa_agent, math_agent]
    )

    # This should route to the math agent with specific expected output
    response = team.run("Calculate the area of a circle with radius 5 units")

    assert response.content is not None
    assert isinstance(response.content, str)
    assert len(response.content) > 0
    assert len(response.member_responses) == 1
    assert response.member_responses[0].agent_id == math_agent.agent_id


def test_route_team_multiple_calls():
    """Test basic functionality of a route team."""

    def get_weather(city: str) -> str:
        return f"The weather in {city} is sunny."

    def get_stock_price(symbol: str) -> str:
        return f"The stock price of {symbol} is $100."

    web_agent = Agent(
        name="Weather Agent",
        agent_id="web-agent",
        model=OpenAIChat("gpt-4o"),
        role="Search the web for weather information",
        tools=[get_weather],
    )

    finance_agent = Agent(
        name="Finance Agent",
        agent_id="finance-agent",
        model=OpenAIChat("gpt-4o"),
        role="Get financial data",
        tools=[get_stock_price],
    )

    team = Team(name="Router Team", mode="route", model=OpenAIChat("gpt-4o"), members=[web_agent, finance_agent])

    # This should route to the finance agent
    response = team.run("What is the current stock price of AAPL?")
    assert response.tools[0].tool_name == "forward_task_to_member"
    assert response.tools[0].tool_args["member_id"] == finance_agent.agent_id

    assert response.member_responses[0].agent_id == finance_agent.agent_id
    assert "What is the current stock price of AAPL?" in response.member_responses[0].messages[1].content

    # This should route to the weather agent
    response = team.run("What is the weather in Tokyo?")
    assert response.tools[0].tool_name == "forward_task_to_member"
    assert response.tools[0].tool_args["member_id"] == web_agent.agent_id
    assert response.member_responses[0].agent_id == web_agent.agent_id
    assert "What is the weather in Tokyo?" in response.member_responses[0].messages[1].content
