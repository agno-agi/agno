## Part 2: Giving Your Agent Tools - Extending Capabilities

While a basic agent can understand and generate text based on its instructions, its capabilities are limited to the knowledge it was trained on. To make your agent truly powerful and interactive, you can give it **Tools**. Tools are special functions or integrations that allow your agent to:

*   Fetch real-time information from the internet (e.g., current news, weather).
*   Interact with external APIs (e.g., search engines, databases, booking systems).
*   Perform specific calculations or data manipulations.
*   Access and modify local files.

Essentially, tools bridge the gap between your agent's conversational intelligence and the vast world of external data and actions.

### 2.1 Using Pre-built Tools

The `superagent` library and its ecosystem often provide pre-built tools that you can easily integrate into your agents. These tools are ready-to-use functionalities for common tasks.

**Concept:** Integrating existing tools is straightforward. You typically import the tool and then pass a list of tool instances to the `tools` parameter when initializing your `Agent`.

**Key Components:**

*   **`tools` parameter in `Agent`:** This parameter accepts a list of tool objects. By providing tools here, you're equipping your agent with new skills.
*   **`show_tool_calls=True`:** When you initialize your `Agent` with `show_tool_calls=True`, the agent will print out information whenever it decides to use a tool and what the outcome of that tool use was. This is incredibly useful for debugging and understanding your agent's reasoning process.

**Example Breakdown: `cookbook/getting_started/02_agent_with_tools.py`**

This example demonstrates how to give an agent the ability to search the web using the `DuckDuckGoTools` pre-built tool.

1.  **Import and Initialization:**
    ```python
    from superagent import Agent
    from superagent.models import OpenAIChat
    from superagent.tools.web import DuckDuckGoTools # Import the tool

    # Initialize the language model
    llm = OpenAIChat()

    # Create the agent, now with tools
    my_search_agent = Agent(
        model=llm,
        instructions="You are a helpful assistant that can search the web.",
        tools=[DuckDuckGoTools()], # Add the tool instance here
        show_tool_calls=True      # Enable visibility into tool usage
    )
    ```
    Notice how `DuckDuckGoTools()` is instantiated and passed as a list to the `tools` parameter.

2.  **Agent Invocation and Tool Usage:**
    When you ask the agent something that requires external information, like "What's the latest news on AI?", the agent, guided by its instructions and the presence of `DuckDuckGoTools`, will recognize that it needs to use the search tool.
    ```python
    response = my_search_agent.invoke("What's the capital of France?")
    print(response)
    ```
    If `show_tool_calls` is `True`, you'll see output in your console indicating that the `DuckDuckGoTools` was called, what search query it used, and what information it retrieved. The agent then uses this retrieved information to formulate its final answer.

**Your Turn: Run and Experiment!**

