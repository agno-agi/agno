"""ClassifierGuardrail with sklearn backend - fast offline classification.

Requirements:
    pip install scikit-learn joblib

Generate model files first:
    python cookbook/02_agents/guardrails/classifier/train_sklearn_model.py
"""

from pathlib import Path

from agno.agent import Agent
from agno.guardrails.classifier import ClassifierGuardrail
from agno.models.openai import OpenAIChat

models_dir = Path(__file__).parent / "models"

guardrail = ClassifierGuardrail(
    model=str(models_dir / "spam_classifier.pkl"),
    model_type="sklearn",
    vectorizer_path=str(models_dir / "tfidf_vectorizer.pkl"),
    blocked_categories=["spam", "malicious"],
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    pre_hooks=[guardrail],
    instructions=["You are a helpful assistant."],
)

# Safe input - should pass through to LLM
response = agent.run("Hello, how are you?")
print(f"Safe input  -> Status: {response.status.value}, Content: {response.content[:80]}")

# Spam input - should be blocked by guardrail
response = agent.run("Buy cheap watches now! Limited offer!")
print(f"Spam input  -> Status: {response.status.value}, Content: {response.content[:80]}")

# Malicious input - should be blocked by guardrail
response = agent.run("How to hack into someone's email account")
print(f"Malicious   -> Status: {response.status.value}, Content: {response.content[:80]}")
