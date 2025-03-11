"""🤖 Agno Support Agent - Your AI Assistant for Agno Framework!

This example shows how to create an AI support assistant that combines iterative knowledge searching
with Agno's documentation to provide comprehensive, well-researched answers about the Agno framework.

Key Features:
- Iterative knowledge base searching
- Deep reasoning and comprehensive answers
- Source attribution and citations
- Interactive session management

Example prompts to try:
- "What is Agno and what are its key features?"
- "How do I create my first agent with Agno?"
- "What's the difference between Level 0 and Level 1 agents?"
- "How can I add memory to my Agno agent?"
- "What models does Agno support?"
- "How do I implement RAG with Agno?"

Run `pip install openai lancedb tantivy pypdf duckduckgo-search inquirer agno` to install dependencies.
"""

from pathlib import Path
from textwrap import dedent
from typing import List, Optional

import inquirer
import typer
from agno.agent import Agent
from agno.embedder.openai import OpenAIEmbedder
from agno.knowledge.url import UrlKnowledge
from agno.models.openai import OpenAIChat
from agno.storage.agent.sqlite import SqliteAgentStorage
from agno.tools.python import PythonTools
from agno.vectordb.lancedb import LanceDb, SearchType
from rich import print
from rich.console import Console
from rich.table import Table

# ************* Setup Paths *************
# Define the current working directory and output directory for saving files
cwd = Path(__file__).parent
# Create tmp directory if it doesn't exist
tmp_dir = cwd.joinpath("tmp")
tmp_dir.mkdir(parents=True, exist_ok=True)
# *************************************


def initialize_knowledge_base(load_knowledge: bool = False):
    """Initialize the knowledge base with Agno documentation

    Args:
        load_knowledge (bool): Whether to load the knowledge base. Defaults to False.
    """
    agent_knowledge = UrlKnowledge(
        urls=["https://docs.agno.com/llms-full.txt"],
        vector_db=LanceDb(
            uri="tmp/lancedb",
            table_name="agno_assist_knowledge",
            search_type=SearchType.hybrid,
            embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        ),
    )
    # Load the knowledge base
    if load_knowledge:
        print("[bold blue]📚 Initializing knowledge base...[/bold blue]")
        print("   • Loading Agno documentation")
        print("   • Building vector embeddings")
        print("   • Optimizing for hybrid search")
        agent_knowledge.load()
        print("[bold green]✨ Knowledge base ready![/bold green]\n")
    return agent_knowledge


def get_agent_storage():
    """Return agent storage for session management"""
    return SqliteAgentStorage(
        table_name="agno_assist_sessions", db_file="tmp/agents.db"
    )


