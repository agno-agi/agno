from agno.agent.agent import Agent
from agno.app.copilotkit.app import CopilotKitApp
from agno.models.openai.chat import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools


class WebSearchAgent(Agent):
    """Agent that answers queries by searching the web via DuckDuckGo."""

    def __init__(self):
        super().__init__(
            model=OpenAIChat(id="gpt-4o"),
            description="You are a helpful assistant that can search the web and cite the latest information.",
            instructions=(
                "When the user asks for information that may require up-to-date data, "
                "use the search tool to retrieve results, then summarize them for the user. "
                "Always think step-by-step: (1) decide if search is needed, (2) call the tool with an appropriate query, "
                "(3) read the JSON response, (4) craft a concise answer citing the sources if relevant."
            ),
            tools=[DuckDuckGoTools(search=True, news=True, fixed_max_results=5)],
            show_tool_calls=True,
            stream=True,
            debug_mode=True,
        )


# Expose the agent under the "/search" prefix so the Dojo frontend can POST /search/run
app = CopilotKitApp(agent=WebSearchAgent()).get_app(use_async=False, prefix="/search")
