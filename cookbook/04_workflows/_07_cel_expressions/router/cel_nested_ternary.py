"""Router with CEL: nested ternary for multi-way routing on input.

Uses chained ternary operators to route to one of several
handlers based on keywords in the input.

Requirements:
    pip install cel-python
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow import CEL_AVAILABLE, Step, Workflow
from agno.workflow.router import Router

if not CEL_AVAILABLE:
    print("CEL is not available. Install with: pip install cel-python")
    exit(1)

python_agent = Agent(
    name="Python Expert",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are a Python expert. Provide Python-specific help.",
    markdown=True,
)

js_agent = Agent(
    name="JavaScript Expert",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are a JavaScript expert. Provide JS-specific help.",
    markdown=True,
)

rust_agent = Agent(
    name="Rust Expert",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are a Rust expert. Provide Rust-specific help.",
    markdown=True,
)

general_agent = Agent(
    name="General Dev",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are a general software development expert.",
    markdown=True,
)

workflow = Workflow(
    name="CEL Nested Ternary Router",
    steps=[
        Router(
            name="Language Router",
            selector=(
                'input.contains("python") ? "Python Expert" : '
                'input.contains("javascript") || input.contains("js") ? "JavaScript Expert" : '
                'input.contains("rust") ? "Rust Expert" : '
                '"General Dev"'
            ),
            choices=[
                Step(name="Python Expert", agent=python_agent),
                Step(name="JavaScript Expert", agent=js_agent),
                Step(name="Rust Expert", agent=rust_agent),
                Step(name="General Dev", agent=general_agent),
            ],
        ),
    ],
)

if __name__ == "__main__":
    print("--- Python question ---")
    workflow.print_response(input="How do I use async/await in python?")
    print()

    print("--- Rust question ---")
    workflow.print_response(input="Explain ownership and borrowing in rust.")
    print()

    print("--- General question ---")
    workflow.print_response(input="What is a good database for a new project?")