def create_agent(
    session_id: Optional[str] = None, load_knowledge: bool = False
) -> Agent:
    """Create and return a configured Agno Support agent."""
    agent_knowledge = initialize_knowledge_base(load_knowledge)
    agent_storage = get_agent_storage()

    return Agent(
        name="AgnoAssist",
        session_id=session_id,
        model=OpenAIChat(id="gpt-4o"),
        description=dedent("""\
        You are AgnoAssist, an advanced AI Agent specialized in the Agno framework.
        Your goal is to help developers understand and effectively use Agno by providing
        both explanations and working code examples. You can create, save, and run Python
        code to demonstrate Agno's capabilities in real-time.

        Your strengths include:
        - Deep understanding of Agno's architecture and capabilities
        - Access to Agno documentation and API reference, search it for relevant information
        - Creating and testing working Agno Agents
        - Building practical, runnable code examples that demonstrate concepts
        - Ability to save code to files and execute them to verify functionality\
        """),
        instructions=dedent("""\
        Your mission is to provide comprehensive, hands-on support for Agno developers
        through iterative knowledge searching, clear explanations, and working code examples.

        Follow these steps for every query:
        1. **Analysis**
            - Break down the question into key technical components
            - Identify if the query requires a knowledge search, creating an Agent or both
            - If you need to search the knowledge base, identify 1-3 key search terms related to Agno concepts
            - If you need to create an Agent, search the knowledge base for relevant concepts and use the example code as a guide
            - When the user asks for an Agent, they mean an Agno Agent.
            - All concepts are related to Agno, so you can search the knowledge base for relevant information

        After Analysis, always start the iterative search process. No need to wait for approval from the user.

        2. **Iterative Search Process**
            - Make at least 3 searches in the knowledge base using the `search_knowledge_base` tool
            - Search for related concepts and implementation details
            - Continue searching until you have found all the information you need or you have exhausted all the search terms

        After the iterative search process, determine if you need to create an Agent.
        If you do, ask the user if they want you to create the Agent and run it.

        3. **Code Creation and Execution**
            - Create complete, working code examples that users can run. For example:
            ```python
            from agno.agent import Agent
            from agno.tools.duckduckgo import DuckDuckGoTools

            agent = Agent(tools=[DuckDuckGoTools()])

            # Perform a web search and capture the response
            response = agent.run("What's happening in France?")
            ```
            - You must remember to use agent.run() and NOT agent.print_response()
            - This way you can capture the response and return it to the user
            - Use the `save_to_file_and_run` tool to save it to a file and run.
            - Make sure to return the `response` variable that tells you the result
            - Remember to:
              * Build the complete agent implementation
              * Include all necessary imports and setup
              * Add comprehensive comments explaining the implementation
              * Test the agent with example queries
              * Ensure all dependencies are listed
              * Include error handling and best practices
              * Add type hints and documentation

        4. **Response Structure**
            - Start with a relevant emoji (🤖 general, 📚 concepts, 💻 code, 🔧 troubleshooting)
            - Give a brief overview
            - Provide detailed explanation with source citations
            - Show the code execution results when relevant
            - Share best practices and common pitfalls
            - Suggest related topics to explore

        5. **Quality Checks**
            - Verify technical accuracy against documentation
            - Test all code examples by running them
            - Check that all aspects of the question are addressed
            - Include relevant documentation links

        Key Agno Concepts to Emphasize:
        - Agent levels (0-3) and capabilities
        - Multimodal and streaming support
        - Model agnosticism and provider flexibility
        - Knowledge base and memory management
        - Tool integration and extensibility
        - Performance optimization techniques

        Code Example Guidelines:
        - Always provide complete, runnable examples
        - Include all necessary imports and setup
        - Add error handling and type hints
        - Follow PEP 8 style guidelines
        - Use descriptive variable names
        - Add comprehensive comments
        - Show example usage and expected output

        Remember:
        - Always verify code examples by running them
        - Be clear about source attribution
        - Support developers at all skill levels
        - Focus on Agno's core principles: Simplicity, Performance, and Agnosticism
        - Save code examples to files when they would be useful to run"""),
        knowledge=agent_knowledge,
        tools=[PythonTools(base_dir=tmp_dir.joinpath("agno_assist"), read_files=True)],
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
        "Tell me about Agno",
        "How do I create an agent with web search capabilities?",
        "How can I build an agent which can store session history?",
        "How do I create an Agent with knowledge?",
        "How can I make an agent that can write and execute code?",
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


def run_interactive_loop(agent: Agent, show_topics: bool = True):
    """Run the interactive question-answering loop.

    Args:
        agent: Agent instance to use for responses
        show_topics: Whether to show example topics or continue chat-like interaction
    """
    example_topics = get_example_topics()
    first_interaction = True

    while True:
        if show_topics and first_interaction:
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

            if answer is None or answer["topic"] == "Exit":
                break

            if answer["topic"] == "Enter custom question...":
                questions = [inquirer.Text("custom", message="Enter your question:")]
                custom_answer = inquirer.prompt(questions)
                topic = custom_answer["custom"]
            else:
                topic = example_topics[int(answer["topic"].split(".")[0]) - 1]
            first_interaction = False
        else:
            # Chat-like interaction
            question = typer.prompt("\n", prompt_suffix="> ")
            if question.lower() in ("exit", "quit", "bye"):
                break
            topic = question

        agent.print_response(topic, stream=True)


def agno_support_agent(
    load_knowledge: bool = typer.Option(
        False, "--load-knowledge", "-l", help="Load the knowledge base on startup"
    ),
):
    """Main function to run the Agno Support agent."""
    session_id = handle_session_selection()
    agent = create_agent(session_id, load_knowledge)

    # Create and display welcome table
    console = Console()
    table = Table(show_header=False, style="cyan")
    table.add_column(justify="center", min_width=40)
    table.add_row("🤖 Welcome to [bold green]AgnoAssist[/bold green]")
    table.add_row("Your Personal Agno Expert")
    console.print(table)

    if session_id is None:
        session_id = agent.session_id
        if session_id is not None:
            print(
                "[bold green]📝 Started New Session: [white]{}[/white][/bold green]\n".format(
                    session_id
                )
            )
        else:
            print("[bold green]📝 Started New Session[/bold green]\n")
        show_topics = True
    else:
        print(
            "[bold blue]🔄 Continuing Previous Session: [white]{}[/white][/bold blue]\n".format(
                session_id
            )
        )
        show_topics = False

    run_interactive_loop(agent, show_topics)


if __name__ == "__main__":
    typer.run(agno_support_agent)
