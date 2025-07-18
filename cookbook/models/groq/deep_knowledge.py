"""🤔 DeepKnowledge - An AI Agent that iteratively searches a knowledge base to answer questions

This agent performs iterative searches through its knowledge base, breaking down complex
queries into sub-questions, and synthesizing comprehensive answers. It's designed to explore
topics deeply and thoroughly by following chains of reasoning.

In this example, the agent uses the Agno documentation as a knowledge base

Key Features:
- Iteratively searches a knowledge base
- Source attribution and citations

Run `pip install openai lancedb tantivy inquirer agno groq` to install dependencies.
"""

from textwrap import dedent
from typing import List, Optional

import inquirer
import typer
from agno.agent import Agent
from agno.embedder.openai import OpenAIEmbedder
from agno.knowledge.url import UrlKnowledge
from agno.models.groq import Groq
from agno.storage.sqlite import SqliteStorage
from agno.vectordb.lancedb import LanceDb, SearchType
from rich import print


def initialize_knowledge_base():
    """Initialize the knowledge base with your preferred documentation or knowledge source
    Here we use Agno docs as an example, but you can replace with any relevant URLs
    """
    agent_knowledge = UrlKnowledge(
        urls=["https://docs.agno.com/llms-full.txt"],
        vector_db=LanceDb(
            uri="tmp/lancedb",
            table_name="deep_knowledge_knowledge",
            search_type=SearchType.hybrid,
            embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        ),
    )
    # Load the knowledge base (comment out after first run)
    agent_knowledge.load()
    return agent_knowledge


def get_agent_storage():
    """Return agent storage"""
    return SqliteStorage(table_name="deep_knowledge_sessions", db_file="tmp/agents.db")


def create_agent(session_id: Optional[str] = None) -> Agent:
    """Create and return a configured DeepKnowledge agent."""
    agent_knowledge = initialize_knowledge_base()
    agent_storage = get_agent_storage()
    return Agent(
        name="DeepKnowledge",
        session_id=session_id,
        model=Groq(id="llama-3.3-70b-versatile"),
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
        knowledge=agent_knowledge,
        storage=agent_storage,
        add_history_to_messages=True,
        num_history_responses=3,
        show_tool_calls=True,
        read_chat_history=True,
        markdown=True,
    )


def get_example_topics() -> List[str]:
    """Return a list of example topics for the agent."""
    return [
        "What are AI agents and how do they work in Agno?",
        "What chunking strategies does Agno support for text processing?",
        "How can I implement custom tools in Agno?",
        "How does knowledge retrieval work in Agno?",
        "What types of embeddings does Agno support?",
    ]


def handle_session_selection() -> Optional[str]:
    """Handle session selection and return the selected session ID."""
    agent_storage = get_agent_storage()

    new = typer.confirm("Do you want to start a new session?", default=True)
    if new:
        return None

    existing_sessions: List[str] = agent_storage.get_all_session_ids()
    if not existing_sessions:
        print("No existing sessions found. Starting a new session.")
        return None

    print("\nExisting sessions:")
    for i, session in enumerate(existing_sessions, 1):
        print(f"{i}. {session}")

    session_idx = typer.prompt(
        "Choose a session number to continue (or press Enter for most recent)",
        default=1,
    )

    try:
        return existing_sessions[int(session_idx) - 1]
    except (ValueError, IndexError):
        return existing_sessions[0]


def run_interactive_loop(agent: Agent):
    """Run the interactive question-answering loop."""
    example_topics = get_example_topics()

    while True:
        choices = [f"{i + 1}. {topic}" for i, topic in enumerate(example_topics)]
        choices.extend(["Enter custom question...", "Exit"])

        questions = [
            inquirer.List(
                "topic",
                message="Select a topic or ask a different question:",
                choices=choices,
            )
        ]
        answer = inquirer.prompt(questions)

        if answer["topic"] == "Exit":
            break

        if answer["topic"] == "Enter custom question...":
            questions = [inquirer.Text("custom", message="Enter your question:")]
            custom_answer = inquirer.prompt(questions)
            topic = custom_answer["custom"]
        else:
            topic = example_topics[int(answer["topic"].split(".")[0]) - 1]

        agent.print_response(topic, stream=True)


def deep_knowledge_agent():
    """Main function to run the DeepKnowledge agent."""

    session_id = handle_session_selection()
    agent = create_agent(session_id)

    print("\n🤔 Welcome to DeepKnowledge - Your Advanced Research Assistant! 📚")
    if session_id is None:
        session_id = agent.session_id
        if session_id is not None:
            print(f"[bold green]Started New Session: {session_id}[/bold green]\n")
        else:
            print("[bold green]Started New Session[/bold green]\n")
    else:
        print(f"[bold blue]Continuing Previous Session: {session_id}[/bold blue]\n")

    run_interactive_loop(agent)


if __name__ == "__main__":
    typer.run(deep_knowledge_agent)

# Example prompts to try:
"""
Explore Agno's capabilities with these queries:
1. "What are the different types of agents in Agno?"
2. "How does Agno handle knowledge base management?"
3. "What embedding models does Agno support?"
4. "How can I implement custom tools in Agno?"
5. "What storage options are available for workflow caching?"
6. "How does Agno handle streaming responses?"
7. "What types of LLM providers does Agno support?"
8. "How can I implement custom knowledge sources?"
"""
