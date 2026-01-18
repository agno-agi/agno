"""
This example demonstrates a team of AI agents working together to answer questions in different languages.

The team consists of six specialized agents:
1. English Agent - Can only answer in English
2. Japanese Agent - Can only answer in Japanese
3. Chinese Agent - Can only answer in Chinese
4. Spanish Agent - Can only answer in Spanish
5. French Agent - Can only answer in French
6. German Agent - Can only answer in German

The team leader routes the user's question to the appropriate language agent. It can only forward the question and cannot answer itself.
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team

english_agent = Agent(
    name="English Agent",
    role="You only answer in English",
    model=OpenAIChat(id="o3-mini"),
)
japanese_agent = Agent(
    name="Japanese Agent",
    role="You only answer in Japanese",
    model=OpenAIChat(id="o3-mini"),
)
chinese_agent = Agent(
    name="Chinese Agent",
    role="You only answer in Chinese",
    model=OpenAIChat(id="o3-mini"),
)
spanish_agent = Agent(
    name="Spanish Agent",
    role="You can only answer in Spanish",
    model=OpenAIChat(id="o3-mini"),
)
french_agent = Agent(
    name="French Agent",
    role="You can only answer in French",
    model=OpenAIChat(id="o3-mini"),
)
german_agent = Agent(
    name="German Agent",
    role="You can only answer in German",
    model=OpenAIChat(id="o3-mini"),
)

multi_language_team = Team(
    name="Multi Language Team",
    model=OpenAIChat("o3-mini"),
    respond_directly=True,
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


async def main():
    """Main async function demonstrating team routing mode."""
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


if __name__ == "__main__":
    asyncio.run(main())
