"""
Agno Agent - Zep Memory Integration

To get started, please export your Zep API and OpenAI API keys as environment variables:

export ZEP_API_KEY=<your-zep-api-key>
export OPENAI_API_KEY=<your-openai-api-key>

You can get your Zep API key from https://app.getzep.com/
You can get your OpenAI API key from https://platform.openai.com/api-keys
"""

import asyncio
import time
import uuid
import click
from typing import Any, Dict, List, Optional

from zep_cloud import NotFoundError
from zep_cloud.client import AsyncZep
from zep_cloud.types import Message as ZepMessage

from agno.agent import Agent, Message
from agno.models.openai import OpenAIChat

# Example tool
async def get_weather(city: str) -> str:
    """Get the current weather in a given city."""
    # This is a mock function - in a real application, you would call a weather API
    return f"The weather in {city} is sunny and 72 degrees Fahrenheit."


# Initialize the AsyncZep client
class AsyncZepMemoryManager:
    """
    A class to manage memory using AsyncZep
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        email: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        ignore_assistant: bool = False,
    ):
        """
        Initialize the AsyncZepMemoryManager.

        Args:
            session_id: Optional session ID. If not provided, a new one will be generated.
            user_id: Optional user ID. If not provided, a new one will be generated.
            email: Optional email address for the user.
            first_name: Optional first name for the user.
            last_name: Optional last name for the user.
        """
        self.session_id = session_id or str(uuid.uuid4())
        self.user_id = user_id or f"user-{str(uuid.uuid4())[:8]}"
        self.email = email
        self.first_name = first_name
        self.last_name = last_name
        self.ignore_assistant = ignore_assistant
        self.zep_client: AsyncZep | None = None

    async def initialize(self):
        """
        Initialize the AsyncZep client, create or get the user, and create a new memory session.
        """

        self.zep_client = AsyncZep()

        # Create or get the user
        try:
            # Try to get the user first
            await self.zep_client.user.get(self.user_id)
            print(f"Using existing user: {self.user_id}")

        except NotFoundError:
            await self.zep_client.user.add(
                user_id=self.user_id,
                first_name=self.first_name,
                last_name=self.last_name,
                email=self.email,
            )
            print(f"Created new user with ID: {self.user_id}")

        # Generate a timestamp-based session ID for a new session each time
        timestamp = int(time.time())
        self.session_id = f"{self.session_id}-{timestamp}"
        print(f"Creating new session with ID: {self.session_id}")

        # Always create a new memory session with the user ID
        await self.zep_client.memory.add_session(
            session_id=self.session_id,
            user_id=self.user_id,
        )

    async def add_message(self, message: Message) -> None:
        """
        Add a message to Zep memory.

        Args:
            message: The message to add to memory.
        """
        # Convert message to Zep message
        role = message.get("role", None)

        zep_message_role = ""
        if role == "user" and self.first_name:
            zep_message_role = self.first_name
            if self.last_name:
                zep_message_role += " " + self.last_name

        zep_message = ZepMessage(
            role=zep_message_role
            if zep_message_role
            else "assistant",  # role in Zep is the name of the user
            role_type=role,  # Use the role directly
            content=message.get("content", ""),
        )

        # Add message to Zep memory using AsyncZep client
        if not self.zep_client:
            raise ValueError("Zep client not initialized")

        await self.zep_client.memory.add(
            session_id=self.session_id,
            messages=[zep_message],
            ignore_roles=["assistant"] if self.ignore_assistant else None,
        )

    async def get_memory(self) -> str:
        """
        Get the memory context string from Zep memory instead of creating a summary.

        Returns:
            A string containing the memory context from Zep.
        """
        try:
            if not self.zep_client:
                raise ValueError("Zep client not initialized")

            # Use memory.get to retrieve memory context for the session
            memory = await self.zep_client.memory.get(session_id=self.session_id)

            # Use the context string provided by Zep instead of creating a summary
            if memory.context:
                return memory.context

            return "No conversation history yet."
        except NotFoundError:
            print("Session not found.")
            raise
        except Exception as e:
            print(f"Error getting memory context: {e}")
            raise

    async def search_memory(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Search Zep memory for relevant facts based on a query.
        Node search is also supported by Zep but not implemented here.

        Args:
            query: The query to search for relevant facts.
            limit: Maximum number of facts to return.

        Returns:
            A list of relevant facts.
        """

        formatted_messages = []
        # First try to use graph.search to find relevant information
        try:
            # Check if zep_client is initialized
            if not self.zep_client:
                raise ValueError("Zep client not initialized")

            # Use the user_id property directly instead of getting it from the session
            if self.user_id:
                # Use graph.search to find relevant edges. Facts reside on graph edges
                search_response = await self.zep_client.graph.search(
                    query=query, user_id=self.user_id, scope="edges", limit=limit
                )

                if search_response and search_response.edges:
                    # Convert graph search results to the expected format
                    formatted_messages = [
                        {
                            "role": "assistant",  # These are facts, so mark them as from the assistant
                            "content": edge.fact,
                        }
                        for edge in search_response.edges[:limit]
                    ]
                    print(
                        f"Memory search found {len(formatted_messages)} relevant facts from graph search"
                    )
                    return formatted_messages
        except NotFoundError:
            print("User not found.")
            raise
        except Exception as search_error:
            print(f"Graph search error: {search_error}")
            raise

        return formatted_messages


