"""
Example demonstrating output transformation using post-hooks with Agno Agent.

This example shows how to:
1. Transform agent responses by updating RunOutput.content
2. Add formatting, structure, and additional information
3. Enhance the user experience through content modification
"""

from datetime import datetime

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.agent import RunOutput
from pydantic import BaseModel


class FormattedResponse(BaseModel):
    main_content: str
    key_points: list[str]
    disclaimer: str
    follow_up_questions: list[str]


def add_markdown_formatting(run_output: RunOutput) -> None:
    """
    Simple post-hook: Add basic markdown formatting to the response.

    Enhances readability by adding proper markdown structure.
    """
    content = run_output.content.strip()

    # Add markdown formatting for better presentation
    formatted_content = f"""# Response

{content}

---
*Generated at {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}*"""

    run_output.content = formatted_content


def add_disclaimer_and_timestamp(run_output: RunOutput) -> None:
    """
    Simple post-hook: Add a disclaimer and timestamp to responses.

    Useful for agents providing advice or information that needs context.
    """
    content = run_output.content.strip()

    enhanced_content = f"""{content}

---
**Important:** This information is for educational purposes only. 
Please consult with appropriate professionals for personalized advice.

*Response generated on {datetime.now().strftime("%B %d, %Y at %I:%M %p")}*"""

    run_output.content = enhanced_content


def structure_financial_advice(run_output: RunOutput) -> None:
    """
    Advanced post-hook: Structure financial advice responses with AI assistance.

    Uses an AI agent to format the response into a structured format
    with key points, disclaimers, and follow-up suggestions.
    """

    # Create a formatting agent
    formatter_agent = Agent(
        name="Response Formatter",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions=[
            "You are a response formatting specialist.",
            "Transform the given response into a well-structured format with:",
            "1. MAIN_CONTENT: The core response, well-formatted and clear",
            "2. KEY_POINTS: Extract 3-4 key takeaways as concise bullet points",
            "3. DISCLAIMER: Add appropriate disclaimer for financial advice",
            "4. FOLLOW_UP_QUESTIONS: Suggest 2-3 relevant follow-up questions",
            "",
            "Maintain the original meaning while improving structure and readability.",
        ],
        output_schema=FormattedResponse,
    )

    try:
        formatted_result = formatter_agent.run(
            input=f"Format and structure this response: '{run_output.content}'"
        )

        formatted = formatted_result.content

        # Build enhanced response with structured formatting
        enhanced_response = f"""## Financial Guidance

{formatted.main_content}

### Key Takeaways
{chr(10).join([f"• {point}" for point in formatted.key_points])}

### Important Disclaimer
{formatted.disclaimer}

### Questions to Consider Next
{chr(10).join([f"{i + 1}. {question}" for i, question in enumerate(formatted.follow_up_questions)])}

---
*Response formatted on {datetime.now().strftime("%Y-%m-%d at %H:%M:%S")}*"""

        # Update the run output with the enhanced response
        run_output.content = enhanced_response

    except Exception as e:
        # Fallback to simple formatting if AI formatting fails
        print(f"Warning: Advanced formatting failed ({e}), using simple format")
        add_disclaimer_and_timestamp(run_output)


def main():
    """Demonstrate output transformation post-hooks."""
    print("🎨 Output Transformation Post-Hook Examples")
    print("=" * 60)

    # Test 1: Simple markdown formatting
    print("\n📝 Test 1: Markdown formatting transformation")
    print("-" * 50)

    markdown_agent = Agent(
        name="Documentation Assistant",
        model=OpenAIChat(id="gpt-4o-mini"),
        post_hooks=[add_markdown_formatting],
        instructions=["Provide clear, helpful explanations on technical topics."],
    )

    markdown_agent.print_response(
        input="What is version control and why is it important?"
    )
    print("✅ Response with markdown formatting")

    # Test 2: Disclaimer and timestamp
    print("\n⚠️  Test 2: Disclaimer and timestamp transformation")
    print("-" * 50)

    advice_agent = Agent(
        name="General Advisor",
        model=OpenAIChat(id="gpt-4o-mini"),
        post_hooks=[add_disclaimer_and_timestamp],
        instructions=["Provide helpful general advice and guidance."],
    )

    advice_agent.print_response(
        input="What are some good study habits for college students?"
    )
    print("✅ Response with disclaimer and timestamp")

    # Test 3: Advanced financial advice structuring
    print("\n💰 Test 3: Structured financial advice transformation")
    print("-" * 50)

    financial_agent = Agent(
        name="Financial Advisor",
        model=OpenAIChat(id="gpt-4o-mini"),
        post_hooks=[structure_financial_advice],
        instructions=[
            "You are a knowledgeable financial advisor.",
            "Provide clear investment and financial planning guidance.",
            "Focus on general principles and best practices.",
        ],
    )

    financial_agent.print_response(
        input="I'm 30 years old and want to start investing. I can save $500 per month. What should I know?"
    )
    print("✅ Structured financial advice response")


if __name__ == "__main__":
    main()