*   **Find the file:** Open `cookbook/getting_started/02_agent_with_tools.py`.
*   **Read the code:** Note how `DuckDuckGoTools` is added and `show_tool_calls=True` is set.
*   **Run it:** Execute `python cookbook/getting_started/02_agent_with_tools.py`.
*   **Observe:**
    *   Try different queries. Some that clearly require web search (e.g., "What's the weather like in London?") and some that don't (e.g., "Tell me a short story.").
    *   Pay attention to the console output showing the tool calls. How does the agent decide when to use the tool?
    *   What happens if you set `show_tool_calls=False`? (You'll still get the answer, but without the intermediate tool call logs).

### 2.2 Creating Custom Tools

While pre-built tools are convenient, you'll often need your agent to perform tasks specific to your application or domain. This is where custom tools come in. You can define your own Python functions and make them available to your agent.

**Concept:** The recommended way to create custom tools in `superagent` is by using the `@tool` decorator provided by `agno.tools`. This decorator wraps your Python function, making it understandable and usable by the agent.

**Key Components:**

*   **Simple Python functions:** At its heart, a custom tool is just a Python function that performs a specific action.
*   **The `@tool` decorator:** Imported from `agno.tools`, this decorator is placed directly above your function definition. It handles the necessary boilerplate to register your function as a tool that the agent can call.
*   **Docstrings:** The docstring of your function is very important! The agent uses the docstring to understand what the tool does and when to use it. A clear and descriptive docstring is crucial for the agent to effectively utilize your custom tool.

**Primary Example (using `@tool` decorator): `cookbook/agent_concepts/tool_concepts/custom_tools/tool_decorator.py`**

This example showcases the power and flexibility of the `@tool` decorator, including accessing agent context and streaming results.

1.  **Defining the Tool:**
    ```python
    from agno.tools import tool
    from superagent import Agent
    from superagent.models import OpenAIChat
    import httpx # For making HTTP requests

    @tool
    def get_top_hackernews_stories(agent, limit: int = 5):
        """
        Fetches the top stories from Hacker News.

        Args:
            limit: The maximum number of stories to return.
        """
        agent.context.set("hackernews_api_accessed", True) # Example of setting context
        hn_url = "https://hacker-news.firebaseio.com/v0"
        
        # Simulate streaming by yielding results
        yield "Fetching top story IDs..."
        top_story_ids = httpx.get(f"{hn_url}/topstories.json").json()
        
        count = 0
        for story_id in top_story_ids:
            if count >= limit:
                break
            yield f"Fetching story ID: {story_id}..."
            story_data = httpx.get(f"{hn_url}/item/{story_id}.json").json()
            yield {"title": story_data.get("title"), "url": story_data.get("url")}
            count += 1

    # Initialize agent with the custom tool
    llm = OpenAIChat()
    hn_agent = Agent(
        model=llm,
        tools=[get_top_hackernews_stories],
        instructions="You are a helpful assistant that can fetch Hacker News stories.",
        show_tool_calls=True
    )

    hn_agent.print_response(f"Get me the top 3 stories from Hacker News.", stream_handler=print)
    # Check context
    # print(f"Hacker News API accessed: {hn_agent.context.get('hackernews_api_accessed')}")
    ```
    *   **`@tool`:** The function `get_top_hackernews_stories` is decorated with `@tool`.
    *   **Docstring:** The docstring clearly explains what the tool does and what its arguments are. This is crucial for the agent to understand when and how to use this tool.
    *   **`agent` parameter:** Notice the first parameter `agent`. When the `@tool` decorator is used, your function can optionally accept the calling `Agent` instance as its first argument. This allows the tool to access agent-specific information or methods if needed, such as `agent.context`.
    *   **`agent.context`:** The example shows `agent.context.set("hackernews_api_accessed", True)`. The `agent.context` is a dictionary-like store where tools (or the agent itself) can read or write information during an interaction. This can be useful for sharing state between tool calls or for the agent to remember things.
    *   **`yield` for Streaming:** Instead of returning all results at once, this tool `yield`s multiple times. This is a way to stream results back to the agent (and potentially to the end-user) as they become available, which is great for long-running tasks. When a tool yields, the agent can process these partial results. The `stream_handler=print` in `print_response` will print these yielded chunks as they arrive.
    *   **Type Hinting:** Using type hints (e.g., `limit: int = 5`) in your tool's function signature helps the agent understand the expected data types for arguments.

2.  **Using the Tool with an Agent:**
    The `get_top_hackernews_stories` function (which is now a tool) is included in the `tools` list when creating `hn_agent`. When you ask this agent to get Hacker News stories, it will understand that it should use your custom tool.

**Basic Example (Simple Function): `cookbook/getting_started/07_write_your_own_tool.py`**

For context, it's useful to know that even a simple Python function can act as a tool *without* the `@tool` decorator, especially if it doesn't need advanced features like context access or automatic schema generation from type hints.

*   **File:** `cookbook/getting_started/07_write_your_own_tool.py`
*   **Focus:** This example shows a very basic custom tool:
    ```python
    # (Simplified from the example file)
    def get_current_time():
      """Returns the current time."""
      import datetime
      return datetime.datetime.now().isoformat()

    # my_agent = Agent(..., tools=[get_current_time])
    ```
    Here, `get_current_time` is a plain Python function. The agent can still use its name and docstring to figure out how to use it. However, the `@tool` decorator offers more robustness, better integration with the agent's systems (like type checking based on hints), and features like context access and easier streaming. **For most custom tool development, the `@tool` decorator is the preferred method.**

**Supporting Example (Variety of Tool Types): `cookbook/tools/custom_tools.py`**

This file further illustrates the flexibility of the `superagent` library in how you can define tools. While the `@tool` decorator is recommended for most cases, `superagent` can often adapt various Python callables to serve as tools.

*   **File:** `cookbook/tools/custom_tools.py`
*   **Focus:** This script showcases different ways to define tools:
    *   Functions returning simple dictionaries or lists.
    *   Functions returning Pydantic models (which `superagent` can automatically convert into structured descriptions for the agent).
    *   More complex classes or callables.
*   **Key Takeaway:** The library is designed to be flexible. However, for clarity, maintainability, and access to advanced features, starting with the `@tool` decorator on your Python functions is the best practice for creating custom tools.

**Your Turn: Explore Custom Tools!**

*   **Primary Example (`tool_decorator.py`):**
    *   **Find and run:** `python cookbook/agent_concepts/tool_concepts/custom_tools/tool_decorator.py`
    *   **Observe:** How are the streamed results printed? Modify the input to ask for a different number of stories.
    *   **Experiment:**
        *   Change the docstring of `get_top_hackernews_stories`. How does this affect the agent's ability to use it (or use it correctly)?
        *   Try adding another simple `@tool` decorated function to the `hn_agent` and see if you can get the agent to call it.
        *   Examine how `agent.context` is used. Try printing `hn_agent.context.get('hackernews_api_accessed')` after the agent runs to see the value.
*   **Basic Example (`07_write_your_own_tool.py`):**
    *   **Find and run:** `python cookbook/getting_started/07_write_your_own_tool.py`
    *   **Compare:** Note its simplicity. Understand that while this works, `@tool` provides more structure.
*   **Variety Example (`custom_tools.py`):**
    *   **Find and run:** `python cookbook/tools/custom_tools.py`
    *   **Browse the code:** See the different ways tools can be structured. This is good for understanding the underlying flexibility, but remember to lean on `@tool` for your own development.

By creating and integrating custom tools, you significantly expand what your agents can achieve, tailoring them to your specific needs and workflows. Remember that clear docstrings and function signatures are key to helping the agent understand and correctly use the tools you provide.
---
