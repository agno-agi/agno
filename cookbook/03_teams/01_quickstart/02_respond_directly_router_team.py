"""
Respond Directly Router Team
=============================

Demonstrates routing multilingual requests to specialized members with direct responses.
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team import Team, TeamMode

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
english_agent = Agent(
    name="English Agent",
    role="You only answer in English",
    model=OpenAIResponses(id="gpt-5-mini"),
)
japanese_agent = Agent(
    name="Japanese Agent",
    role="You only answer in Japanese",
    model=OpenAIResponses(id="gpt-5-mini"),
)
chinese_agent = Agent(
    name="Chinese Agent",
    role="You only answer in Chinese",
    model=OpenAIResponses(id="gpt-5-mini"),
)
spanish_agent = Agent(
    name="Spanish Agent",
    role="You can only answer in Spanish",
    model=OpenAIResponses(id="gpt-5-mini"),
)
french_agent = Agent(
    name="French Agent",
    role="You can only answer in French",
    model=OpenAIResponses(id="gpt-5-mini"),
)
german_agent = Agent(
    name="German Agent",
    role="You can only answer in German",
    model=OpenAIResponses(id="gpt-5-mini"),
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
multi_language_team = Team(
    name="Multi Language Team",
    model=OpenAIResponses(id="gpt-5-mini"),
    mode=TeamMode.route,
    members=[
        english_agent,
        spanish_agent,
        japanese_agent,
        french_agent,
        german_agent,
        chinese_agent,
    ],
    markdown=True,
    instructions=[
        "You are a language router that directs questions to the appropriate language agent.",
        "If the user asks in a language whose agent is not a team member, respond in English with:",
        "'I can only answer in the following languages: English, Spanish, Japanese, French and German. Please ask your question in one of these languages.'",
        "Always check the language of the user's input before routing to an agent.",
        "For unsupported languages like Italian, respond in English with the above message.",
    ],
    show_members_responses=True,
)


async def run_async_router() -> None:
    # Ask "How are you?" in all supported languages
    await multi_language_team.aprint_response(
        "How are you?",
        stream=True,  # English
    )

    await multi_language_team.aprint_response(
        "你好吗？",
        stream=True,  # Chinese
    )

    await multi_language_team.aprint_response(
        "お元気ですか?",
        stream=True,  # Japanese
    )

    await multi_language_team.aprint_response("Comment allez-vous?", stream=True)

    await multi_language_team.aprint_response(
        "Wie geht es Ihnen?",
        stream=True,  # German
    )

    await multi_language_team.aprint_response(
        "Come stai?",
        stream=True,  # Italian
    )


# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    multi_language_team.print_response("How are you?", stream=True)

    # --- Async ---
    asyncio.run(run_async_router())
