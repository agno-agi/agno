"""ClassifierGuardrail with transformers backend - HuggingFace models.

Requirements: pip install transformers torch

Downloads the model on first run (~500MB).
"""

from agno.agent import Agent
from agno.guardrails.classifier import ClassifierGuardrail
from agno.models.openai import OpenAIChat

guardrail = ClassifierGuardrail(
    model="facebook/roberta-hate-speech-dynabench-r4-target",
    model_type="transformers",
    blocked_categories=["hate"],
    device="cpu",
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    pre_hooks=[guardrail],
    instructions=["You are a helpful assistant."],
)

# Safe input - classified as "nothate", passes through
response = agent.run("Hello, how are you?")
print(f"Safe input -> Status: {response.status.value}, Content: {response.content[:80]}")

# Hateful input - classified as "hate", blocked by guardrail
response = agent.run("I absolutely despise and hate all people from that country")
print(f"Hate input -> Status: {response.status.value}, Content: {response.content[:80]}")
