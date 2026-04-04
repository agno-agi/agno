import os
from bindu.penguin.bindufy import bindufy
from agno.agent import Agent
from agno.models.openrouter import OpenRouter
from textwrap import dedent
from dotenv import load_dotenv

load_dotenv()

# Define your agent
agent = Agent(
    name="Quiz Generator Agent",
    description="Educational Assessment Expert specializing in MCQ generation.",
    instructions=dedent("""\
            You are a professional teacher. Your task is to generate a quiz based on the provided text.
            
            1. Create exactly 10 Multiple Choice Questions (MCQs).
            2. For each question, provide 4 options: A, B, C, and D.
            3. Ensure only one answer is correct.
            4. Provide a 1-sentence explanation for why the correct answer is right.
            5. Keep the language clear and academic.
        """),
    expected_output=dedent("""\
            # 📝 Quiz: Knowledge Check
            
            ---
            
            ### Question 1
            [Question text here]
            A) [Option A]
            B) [Option B]
            C) [Option C]
            D) [Option D]
            
            **Correct Answer:** [A/B/C/D]
            **Explanation:** [Brief explanation]
            
            ---
            (Repeat for questions 2 through 10)
        """),
    markdown=True,
    model=OpenRouter(
        id="openai/gpt-oss-120b",
        api_key=os.getenv("OPENROUTER_API_KEY")
    ),
    
)


# Configuration
# Note: Infrastructure configs (storage, scheduler, sentry, API keys) are now
# automatically loaded from environment variables. See .env.example for details.
config = {
    "author": "your.email@example.com",
    "name": "quiz_generator_agent",
    "description": "Educational assessment expert for MCQ generation",
    "deployment": {
            "url": "http://localhost:3773",
            "expose": True,
            "cors_origins": ["http://localhost:5173"]
        },
    "skills": ["skills"],
}


# Handler function
def handler(messages: list[dict[str, str]]):
    """Process messages and return agent response.

    Args:
        messages: List of message dictionaries containing conversation history

    Returns:
        Agent response result
    """
    result = agent.run(input=messages)
    return result


# Bindu-fy it
bindufy(config, handler)
