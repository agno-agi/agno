"""
Standalone usage of DSPy with Agno's .run() and .print_response() methods.

Requirements:
    pip install dspy

Usage:
    .venvs/demo/bin/python cookbook/frameworks/dspy/dspy_basic.py
"""

import dspy
from agno.agents.dspy import DSPyAgent

# ----- Configure DSPy LM (must be set on the main thread) -----
lm = dspy.LM("openai/gpt-5.4")
dspy.configure(lm=lm)

# ----- Basic Q&A with ChainOfThought -----
agent = DSPyAgent(
    name="DSPy Q&A",
    program=dspy.ChainOfThought("question -> answer"),
)

# Streaming
agent.print_response("What is quantum computing?", stream=True)

# Non-streaming
agent.print_response("Explain the theory of relativity in simple terms", stream=False)
