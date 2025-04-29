"""
This example demonstrates how to use the Mem0Toolkit class to interact with memories stored in Mem0.
"""

import time
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.mem0 import Mem0Toolkit

# Define a User ID for the session
USER_ID = "john_billings"

# -----------------------------------------------------------------------------------------------
# Example 1: Basic Usage
# -----------------------------------------------------------------------------------------------

agent = Agent(
    model=OpenAIChat(id="o4-mini"),
    tools=[Mem0Toolkit()],
    instructions=dedent(
        f"""
        You are a helpful assistant interacting with user: {USER_ID}.
        You MUST use the `Mem0Toolkit` to manage memories effectively.
        The user's identifier is: {USER_ID}

        **Tool Usage Guidelines:**

        1.  **`add_memory`**: Call this after processing each user message containing new information to save it. You MUST include `user_id='{USER_ID}'`. The tool returns a result containing the `memory_id` of the added memory. Example: `add_memory(messages=[{{'role': 'user', 'content': 'I like pizza'}}], user_id='{USER_ID}')`
        2.  **`search_memory`**: Call this when the user asks about past information or when you need context. You MUST include `user_id='{USER_ID}'`. The tool returns a list of relevant memories, each including its `memory_id`. Example: `search_memory(query='favorite food', user_id='{USER_ID}')`
        3.  **`get_memory`**: Use this to retrieve the exact content of a *specific* memory if you know its `memory_id` (obtained from `add_memory` or `search_memory` results). Example: `get_memory(memory_id='some-abc-123')`
        4.  **`update_memory`**: Use this to modify an *existing* memory. First, use `search_memory` to find the relevant memory and get its `memory_id`. Then, call this tool. Example: `update_memory(memory_id='some-abc-123', data='User now likes pasta')`
        5.  **`delete_memory`**: Use this to delete a *specific* memory. First, use `search_memory` to find the relevant memory and get its `memory_id`. Then, call this tool. Example: `delete_memory(memory_id='some-abc-123')`
        6.  **`get_all_memories`**: Use this when the user asks to list *all* memories you have about them. You MUST include `user_id='{USER_ID}'`. Example: `get_all_memories(user_id='{USER_ID}')`
        7.  **`delete_all_memories`**: Use this ONLY if the user explicitly asks to delete *all* their memories. Be cautious. You MUST include `user_id='{USER_ID}'`. Example: `delete_all_memories(user_id='{USER_ID}')`
        8.  **`get_memory_history`**: Use this to see the change history of a *specific* memory if you know its `memory_id` (obtained from `add_memory` or `search_memory` results). Example: `get_memory_history(memory_id='some-abc-123')`

        **Workflow:**
        - **Always add context:** Call `add_memory` after user turns with new info.
        - **Search before answering questions:** Call `search_memory` to retrieve relevant facts before answering user questions about past information.
        - **Use IDs for specific operations:** Parse results from `add_memory` and `search_memory` to get `memory_id`s required for `get_memory`, `update_memory`, `delete_memory`, and `get_memory_history`.
        - **Prioritize recalled memories:** Base your answers about the user on information retrieved using
        """
    ),
    show_tool_calls=True,
)

agent.print_response("My name is John Billings")
agent.print_response("I live in NYC")
agent.print_response("Delete all memories")
agent.print_response("I'm going to a concert tomorrow")

agent.print_response("What do you know about me?")

# -----------------------------------------------------------------------------------------------
# Example 2: Advanced Usage - Demonstrating All Tools
# -----------------------------------------------------------------------------------------------

# Note: For a real application, you might pass a default user_id to the toolkit initialization

# agent_advanced = Agent(
#     model=OpenAIChat(id="o4-mini"),
#     tools=[Mem0Toolkit(user_id=USER_ID)], # Use the toolkit instance for this example
#     instructions=dedent(
#         f"""
#         You are a helpful assistant interacting with user: {USER_ID}.
#         You MUST use the `Mem0Toolkit` to manage memories effectively.
#         The user's identifier is: {USER_ID}

#         **Tool Usage Guidelines:**

