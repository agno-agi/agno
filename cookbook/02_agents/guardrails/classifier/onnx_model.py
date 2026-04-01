"""ClassifierGuardrail with ONNX backend - optimized inference."""

from pathlib import Path

from agno.agent import Agent
from agno.guardrails.classifier import ClassifierGuardrail
from agno.models.openai import OpenAIChat

models_dir = Path(__file__).parent / "models"

guardrail = ClassifierGuardrail(
    model=str(models_dir / "spam_classifier.onnx"),
    model_type="onnx",
    vectorizer_path=str(models_dir / "tfidf_vectorizer.pkl"),
    categories=["safe", "spam", "malicious"],
    blocked_categories=["spam", "malicious"],
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    pre_hooks=[guardrail],
    instructions=["You are a helpful assistant."],
)

if __name__ == "__main__":
    response = agent.run("Hello, how are you?")
    print(
        f"Safe input  -> Status: {response.status.value}, Content: {response.content[:80]}"
    )

    response = agent.run("Buy cheap watches now! Limited offer!")
    print(
        f"Spam input  -> Status: {response.status.value}, Content: {response.content[:80]}"
    )
