import asyncio
import time
import uuid
from typing import Optional

import click
from agno.agent import Agent, Message
from agno.models.openai import OpenAIChat
from agno.tools.zep import ZepTools

MODEL_NAME = "gpt-4o-mini"
SYSTEM_PROMPT_TEMPLATE = """

You are a helpful Agent with memory capabilities. Use the search_zep_memory tool to recall important information about the user or the conversation when asked directly or when context suggests it's needed.

Ask the user plenty of questions about their life so you can build up a profile of them. Some things to ask them:
- Where they live
- their favorite things
- their favorite activities
- what they like about the place they live

{memory_context_section}
"""


async def get_weather(city: str) -> str:
    """Get the current weather in a given city."""
    return f"The weather in {city} is sunny and 72 degrees Fahrenheit."


class AsyncZepMemoryAgent:
    """
    An agent that uses the Agno ZepTools for memory.
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        email: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        ignore_assistant: bool = False,
        zep_api_key: Optional[str] = None,
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
            zep_api_key: Zep API Key.
        """
        self.user_id = user_id or f"interactive-user-{uuid.uuid4()}"
        self.session_id = session_id or f"{self.user_id}-session-{uuid.uuid4()}"
        self.email = email
        self.first_name = first_name
        self.last_name = last_name

        self.zep_toolkit = ZepTools(
            session_id=self.session_id,
            user_id=self.user_id,
            api_key=zep_api_key,
            ignore_assistant_messages=ignore_assistant,
        )
        self.agent: Optional[Agent] = None
        self._initialized = False

    async def initialize(self) -> bool:
        """
        Initialize the agent: Call ZepTools initialize and create the Agno agent.

        Returns:
            True if initialization succeeds, False otherwise.
        """
        try:
            init_success = await self.zep_toolkit.initialize()
            if not init_success:
                print("ZepTools initialization failed.")
                return False  # Indicate agent initialization failure
            print("ZepTools initialized successfully.")
        except Exception as e:  # Catch any unexpected errors during Zep init
            print(f"ZepTools initialization failed: {e}")
            return False

        memory_context_section = "\\n\\n--- Conversation Context (from Zep) ---\\n(Context will be loaded during conversation)\\n------------------------------------"
        initial_instructions = SYSTEM_PROMPT_TEMPLATE.format(
            memory_context_section=memory_context_section
        )

        # Create the Agno Agent
        try:
            print("Attempting to create Agent instance...")
            self.agent = Agent(
                name="InteractiveZepAgent",
                model=OpenAIChat(id=MODEL_NAME),
                instructions=initial_instructions,
                tools=[get_weather, self.zep_toolkit],
            )
            self._initialized = True
            return True
        except Exception as e:
            print(f"Failed to create Agno Agent instance: {e}")
            self.agent = None
            self._initialized = False
            return False

    async def chat(self, user_input: str) -> str:
        """
        Chat with the agent, adding messages and updating context via ZepTools.

        Args:
            user_input: The user's input message.

        Returns:
            The agent's response.
        """
        if not self._initialized or not self.agent:
            print("Agent not initialized. Cannot chat.")
            return "Error: Agent not initialized."

        await self.zep_toolkit.add_zep_message(role="user", content=user_input)

        # Add a delay to allow Zep to process the message
        processing_delay = 15  # Increased delay
        await asyncio.sleep(processing_delay)

        current_memory_context = await self.zep_toolkit.get_zep_memory(
            memory_type="context"
        )

        # 3. Update agent instructions with the latest context
        memory_context_section = f"\n\n--- Conversation Context (from Zep) ---\n{current_memory_context}\n------------------------------------"
        updated_instructions = SYSTEM_PROMPT_TEMPLATE.format(
            memory_context_section=memory_context_section
        )
        self.agent.instructions = updated_instructions
        try:
            result: Message = await self.agent.arun(user_input)
            agent_response = result.content

        except Exception as e:
            agent_response = f"Sorry, an error occurred: {e}"

        # 5. Add agent response to Zep memory
        if agent_response and not agent_response.startswith("Error:"):
            await self.zep_toolkit.add_zep_message(
                role="assistant", content=agent_response
            )

        return agent_response


