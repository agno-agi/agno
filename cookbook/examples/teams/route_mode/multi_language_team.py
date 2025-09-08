from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.deepseek import DeepSeek
from agno.models.mistral import MistralChat
from agno.models.openai import OpenAIChat
from agno.team.team import Team

japanese_agent = Agent(
    name="Japanese Agent",
    role="You only answer in Japanese",
    model=DeepSeek(id="deepseek-chat"),
)
chinese_agent = Agent(
    name="Chinese Agent",
    role="You only answer in Chinese",
    model=DeepSeek(id="deepseek-chat"),
)
spanish_agent = Agent(
    name="Spanish Agent",
    role="You only answer in Spanish",
    model=OpenAIChat(id="gpt-4o"),
)
french_agent = Agent(
    name="French Agent",
    role="You only answer in French",
    model=MistralChat(id="mistral-large-latest"),
)
german_agent = Agent(
    name="German Agent",
    role="You only answer in German",
    model=Claude("claude-3-5-sonnet-20241022"),
)

multi_language_team = Team(
    name="Multi Language Team",
    respond_directly=True,
    determine_input_for_members=False,
    model=OpenAIChat("gpt-4o"),
    members=[
        spanish_agent,
        japanese_agent,
        french_agent,
        german_agent,
        chinese_agent,
    ],
    description="You are a language router that directs questions to the appropriate language agent.",
    instructions=[
        "Identify the language of the user's question and direct it to the appropriate language agent.",
        "Let the language agent answer the question in the language of the user's question.",
        "The the user asks a question in English, respond directly in English with:",
        "If the user asks in a language that is not English or your don't have a member agent for that language, respond in English with:",
        "'I only answer in the following languages: English, Spanish, Japanese, Chinese, French and German. Please ask your question in one of these languages.'",
        "Always check the language of the user's input before routing to an agent.",
        "For unsupported languages like Italian, respond in English with the above message.",
    ],
    markdown=True,
    show_members_responses=True,
)

if __name__ == "__main__":
    # Ask "How are you?" in all supported languages
    multi_language_team.print_response("Comment allez-vous?", stream=True)  # French
    multi_language_team.print_response("How are you?", stream=True)  # English
    multi_language_team.print_response("你好吗？", stream=True)  # Chinese
    multi_language_team.print_response("お元気ですか?", stream=True)  # Japanese
    multi_language_team.print_response("Wie geht es Ihnen?", stream=True)  # German
    multi_language_team.print_response("Hola, ¿cómo estás?", stream=True)  # Spanish
    multi_language_team.print_response("Come stai?", stream=True)  # Italian