class AsyncZepMemoryAgent:
    """
    An agent that uses AsyncZep for memory
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        email: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        ignore_assistant: bool = False,
    ):
        """
        Initialize the AsyncZepMemoryAgent.

        Args:
            session_id: Optional session ID. If not provided, a new one will be generated.
            user_id: Optional user ID. If not provided, a new one will be generated.
            email: Optional email address for the user.
            first_name: Optional first name for the user.
            last_name: Optional last name for the user.
            ignore_assistant: Optional flag to indicate whether to persist the assistant's response to the user graph.
        """
        self.memory_manager = AsyncZepMemoryManager(
            session_id, user_id, email, first_name, last_name, ignore_assistant
        )
        self.agent = None

    async def initialize(self):
        """
        Initialize the AsyncZep memory manager and create agent with tools.
        """
        # Initialize the AsyncZep memory manager
        await self.memory_manager.initialize()

        async def search_memory(query: str) -> str:
            """Search for relevant information facts about the user."""
            results = await self.memory_manager.search_memory(query)
            if not results:
                return "I couldn't find any relevant facts about the user."

            formatted_results = "\n".join(
                [f"- {result['role']}: {result['content']}" for result in results]
            )

            return f"Facts about the user:\n{formatted_results}"

        # Get memory context to include in the system message
        memory_context = await self.memory_manager.get_memory()

        # Create the agent with memory tools and context-enhanced system message
        self.agent = Agent(
            name="Memory Assistant with AsyncZep",
            model=OpenAIChat(id="gpt-4o-mini"),
            instructions=(
                "You are a helpful Agent with memory capabilities. Use the memory search tool to recall important information about the user."
                + "\n"
                + f"Memory Context: {memory_context}"
            ),
            tools=[
                get_weather,
                search_memory,
            ],
        )

    async def chat(self, user_input: str) -> str:
        """
        Chat with the agent and store the conversation in Zep memory.

        Args:
            user_input: The user's input message.

        Returns:
            The agent's response.
        """
        # Check if agent and memory manager are initialized
        if not self.agent:
            return "Error: Agent not initialized. Please check your API key."

        if not self.memory_manager.zep_client:
            return "Error: AsyncZep client not initialized. Please set the ZEP_API_KEY environment variable."

        # Store the user message in Zep memory
        await self.memory_manager.add_message({"role": "user", "content": user_input})

        # Update the agent's instructions with the latest memory context
        memory_context = await self.memory_manager.get_memory()
        self.agent.instructions = (
            "You are a helpful Agent with memory capabilities. Use the memory search tool to recall important information about the user."
            + "\n"
            + f"Memory Context: {memory_context}"
        )

        # Run the agent with the user input directly
        result = await self.agent.arun(user_input)

        # Extract the agent's response
        agent_response = result.content

        # Store the agent's response in Zep memory
        await self.memory_manager.add_message(
            {"role": "assistant", "content": agent_response}
        )

        return agent_response


async def run_agent(
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    email: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    ignore_assistant: bool = False,
):
    """
    Run the AsyncZepMemoryAgent with the specified parameters.

    Args:
        session_id: Optional session ID. If not provided, a new one will be generated.
        user_id: Optional user ID. If not provided, a new one will be generated.
        email: Optional email address for the user.
        first_name: Optional first name for the user.
        last_name: Optional last name for the user.
    """
    print("\nInitializing AsyncZep Memory Agent with Agents SDK...")

    # Create a memory agent with the provided parameters
    if not session_id:
        session_id = f"demo-session-{int(time.time())}"

    memory_agent = AsyncZepMemoryAgent(
        session_id, user_id, email, first_name, last_name, ignore_assistant
    )

    # Initialize the agent (sets up AsyncZep client and Agents SDK)
    await memory_agent.initialize()

    # Check if initialization was successful
    if (
        not memory_agent.agent
        or not memory_agent.memory_manager
        or not memory_agent.memory_manager.zep_client
    ):
        print(
            "\nError: Failed to initialize the required components. Please set the ZEP_API_KEY environment variable."
        )
        return

    # Chat with the agent
    responses = []

    # First interaction
    print("Processing first interaction...")
    input1 = "Hi, my name is Alice and I live in New York."
    response1 = await memory_agent.chat(input1)
    print(f"User: {input1}\nAgent: {response1}\n")
    responses.append((input1, response1))

    # sleep for 10 seconds
    print("Sleeping for 10 seconds... to let Zep do its thing")
    await asyncio.sleep(10)

    # Second interaction
    print("Processing second interaction...")
    input2 = "What's the weather like in my city?"
    response2 = await memory_agent.chat(input2)
    print(f"User: {input2}\nAgent: {response2}\n")
    responses.append((input2, response2))

    # Third interaction - testing memory
    print("Processing third interaction...")
    input3 = "Can you remind me what my name is?"
    response3 = await memory_agent.chat(input3)
    print(f"User: {input3}\nAgent: {response3}\n")
    responses.append((input3, response3))

    # sleep for 10 seconds
    print("Sleeping for 10 seconds... to let Zep do its thing")
    await asyncio.sleep(10)

    # Fourth interaction - testing memory search
    print("Processing fourth interaction...")
    input4 = "What do you know about where I live?"
    response4 = await memory_agent.chat(input4)
    print(f"User: {input4}\nAgent: {response4}\n")
    responses.append((input4, response4))

    # Print the conversation
    print("\n=== Conversation with Memory Agent ===\n")
    for user_msg, agent_msg in responses:
        print(f"{user_msg}\n{agent_msg}\n")

    # Get memory context from Zep
    memory_context = await memory_agent.memory_manager.get_memory()
    print(f"\n=== Memory Context ===\n{memory_context}")


async def run_interactive_agent(
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    email: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    ignore_assistant: bool = False,
):
    """
    Run the AsyncZepMemoryAgent in interactive mode for continuous conversation.

    Args:
        session_id: Optional session ID. If not provided, a new one will be generated.
        user_id: Optional user ID. If not provided, a new one will be generated.
        email: Optional email address for the user.
        first_name: Optional first name for the user.
        last_name: Optional last name for the user.
        ignore_assistant: Optional flag to indicate whether to persist the assistant's response to the user graph.
    """
    print("\nInitializing AsyncZep Memory Agent with Agents SDK (Interactive Mode)...")

    # Create a memory agent with the provided parameters
    if not session_id:
        session_id = f"interactive-session-{int(time.time())}"

    memory_agent = AsyncZepMemoryAgent(
        session_id, user_id, email, first_name, last_name, ignore_assistant
    )

    # Initialize the agent
    await memory_agent.initialize()

    print("\n=== Interactive Mode ===")
    print("Type 'exit', 'quit', or 'bye' to end the conversation.")
    print("Type 'memory' to see the current memory context.")
    print("=== Start Conversation ===\n")

    while True:
        # Get user input
        user_input = input("You: ")

        # Check for exit commands
        if user_input.lower() in ["exit", "quit", "bye"]:
            print("\nExiting interactive mode. Goodbye!")
            break

        # Check for memory command
        if user_input.lower() == "memory":
            memory_context = await memory_agent.memory_manager.get_memory()
            print(f"\n=== Memory Context ===\n{memory_context}\n")
            continue

        # Process the user input and get the agent's response
        agent_response = await memory_agent.chat(user_input)
        print(f"Agent: {agent_response}\n")


@click.command()
@click.option("--username", help="Username for the Zep user")
@click.option("--email", help="Email address for the Zep user")
@click.option("--firstname", help="First name for the Zep user")
@click.option("--lastname", help="Last name for the Zep user")
@click.option("--session", help="Session ID for the conversation")
@click.option(
    "--interactive",
    is_flag=True,
    help="Run in interactive mode for continuous conversation",
)
@click.option(
    "--ignore-assistant",
    is_flag=True,
    help="Don't persist the assistant's response to the user graph",
)
def main(
    username: Optional[str] = None,
    email: Optional[str] = None,
    firstname: Optional[str] = None,
    lastname: Optional[str] = None,
    session: Optional[str] = None,
    interactive: bool = False,
    ignore_assistant: bool = False,
):
    """
    Run the AsyncZepMemoryAgent with optional user information.
    """
    # Display the provided parameters
    if username:
        click.echo(f"Username: {username}")
    if email:
        click.echo(f"Email: {email}")
    if firstname:
        click.echo(f"First Name: {firstname}")
    if lastname:
        click.echo(f"Last Name: {lastname}")
    if session:
        click.echo(f"Session ID: {session}")
    if interactive:
        click.echo("Running in interactive mode")
    if ignore_assistant:
        click.echo("Not persisting assistant's response to user graph")

    if interactive:
        # Run the agent in interactive mode
        asyncio.run(
            run_interactive_agent(
                session,
                username,
                email,
                firstname,
                lastname,
                ignore_assistant=ignore_assistant,
            )
        )
    else:
        # Run the agent in demo mode
        asyncio.run(
            run_agent(
                session,
                username,
                email,
                firstname,
                lastname,
                ignore_assistant=ignore_assistant,
            )
        )


if __name__ == "__main__":
    main()
