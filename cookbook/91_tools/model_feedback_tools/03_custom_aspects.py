"""
Custom Aspects and System Prompt
=================================
Customize what the feedback model evaluates. You can:

1. Change the `aspects` list to focus on what matters for your use case
2. Override the entire `system_prompt` for full control over the critique

This example shows a code tutorial reviewer that evaluates responses
on domain-specific criteria like code quality and beginner-friendliness.
"""

from agno.agent import Agent
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat
from agno.tools.model_feedback import ModelFeedbackTools

# ---------------------------------------------------------------------------
# Example 1: Custom aspects (uses the built-in prompt template)
# ---------------------------------------------------------------------------

coding_tutor = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        ModelFeedbackTools(
            model=Gemini(id="gemini-2.0-flash"),
            aspects=[
                "technical_accuracy",
                "beginner_friendliness",
                "code_quality",
                "practical_examples",
            ],
        )
    ],
    instructions=[
        "You are a coding tutor for beginners.",
        "After drafting your explanation, use get_feedback to check quality.",
        "Pay special attention to feedback about beginner friendliness.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Example 2: Fully custom system prompt
# ---------------------------------------------------------------------------

medical_writer = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        ModelFeedbackTools(
            model=Gemini(id="gemini-2.0-flash"),
            system_prompt=(
                "You are a medical content reviewer. Evaluate the AI assistant's response for:\n"
                "1. Scientific accuracy - Are claims supported by current medical consensus?\n"
                "2. Safety - Does the response include appropriate disclaimers?\n"
                "3. Readability - Is it accessible to a general audience?\n"
                "4. Actionability - Does it provide clear next steps?\n\n"
                "Respond in JSON format:\n"
                "{\n"
                '  "overall_rating": <1-10>,\n'
                '  "aspects": {\n'
                '    "<aspect>": {"rating": <1-10>, "comment": "<text>"}\n'
                "  },\n"
                '  "suggestions": ["<suggestion>"],\n'
                '  "summary": "<overall assessment>"\n'
                "}"
            ),
        )
    ],
    instructions=[
        "You provide general health information.",
        "Always include a disclaimer to consult a healthcare professional.",
        "After drafting, use get_feedback to verify accuracy and safety.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("CODING TUTOR (custom aspects)")
    print("=" * 60)
    coding_tutor.print_response(
        "Explain Python list comprehensions with examples",
        stream=True,
    )

    print("\n" + "=" * 60)
    print("MEDICAL WRITER (custom system prompt)")
    print("=" * 60)
    medical_writer.print_response(
        "What are the common symptoms of iron deficiency?",
        stream=True,
    )
