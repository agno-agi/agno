"""Wikipedia Research Agent - AI assistant that researches topics using Wikipedia

This example demonstrates how to create an AI research assistant that leverages
Wikipedia to gather comprehensive information on any topic. The agent uses multiple
Wikipedia tools to search, retrieve detailed pages, get summaries, and find related topics.

Run `pip install openai wikipedia agno` to install dependencies.
"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.wikipedia import WikipediaTools

# Create a Research Agent with Wikipedia tools
research_agent = Agent(
    name="Wikipedia Research Assistant",
    model=OpenAIChat(id="gpt-4.1-mini"),
    tools=[WikipediaTools(all=True)],
    instructions=dedent("""\
        You are a knowledgeable research assistant specializing in gathering 
        and presenting information from Wikipedia. 📚

        Your research process:
        1. Start by searching Wikipedia for the topic to find relevant articles
        2. Retrieve detailed information from the most relevant pages
        3. Synthesize information into a clear, well-organized response
        4. Include key facts, context, and interesting details
        5. Cite sources by mentioning the Wikipedia article titles
        6. Suggest related topics for further exploration

        Presentation style:
        - Use clear headings and bullet points for readability
        - Start with a concise summary (2-3 sentences)
        - Organize information logically by subtopics
        - Include relevant facts, dates, and key figures
        - End with "Related Topics" section for further research
        
        Always maintain accuracy and cite your Wikipedia sources!\
    """),
    markdown=True,
    debug_mode=True,
)

# Example 1: Basic research query
print("=" * 80)
print("Example 1: Researching Artificial Intelligence")
print("=" * 80)
response = research_agent.run(
    "Research the history and key concepts of Artificial Intelligence"
)
print(response.content)

print("\n\n" + "=" * 80)
print("Example 2: Multi-topic comparison")
print("=" * 80)
response = research_agent.run(
    "Compare Python and Java programming languages, highlighting their key differences"
)
print(response.content)

print("\n\n" + "=" * 80)
print("Example 3: Deep dive with sections")
print("=" * 80)
response = research_agent.run(
    "Give me a detailed overview of Quantum Computing, including its main sections and related topics"
)
print(response.content)

# More example prompts to try:
"""
1. "What are the main theories about the origin of the universe?"
2. "Explain the Renaissance period and its impact on art and science"
3. "Research the Mars exploration missions and their discoveries"
4. "Compare different types of machine learning algorithms"
5. "What is the history of the Internet and key milestones?"
"""
