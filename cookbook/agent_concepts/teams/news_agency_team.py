"""
1. Run: `pip install openai duckduckgo-search newspaper4k lxml_html_clean agno` to install the dependencies
2. Run: `python cookbook/teams/02_news_reporter.py` to run the agent
"""

from pathlib import Path

from agno.agent import Agent
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.file import FileTools
from agno.tools.newspaper4k import Newspaper4kTools

urls_file = Path(__file__).parent.joinpath("tmp", "urls__{session_id}.md")
urls_file.parent.mkdir(parents=True, exist_ok=True)


searcher = Agent(
    name="Searcher",
    role="Searches the top URLs for a topic",
    instructions=[
        "Given a topic, first generate a list of 3 search terms related to that topic.",
        "For each search term, search the web and analyze the results.Return the 10 most relevant URLs to the topic.",
        "You are writing for the New York Times, so the quality of the sources is important.",
    ],
    tools=[DuckDuckGoTools()],
    save_response_to_file=str(urls_file),
    add_datetime_to_instructions=True,
)
writer = Agent(
    name="Writer",
    role="Writes a high-quality article",
    description=(
        "You are a senior writer for the New York Times. Given a topic and a list of URLs, "
        "your goal is to write a high-quality NYT-worthy article on the topic."
    ),
    instructions=[
        f"First read all urls in {urls_file.name} using `get_article_text`."
        "Then write a high-quality NYT-worthy article on the topic."
        "The article should be well-structured, informative, engaging and catchy.",
        "Ensure the length is at least as long as a NYT cover story -- at a minimum, 15 paragraphs.",
        "Ensure you provide a nuanced and balanced opinion, quoting facts where possible.",
        "Focus on clarity, coherence, and overall quality.",
        "Never make up facts or plagiarize. Always provide proper attribution.",
        "Remember: you are writing for the New York Times, so the quality of the article is important.",
    ],
    tools=[Newspaper4kTools(), FileTools(base_dir=urls_file.parent)],
    add_datetime_to_instructions=True,
)

editor = Agent(
    name="Editor",
    team=[searcher, writer],
    description="You are a senior NYT editor. Given a topic, your goal is to write a NYT worthy article.",
    instructions=[
        "First ask the search journalist to search for the most relevant URLs for that topic.",
        "Then ask the writer to get an engaging draft of the article.",
        "Edit, proofread, and refine the article to ensure it meets the high standards of the New York Times.",
        "The article should be extremely articulate and well written. "
        "Focus on clarity, coherence, and overall quality.",
        "Remember: you are the final gatekeeper before the article is published, so make sure the article is perfect.",
    ],
    add_datetime_to_instructions=True,
    markdown=True,
    debug_mode=True,
)
editor.print_response("Write an article about latest developments in AI.")