#         1.  **`add_memory`**: Call this after processing each user message containing new information to save it. You MUST include `user_id='{USER_ID}'`. The tool returns a result containing the `memory_id` of the added memory. Example: `add_memory(messages=[{{'role': 'user', 'content': 'I like pizza'}}], user_id='{USER_ID}')`
#         2.  **`search_memory`**: Call this when the user asks about past information or when you need context. You MUST include `user_id='{USER_ID}'`. The tool returns a list of relevant memories, each including its `memory_id`. Example: `search_memory(query='favorite food', user_id='{USER_ID}')`
#         3.  **`get_memory`**: Use this to retrieve the exact content of a *specific* memory if you know its `memory_id` (obtained from `add_memory` or `search_memory` results). Example: `get_memory(memory_id='some-abc-123')`
#         4.  **`update_memory`**: Use this to modify an *existing* memory. First, use `search_memory` to find the relevant memory and get its `memory_id`. Then, call this tool. Example: `update_memory(memory_id='some-abc-123', data='User now likes pasta')`
#         5.  **`delete_memory`**: Use this to delete a *specific* memory. First, use `search_memory` to find the relevant memory and get its `memory_id`. Then, call this tool. Example: `delete_memory(memory_id='some-abc-123')`
#         6.  **`get_all_memories`**: Use this when the user asks to list *all* memories you have about them. You MUST include `user_id='{USER_ID}'`. Example: `get_all_memories(user_id='{USER_ID}')`
#         7.  **`delete_all_memories`**: Use this ONLY if the user explicitly asks to delete *all* their memories. Be cautious. You MUST include `user_id='{USER_ID}'`. Example: `delete_all_memories(user_id='{USER_ID}')`
#         8.  **`get_memory_history`**: Use this to see the change history of a *specific* memory if you know its `memory_id` (obtained from `add_memory` or `search_memory` results). Example: `get_memory_history(memory_id='some-abc-123')`

#         **Workflow:**
#         - **Always add context:** Call `add_memory` after user turns with new info.
#         - **Search before answering questions:** Call `search_memory` to retrieve relevant facts before answering user questions about past information.
#         - **Use IDs for specific operations:** Parse results from `add_memory` and `search_memory` to get `memory_id`s required for `get_memory`, `update_memory`, `delete_memory`, and `get_memory_history`.
#         - **Prioritize recalled memories:** Base your answers about the user on information retrieved using the tools.
#         """
#     ),
#     show_tool_calls=True,
# )

# print("\n--- Starting Example 2: Advanced Usage ---")
# # Add initial memories
# agent_advanced.print_response("I like dogs.")
# agent_advanced.print_response("My favorite food is pizza.")

# # Search for a memory
# agent_advanced.print_response("What pets do I like?")

# # Update a memory (Agent needs to search first to get ID, then update)
# agent_advanced.print_response("Actually, change that, I like cats now.")

# # Get history of the updated memory (Agent needs ID again)
# agent_advanced.print_response("Show me the history of the memory about my pet preference.")

# # Get a specific memory (Agent needs to search first to get ID)
# agent_advanced.print_response("What was that specific memory about my favorite food?")

# # Get all memories
# agent_advanced.print_response("List all memories you have about me.")

# # Delete a specific memory (Agent needs to search first to get ID)
# agent_advanced.print_response("Forget about my favorite food.")

# # Verify deletion
# agent_advanced.print_response("What do you know about me now?")

# # Delete all memories
# agent_advanced.print_response("Delete all my memories permanently.")

# # Verify final deletion
# agent_advanced.print_response("Is there anything left you know about me?")


# -----------------------------------------------------------------------------------------------
# Example 3: Custom embedding model
# -----------------------------------------------------------------------------------------------
# Make sure to set GROQ_API_KEY
# config = {
#     "llm": {
#         "provider": "groq",
#         "config": {
#             "model": "llama-3.3-70b-versatile",
#             "temperature": 0.1,
#             "max_tokens": 2000,
#         }
#     }
# }
# agent = Agent(
#     model=OpenAIChat(id="o4-mini"),
#     tools=[Mem0Toolkit(config=config)],
#     instructions=dedent(
#         f"""
#         You are a helpful assistant interacting with user: {USER_ID}.
#         You MUST use the `Mem0Toolkit` to manage memories effectively.
#         The user's identifier is: {USER_ID}

#         **Tool Usage Guidelines:**

#         1.  **`add_memory`**: Call this after processing each user message containing new information to save it.
#             - You MUST include `user_id='{USER_ID}'`.
#             - The `messages` argument MUST be a LIST containing one or more dictionaries.
#             - EACH dictionary in the list MUST have a `'role'` key (e.g., 'user' or 'assistant') and a `'content'` key (the text of the message).
#             - **DO NOT** pass arbitrary key-value pairs. ONLY use the `{{'role': ..., 'content': ...}}` structure inside the list.
#             - Example: `add_memory(messages=[{{'role': 'user', 'content': 'I like pizza'}}], user_id='{USER_ID}')`
#             - The tool returns a result potentially containing the `memory_id` of the added memory.

#         2.  **`search_memory`**: Call this when the user asks about past information or when you need context.
#             - You MUST include `user_id='{USER_ID}'`.
#             - Example: `search_memory(query='favorite food', user_id='{USER_ID}')`
#             - The tool returns a list of relevant memories, each including its `memory_id`.

#         3.  **`get_memory`**: Use this to retrieve the exact content of a *specific* memory if you know its `memory_id` (obtained from `add_memory` or `search_memory` results).
#             - Example: `get_memory(memory_id='some-abc-123')`

#         4.  **`update_memory`**: Use this to modify an *existing* memory.
#             - First, use `search_memory` to find the relevant memory and get its `memory_id`.
#             - Then, call this tool with the `memory_id` and the new `data` (content).
#             - Example: `update_memory(memory_id='some-abc-123', data='User now likes pasta')`

