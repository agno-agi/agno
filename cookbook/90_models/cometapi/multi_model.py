"""Example showcasing different models available through CometAPI."""

from agno.agent import Agent
from agno.models.cometapi import CometAPI

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


def test_model(
    model_id: str,
    prompt: str = "Explain what makes you unique as an AI model in 2-3 sentences.",
):
    """Test a specific model with a given prompt."""
    print(f"\nTesting {model_id}:")
    print("=" * 50)

    try:
        agent = Agent(model=CometAPI(id=model_id), markdown=True)
        agent.print_response(prompt)
    except Exception as e:
        print(f"[ERROR] Error with {model_id}: {e}")


def main():
    """Showcase different models available through CometAPI."""
    print("CometAPI Multi-Model Showcase")
    print("This example demonstrates different AI models accessible through CometAPI")

    # Test different model categories
    models_to_test = [
        # OpenAI models
        ("gpt-5.2", "Latest GPT-5 Mini model"),
        # Anthropic models
        ("claude-sonnet-4-20250514", "Claude Sonnet 4"),
        # Google models
        ("gemini-2.5-pro", "Gemini 2.5 Pro"),
        ("gemini-3-flash-preview", "Gemini 3 Flash Preview"),
        # DeepSeek models
        ("deepseek-v3", "DeepSeek V3"),
        ("deepseek-chat", "DeepSeek Chat"),
    ]

    for model_id, description in models_to_test:
        print(f"\n{description}")
        test_model(model_id)

        # Pause between models for readability
        # input("\nPress Enter to continue to the next model...")

    print("\nMulti-model showcase complete!")
    print("Learn more about CometAPI at: https://www.cometapi.com/")


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    main()