async def run_interactive_agent(
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    email: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    ignore_assistant: bool = False,
    zep_api_key: Optional[str] = None,
):
    """
    Run the AsyncZepMemoryAgent in interactive mode.
    """
    memory_agent = AsyncZepMemoryAgent(
        session_id=session_id,
        user_id=user_id,
        email=email,
        first_name=first_name,
        last_name=last_name,
        ignore_assistant=ignore_assistant,
        zep_api_key=zep_api_key,
    )

    # Initialize the agent
    initialized = await memory_agent.initialize()
    if not initialized:
        print("Agent initialization failed. Exiting.")
        return

    print(f"User ID: {memory_agent.user_id}")
    print(f"Session ID: {memory_agent.session_id}")

    print("\n=== Interactive Mode ===")
    print("Type 'exit', 'quit', or 'bye' to end the conversation.")
    print("Type 'memory' to see the current Zep context.")
    # Add command for specific fact search
    print("Type 'search <query>' to search Zep graph memory.")
    print("=== Start Conversation ===\n")

    while True:
        try:
            user_input = input("You: ")
        except EOFError:
            print("\nExiting (EOF detected).")
            break

        if user_input.lower() in ["exit", "quit", "bye"]:
            print("\nExiting interactive mode. Goodbye!")
            break

        if user_input.lower() == "memory":
            print("\nFetching memory context...")
            try:
                context = await memory_agent.zep_toolkit.get_zep_memory(
                    memory_type="context"
                )
                print("\n=== Memory Context ===")
                print(context if context else "No context available.")
                print("=" * 20 + "\n")
            except Exception as e:
                print(f"Error fetching memory: {e}")
            continue  # Skip agent interaction for this command

        # Handle specific memory search command
        if user_input.lower().startswith("search "):
            query = user_input[len("search ") :].strip()
            if not query:
                print(
                    "Please provide a query after 'search'. Example: search Where do I live?"
                )
                continue  # Skip if query is empty
            print(f"\nSearching Zep graph memory for: '{query}'")
            try:
                results = await memory_agent.zep_toolkit.search_zep_memory(query=query)
                print("\n=== Graph Search Results ===")
                if results:
                    for i, fact in enumerate(results):
                        print(
                            f"{i + 1}. {fact['content']}"
                        )  # Assuming result format {role:'fact', content: '... '}
                else:
                    print("No relevant facts found in graph memory.")
                print("=" * 26 + "\n")
            except Exception as e:
                print(f"Error getting memory context: {e}")
            continue  # Skip regular agent interaction after search command

        # Process regular chat input
        agent_response = await memory_agent.chat(user_input)
        print(f"Agent: {agent_response}\n")


# --- Demo Mode Function ---
async def run_demo_agent(
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    email: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    ignore_assistant: bool = False,
    zep_api_key: Optional[str] = None,
):
    """Runs a predefined sequence of interactions with the agent."""
    if not session_id:
        # Create a unique session ID for the demo run
        session_id = f"demo-session-{int(time.time())}"

    memory_agent = AsyncZepMemoryAgent(
        session_id=session_id,
        user_id=user_id,  # Will generate if None
        email=email,
        first_name=first_name,
        last_name=last_name,
        ignore_assistant=ignore_assistant,
        zep_api_key=zep_api_key,
    )

    initialized = await memory_agent.initialize()
    if not initialized:
        print("Agent initialization failed. Exiting demo.")
        return

    print(f"User ID: {memory_agent.user_id}")
    print(f"Session ID: {memory_agent.session_id}")
    print("\n=== Demo Run ===")

    interactions = [
        ("user", "Hi, my name is Alex and I live in London."),
        ("wait", 15),
        ("user", "What city do I live in?"),
        ("wait", 15),
        ("user", "What is my name?"),
    ]

    for type, content in interactions:
        if type == "user":
            print(f"\nYou: {content}")
            response = await memory_agent.chat(content)
            print(f"Agent: {response}")
        elif type == "wait":
            print(f"\n(Waiting {content}s for Zep processing...)")
            await asyncio.sleep(content)

    print("\n=== Demo Run Finished ===\n")
    final_context = await memory_agent.zep_toolkit.get_zep_memor("context")
    print("=== Final Memory Context ===")
    print(final_context if final_context else "No context available.")
    print("==========================")


# --- CLI Setup ---
@click.command()
@click.option("--username", default=None, help="Optional Zep user ID.")
@click.option("--email", default=None, help="Optional email address for the Zep user.")
@click.option("--firstname", default=None, help="Optional first name for the Zep user.")
@click.option("--lastname", default=None, help="Optional last name for the Zep user.")
@click.option(
    "--session",
    default=None,
    help="Optional Zep session ID to reuse or base new ID on.",
)
@click.option(
    "--interactive",
    is_flag=True,
    default=False,  # Default to False (demo mode)
    help="Run in interactive mode for continuous conversation.",
)
@click.option(
    "--ignore-assistant",
    is_flag=True,
    help="Don't persist the assistant's response to the user graph.",
)
@click.option("--debug", is_flag=True, help="Enable DEBUG level logging.")
def main(
    username: Optional[str],
    email: Optional[str],
    firstname: Optional[str],
    lastname: Optional[str],
    session: Optional[str],
    interactive: bool,
    ignore_assistant: bool,
):
    """
    Run the Zep Memory Agent using Agno components.
    """
    if interactive:
        asyncio.run(
            run_interactive_agent(
                session_id=session,
                user_id=username,
                email=email,
                first_name=firstname,
                last_name=lastname,
                ignore_assistant=ignore_assistant,
            )
        )
    else:
        asyncio.run(
            run_demo_agent(  # Call the new demo function
                session_id=session,
                user_id=username,
                email=email,
                first_name=firstname,
                last_name=lastname,
                ignore_assistant=ignore_assistant,
            )
        )


if __name__ == "__main__":
    main()
