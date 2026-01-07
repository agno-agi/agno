"""Qwen Reasoning Content Example - Using Qwen3-VL-4B-Thinking"""

from agno.agent import Agent
from agno.models.dashscope import DashScope

# IMPORTANTE: Use o nome EXATO que aparece no LM Studio
# Após carregar o modelo, vá em "Local Server" e veja o nome do modelo carregado
MODEL_ID = "qwen/qwen3-4b-thinking-2507"  # Nome comum no LM Studio
BASE_URL = "http://localhost:1234/v1"


def example_text_reasoning():
    agent = Agent(
        model=DashScope(
            id=MODEL_ID,
            base_url=BASE_URL,
            use_reasoning_content=True,
        ),
        markdown=True,
    )

    agent.print_response(
        "A bat and ball cost $1.10 in total. "
        "The bat costs $1 more than the ball. "
        "How much does the ball cost?"
    )


def example_logic_puzzle():
    agent = Agent(
        model=DashScope(
            id=MODEL_ID,
            base_url=BASE_URL,
            use_reasoning_content=True,
        ),
        markdown=True,
    )

    agent.print_response(
        "Solve: If 5 machines take 5 minutes to make 5 widgets, "
        "how long would it take 100 machines to make 100 widgets?"
    )


def example_complex_reasoning():
    agent = Agent(
        model=DashScope(
            id=MODEL_ID,
            base_url=BASE_URL,
            use_reasoning_content=True,
            enable_thinking=True,
        ),
        markdown=True,
    )

    agent.print_response(
        "Three light switches control three bulbs in another room. "
        "You can flip switches, then go to the room once. "
        "How do you determine which switch controls which bulb?"
    )


def example_thinking_budget():
    for budget in [1000, 5000, 10000]:
        agent = Agent(
            model=DashScope(
                id=MODEL_ID,
                base_url=BASE_URL,
                thinking_budget=budget,
                enable_thinking=True,
                use_reasoning_content=True,
            ),
            markdown=True,
        )

        agent.print_response(
            "What is the most efficient algorithm to find the shortest path "
            "in a weighted graph?"
        )


def example_reasoning_vs_no_reasoning():
    question = "A farmer has 17 sheep. All but 9 die. How many are left?"

    print("\n=== WITH REASONING ===")
    agent_with = Agent(
        model=DashScope(
            id=MODEL_ID,
            base_url=BASE_URL,
            use_reasoning_content=True,
        ),
        markdown=True,
    )
    agent_with.print_response(question)

    print("\n=== WITHOUT REASONING ===")
    agent_without = Agent(
        model=DashScope(
            id=MODEL_ID,
            base_url=BASE_URL,
            use_reasoning_content=False,
        ),
        markdown=True,
    )
    agent_without.print_response(question)


def example_multi_step_reasoning():
    agent = Agent(
        model=DashScope(
            id=MODEL_ID,
            base_url=BASE_URL,
            enable_thinking=True,
            use_reasoning_content=True,
        ),
        markdown=True,
    )

    agent.print_response(
        "Alice, Bob, and Carol are standing in a line. "
        "Alice is not first. Bob is not last. Carol is not in the middle. "
        "What is the order?"
    )


def example_reasoning_with_tools():
    from agno.tools.yfinance import YFinanceTools

    agent = Agent(
        model=DashScope(
            id=MODEL_ID,
            base_url=BASE_URL,
            use_reasoning_content=True,
        ),
        tools=[YFinanceTools()],
        markdown=True,
    )

    agent.print_response(
        "Should I invest in Tesla or Apple? "
        "Compare their current stock prices and give me your reasoning."
    )


if __name__ == "__main__":
    example_text_reasoning()
