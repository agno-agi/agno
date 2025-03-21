from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.deepseek import DeepSeek
from agno.models.mistral import MistralChat
from agno.models.openai import OpenAIChat
from agno.team.team import Team

english_agent = Agent(
    name="English Agent",
    role="You can only answer in English",
    model=OpenAIChat(id="gpt-4.5-preview"),
    instructions=[
        "You must only respond in English",
    ],
)

japanese_agent = Agent(
    name="Japanese Agent",
    role="You can only answer in Japanese",
    model=DeepSeek(id="deepseek-chat"),
    instructions=[
        "You must only respond in Japanese",
    ],
)
chinese_agent = Agent(
    name="Chinese Agent",
    role="You can only answer in Chinese",
    model=DeepSeek(id="deepseek-chat"),
    instructions=[
        "You must only respond in Chinese",
    ],
)
spanish_agent = Agent(
    name="Spanish Agent",
    role="You can only answer in Spanish",
    model=OpenAIChat(id="gpt-4.5-preview"),
    instructions=[
        "You must only respond in Spanish",
    ],
)

french_agent = Agent(
    name="French Agent",
    role="You can only answer in French",
    model=MistralChat(id="mistral-large-latest"),
    instructions=[
        "You must only respond in French",
    ],
)

german_agent = Agent(
    name="German Agent",
    role="You can only answer in German",
    model=Claude("claude-3-5-sonnet-20241022"),
    instructions=[
        "You must only respond in German",
    ],
)
multi_language_team = Team(
    name="Multi Language Team",
    mode="route",
    model=OpenAIChat("gpt-4.5-preview"),
    members=[
        english_agent,
        spanish_agent,
        japanese_agent,
        french_agent,
        german_agent,
        chinese_agent,
    ],
    show_tool_calls=True,
    markdown=True,
    instructions=[
        "You are a language router that directs questions to the appropriate language agent.",
        "If the user asks in a language whose agent is not a team member, respond in English with:",
        "'I can only answer in the following languages: English, Spanish, Japanese, French and German. Please ask your question in one of these languages.'",
        "Always check the language of the user's input before routing to an agent.",
        "For unsupported languages like Italian, respond in English with the above message.",
    ],
    show_members_responses=True,
    debug_mode=True,
)


# Ask "How are you?" in all supported languages
# multi_language_team.print_response(
#     "How are you?", stream=True  # English
# )

# multi_language_team.print_response(
#     "你好吗？", stream=True  # Chinese
# )

# multi_language_team.print_response(
#     "お元気ですか?", stream=True  # Japanese
# )

multi_language_team.print_response(
    "Comment allez-vous?",
    stream=True,  # French
)

# multi_language_team.print_response(
#     "Wie geht es Ihnen?", stream=True  # German
# )


# multi_language_team.print_response(
#     "Come stai?", stream=True  # Italian
# )
