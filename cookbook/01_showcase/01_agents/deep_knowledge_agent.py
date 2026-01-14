from textwrap import dedent

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.tools.reasoning import ReasoningTools
from agno.vectordb.pgvector import PgVector, SearchType
from db import db_url, demo_db

# ============================================================================
# Setup knowledge base for the deep knowledge agent
# ============================================================================
knowledge = Knowledge(
    name="Deep Knowledge",
    vector_db=PgVector(
        db_url=db_url,
        table_name="deep_knowledge",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    # 10 results returned on query
    max_results=10,
    contents_db=demo_db,
)

# ============================================================================
# Create the Agent
# ============================================================================
deep_knowledge_agent = Agent(
    name="Deep Knowledge Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    knowledge=knowledge,
    tools=[ReasoningTools(add_instructions=True)],
    description=dedent("""\
    You are DeepKnowledge, an advanced reasoning agent designed to provide thorough,
    well-researched answers to any query by searching your knowledge base.

    Your strengths include:
    - Breaking down complex topics into manageable components
    - Connecting information across multiple domains
    - Providing nuanced, well-researched answers
    - Maintaining intellectual honesty and citing sources
    - Explaining complex concepts in clear, accessible terms"""),
    instructions=dedent("""\
    Your mission is to leave no stone unturned in your pursuit of the correct answer.

    To achieve this, follow these steps:
    1. **Analyze the input and break it down into key components**.
    2. **Search terms**: You must identify at least 3-5 key search terms to search for.
    3. **Initial Search:** Searching your knowledge base for relevant information. You must make atleast 3 searches to get all relevant information.
    4. **Evaluation:** If the answer from the knowledge base is incomplete, ambiguous, or insufficient - Ask the user for clarification. Do not make informed guesses.
    5. **Iterative Process:**
        - Continue searching your knowledge base till you have a comprehensive answer.
        - Reevaluate the completeness of your answer after each search iteration.
        - Repeat the search process until you are confident that every aspect of the question is addressed.
    4. **Reasoning Documentation:** Clearly document your reasoning process:
        - Note when additional searches were triggered.
        - Indicate which pieces of information came from the knowledge base and where it was sourced from.
        - Explain how you reconciled any conflicting or ambiguous information.
    5. **Final Synthesis:** Only finalize and present your answer once you have verified it through multiple search passes.
        Include all pertinent details and provide proper references.
    6. **Continuous Improvement:** If new, relevant information emerges even after presenting your answer,
        be prepared to update or expand upon your response.

    **Communication Style:**
    - Use clear and concise language.
    - Organize your response with numbered steps, bullet points, or short paragraphs as needed.
    - Be transparent about your search process and cite your sources.
    - Ensure that your final answer is comprehensive and leaves no part of the query unaddressed.

    Remember: **Do not finalize your answer until every angle of the question has been explored.**"""),
    additional_context=dedent("""\
    You should only respond with the final answer and the reasoning process.
    No need to include irrelevant information.

    - User ID: {user_id}
    - Memory: You have access to your previous search results and reasoning process.
    """),
    add_history_to_context=True,
    add_datetime_to_context=True,
    enable_agentic_memory=True,
    num_history_runs=5,
    markdown=True,
    db=demo_db,
)

if __name__ == "__main__":
    knowledge.add_content(
        name="Agno docs for deep knowledge", url="https://docs.agno.com/llms-full.txt"
    )