#         5.  **`delete_memory`**: Use this to delete a *specific* memory.
#             - First, use `search_memory` to find the relevant memory and get its `memory_id`.
#             - Then, call this tool with the `memory_id`.
#             - Example: `delete_memory(memory_id='some-abc-123')`

#         6.  **`get_all_memories`**: Use this when the user asks to list *all* memories you have about them.
#             - You MUST include `user_id='{USER_ID}'`.
#             - Example: `get_all_memories(user_id='{USER_ID}')`

#         7.  **`delete_all_memories`**: Use this ONLY if the user explicitly asks to delete *all* their memories.
#             - Be cautious.
#             - You MUST include `user_id='{USER_ID}'`.
#             - Example: `delete_all_memories(user_id='{USER_ID}')`

#         8.  **`get_memory_history`**: Use this to see the change history of a *specific* memory if you know its `memory_id`.
#             - Example: `get_memory_history(memory_id='some-abc-123')`

#         **Workflow:**
#         - **Always add user/assistant messages:** Call `add_memory` with the correct `messages` format (list of dicts with `role` and `content`) after relevant turns.
#         - **Search before answering questions:** Call `search_memory` to retrieve relevant facts before answering user questions about past information.
#         - **Use IDs for specific operations:** Parse results from `add_memory` and `search_memory` to get `memory_id`s required for `get_memory`, `update_memory`, `delete_memory`, and `get_memory_history`.
#         - **Prioritize recalled memories:** Base your answers about the user on information retrieved using the tools.
#         """
#     ),
#     show_tool_calls=True,
# )

# print("\n--- Running Mem0 Demo --- ")
# # Add initial memories
# agent.print_response("My name is John Billings")
# agent.print_response("I live in NYC")
# agent.print_response("What is my name?")
# agent.print_response("Actually, my name is Jonathan Billings.")
# agent.print_response("Show me the history of the memory about my name.")
# agent.print_response("What was that specific memory about where I live?")
# agent.print_response("List all memories you have about me.")
# agent.print_response("Forget where I live.")
# agent.print_response("What do you know about me now?")
# agent.print_response("Delete all my memories permanently.")
# agent.print_response("Is there anything left you know about me?")

# -----------------------------------------------------------------------------------------------
# Example using API Key (Optional - Requires MEM0_API_KEY env var)
# -----------------------------------------------------------------------------------------------

# To get started, please export your Mem0 API key as an environment variable. You can get your Mem0 API key from https://app.mem0.ai/dashboard/api-keys
# export MEM0_API_KEY=<your-mem0-api-key> (optional)

# agent_api = Agent(
#     model=OpenAIChat(id="o4-mini"),
#     tools=[
#         Mem0Toolkit(
#             api_key="m0-4usPmdPK98zFmDougPXDmNqje1GA2Rn1HwcMPj73",
#             user_id=USER_ID + "-api",
#         )
#     ],
#     instructions=dedent(f"""
#     You are a helpful assistant interacting with user: {USER_ID + "-api"}.
#     You MUST use the `Mem0Toolkit` to manage memories effectively.
#     The user's identifier is: {USER_ID + "-api"}

#     **Tool Usage Guidelines:**

#     1.  **`add_memory`**: Call this after processing user messages with new info.
#         - You MUST include `user_id='{USER_ID + "-api"}'`. 
#         - The `messages` argument **MUST** be a LIST containing one or more dictionaries.
#         - **EACH dictionary** in the list **MUST** strictly follow the format: `{{'role': 'user', 'content': '...'}}` or `{{'role': 'assistant', 'content': '...'}}`. 
#         - Use `'user'` for the user's message and `'assistant'` for your previous responses if relevant.
#         - **CRITICAL:** Do NOT invent other keys like 'hobby', 'name', 'event'. The ONLY allowed keys in the dictionary are `'role'` and `'content'`.
#         - **Correct Example:** `add_memory(messages=[{{'role': 'user', 'content': 'My hobby is painting.'}}], user_id='{USER_ID + "-api"}')`
#         - **Incorrect Example:** `add_memory(messages={{'hobby': 'painting'}}, user_id='{USER_ID + "-api"}')`

#     2.  **`search_memory`**: Call this to find relevant past information.
#         - You MUST include `user_id='{USER_ID + "-api"}'`. 
#         - Example: `search_memory(query='user hobby', user_id='{USER_ID + "-api"}')`

#     (Include descriptions for other tools: get_memory, update_memory, delete_memory, get_all_memories, delete_all_memories, get_memory_history as in the previous example, ensuring user_id is set to '{USER_ID + "-api"}')

#     **Workflow:**
#     - Add user messages using `add_memory` with the **strict** `messages=[{{'role': 'user', 'content': ...}}]` format.
#     - Use `search_memory` to retrieve information before answering questions about the past.
#     - Use `memory_id` from search results for other specific tools when needed.
#     """),
#     show_tool_calls=True,
#     debug_mode=True,
# )
# agent_api.print_response("My hobby is painting.")
# agent_api.print_response("What is my hobby?")
