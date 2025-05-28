# SuperAgent in a Day: A Practical Guide to Building AI Agents

**Welcome!**

This guide is designed to be your accelerated path to understanding and building powerful AI agents using the `agno` Python library. We believe in learning by doing, so we'll heavily leverage the rich examples available in the official `cookbook` directory. Our core objective is to equip you with a solid grasp of agents, how to give them tools, enable memory, and touch upon basic agent architectures—all achievable within a dedicated day of learning. Whether you're a developer looking to integrate AI into your applications or an enthusiast curious about agentic AI, this guide will provide a practical, hands-on introduction. Let's embark on this exciting journey together!

**Prerequisites:**

To make the most of this guide, you should have:

*   **Basic Python knowledge:** You should be comfortable reading and writing simple Python scripts, understanding functions, classes, and basic data structures.
*   **A Python environment:** You'll need an environment (like a virtual environment) where you can install Python packages using `pip`. The examples will require libraries such as `openai`, `agno` (e.g., `pip install openai agno`), and others as specified in individual `cookbook` scripts.
*   **API keys:** Many examples, especially those involving `OpenAIChat` or other commercial LLMs (like Anthropic Claude or Google Gemini), will require API keys for these services. Ensure you have these ready and configured in your environment (usually as environment variables, e.g., `OPENAI_API_KEY`).

**How to Use This Guide:**

This guide is structured to be interactive and example-driven:

*   **Follow Sequentially:** Each section builds upon the previous ones, introducing new concepts and functionalities. It's best to go through them in order.
*   **Engage with the Cookbook:** Each part will direct you to specific Python files within the `cookbook` directory of the `agno` repository. These are your primary learning resources.
*   **Read, Run, Understand:**
    *   **Open and Read:** Carefully read the code and any accompanying comments in the example files. Understand the setup, the components being used, and the logic flow.
    *   **Run the Examples:** Execute the Python scripts from your terminal. Observe their output and how they behave.
*   **Experiment Actively:** This is crucial for effective learning.
    *   Modify agent instructions.
    *   Change the inputs you provide to the agents.
    *   If a tool is used, try altering its parameters or the way the agent is prompted to use it.
    *   Tweak configuration parameters like `num_history_runs` for memory or `reasoning=True` for chain-of-thought.
    *   Don't be afraid to break things – it's often the best way to learn!

---
## Part 1: Your First Agent - Understanding the Basics

Welcome to the world of AI agents! At its core, an agent is like a smart assistant that can understand instructions, process information, and perform tasks. In the `agno` library, an **Agent** is an entity that you can instruct to behave in a certain way and interact with. It's your primary building block for creating sophisticated AI applications.

Let's dive into how you create your very first agent.

**Key Components:**

*   **`Agent`:** This is the central class you'll use. Think of it as the brain of your AI. You initialize an `Agent` to get started.
*   **`Model`:** An agent needs a "language model" to understand and generate text. The `agno` library supports various models, and a common one you'll see is `OpenAIChat` (which uses OpenAI's chat models like GPT-3.5 or GPT-4). You pass a model instance to your agent during initialization. This tells the agent which LLM to use for its "thinking" process.
*   **`instructions`:** This is where you give your agent its personality, purpose, and rules of engagement. The `instructions` parameter is typically a string of text that tells the agent how it should behave. For example, you could instruct it to be a "helpful assistant," a "sarcastic poet," or a "technical expert in Python." These instructions guide the agent's responses and actions.

**Example Breakdown: `cookbook/getting_started/01_basic_agent.py`**

Let's look at the provided example file, `cookbook/getting_started/01_basic_agent.py`. This script demonstrates the fundamental steps of creating and running a simple agent.

1.  **Initialization:**
    You'll typically see something like this:
    ```python
    from agno.agent import Agent
    from agno.models.openai import OpenAIChat

    # Initialize the language model
    llm = OpenAIChat() # Assumes OPENAI_API_KEY is set in environment

    # Create the agent
    my_agent = Agent(
        model=llm,
        instructions="You are a friendly assistant that loves to tell jokes."
    )
    ```
    Here, we first import the necessary classes. Then, we create an instance of `OpenAIChat`. Finally, we instantiate our `Agent`, passing the `llm` as the `model` and providing a simple set of `instructions`. This agent is now primed to be a joke-telling friendly assistant!

2.  **Running the Agent and Getting a Response:**
    Once your agent is created, you can interact with it. The example shows how to send a message to the agent and get its response, typically by printing it directly to the console with streaming:
    ```python
    # Get a response from the agent and stream it to the console
    my_agent.print_response("Tell me a joke about computers.", stream=True)
    ```
    The `print_response()` method with `stream=True` is a common way to "talk" to your agent and see its output in real-time. You pass your input (e.g., "Tell me a joke about computers."), and the agent, guided by its `instructions` and powered by its `model`, will generate a response.

**Your Turn: Run and Experiment!**

*   **Find the file:** Open `cookbook/getting_started/01_basic_agent.py` in your code editor.
*   **Read the code:** Pay close attention to how the `Agent` is initialized with `OpenAIChat` and the specific `instructions` given.
*   **Run it:** Execute the script from your terminal: `python cookbook/getting_started/01_basic_agent.py`
*   **Observe:** See the output. Does the agent behave according to its instructions?
*   **Modify and Experiment:** This is the most crucial part of learning!
    *   Change the `instructions`. What happens if you tell it to be a "serious historian" or a "pirate captain"?
    *   Change the input message you send via `print_response()`.
    *   If you're comfortable, and once you explore more about models, you could even try swapping out the model (though `01_basic_agent.py` is set up for `OpenAIChat`).

By running and tweaking this basic example, you'll gain a solid understanding of how to create, instruct, and interact with your first AI agent. This forms the foundation for building much more complex and capable agents later on!
---
## Part 2: Giving Your Agent Tools - Extending Capabilities

While a basic agent can understand and generate text based on its instructions, its capabilities are limited to the knowledge it was trained on. To make your agent truly powerful and interactive, you can give it **Tools**. Tools are special functions or integrations that allow your agent to:

*   Fetch real-time information from the internet (e.g., current news, weather).
*   Interact with external APIs (e.g., search engines, databases, booking systems).
*   Perform specific calculations or data manipulations.
*   Access and modify local files.

Essentially, tools bridge the gap between your agent's conversational intelligence and the vast world of external data and actions.

### 2.1 Using Pre-built Tools

The `agno` library and its ecosystem often provide pre-built tools that you can easily integrate into your agents. These tools are ready-to-use functionalities for common tasks.

**Concept:** Integrating existing tools is straightforward. You typically import the tool and then pass a list of tool instances to the `tools` parameter when initializing your `Agent`.

**Key Components:**

*   **`tools` parameter in `Agent`:** This parameter accepts a list of tool objects. By providing tools here, you're equipping your agent with new skills.
*   **`show_tool_calls=True`:** When you initialize your `Agent` with `show_tool_calls=True`, the agent will print out information whenever it decides to use a tool and what the outcome of that tool use was. This is incredibly useful for debugging and understanding your agent's reasoning process.

**Example Breakdown: `cookbook/getting_started/02_agent_with_tools.py`**

This example demonstrates how to give an agent the ability to search the web using the `DuckDuckGoTools` pre-built tool.

1.  **Import and Initialization:**
    ```python
    from agno.agent import Agent
    from agno.models.openai import OpenAIChat
    from agno.tools.web import DuckDuckGoTools # Import the tool

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
    my_search_agent.print_response("What's the capital of France?", stream=True)
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

**Concept:** The recommended way to create custom tools in `agno` is by using the `@tool` decorator provided by `agno.tools`. This decorator wraps your Python function, making it understandable and usable by the agent.

**Key Components:**

*   **Simple Python functions:** At its heart, a custom tool is just a Python function that performs a specific action.
*   **The `@tool` decorator:** Imported from `agno.tools`, this decorator is placed directly above your function definition. It handles the necessary boilerplate to register your function as a tool that the agent can call.
*   **Docstrings:** The docstring of your function is very important! The agent uses the docstring to understand what the tool does and when to use it. A clear and descriptive docstring is crucial for the agent to effectively utilize your custom tool.

**Primary Example (using `@tool` decorator): `cookbook/agent_concepts/tool_concepts/custom_tools/tool_decorator.py`**

This example showcases the power and flexibility of the `@tool` decorator, including accessing agent context and streaming results.

1.  **Defining the Tool:**
    ```python
    from agno.tools import tool
    from agno.agent import Agent
    from agno.models.openai import OpenAIChat
    import httpx # For making HTTP requests

    @tool
    def get_top_hackernews_stories(agent, limit: int = 5):
        """get_top_hackernews_stories(limit: int = 5) -> list[dict[str, str]] - Fetches the top stories from Hacker News."""
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

    hn_agent.print_response(f"Get me the top 3 stories from Hacker News.", stream=True)
    # Check context
    # print(f"Hacker News API accessed: {hn_agent.context.get('hackernews_api_accessed')}")
    ```
    *   **`@tool`:** The function `get_top_hackernews_stories` is decorated with `@tool`.
    *   **Docstring:** The docstring (simplified here to reflect the example's actual docstring) is crucial. The agent uses this information, along with the function signature, to understand how and when to use the tool. Even a concise docstring like the one in the actual example (`get_top_hackernews_stories(limit: int = 5) -> list[dict[str, str]] - Fetches the top stories from Hacker News.`) provides essential details. **Always write clear and descriptive docstrings for your tools.**
    *   **`agent` parameter:** Notice the first parameter `agent`. When the `@tool` decorator is used, your function can optionally accept the calling `Agent` instance as its first argument. This allows the tool to access agent-specific information or methods if needed, such as `agent.context`.
    *   **`agent.context`:** The example shows `agent.context.set("hackernews_api_accessed", True)`. The `agent.context` is a dictionary-like store where tools (or the agent itself) can read or write information during an interaction. This can be useful for sharing state between tool calls or for the agent to remember things.
    *   **`yield` for Streaming:** Instead of returning all results at once, this tool `yield`s multiple times. This is a way to stream results back to the agent (and potentially to the end-user) as they become available, which is great for long-running tasks. When a tool yields, the agent can process these partial results. The `print_response(..., stream=True)` method will handle printing these yielded chunks as they arrive.
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

This file further illustrates the flexibility of the `agno` library in how you can define tools. While the `@tool` decorator is recommended for most cases, `agno` can often adapt various Python callables to serve as tools.

*   **File:** `cookbook/tools/custom_tools.py`
*   **Focus:** This script showcases different ways to define tools:
    *   Functions returning simple dictionaries or lists.
    *   Functions returning Pydantic models (which `agno` can automatically convert into structured descriptions for the agent).
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
## Part 3: Giving Your Agent Memory - Context and Learning

Memory is a crucial aspect of intelligent agents, allowing them to recall past interactions, utilize vast amounts of external knowledge, and maintain context over extended conversations. This capability transforms an agent from a simple command-processor into a more adaptive and knowledgeable conversational partner. In `agno`, memory can take several forms, each serving a distinct purpose.

### 3.1 Conversational History

Conversational history enables agents to remember what has been said in the recent parts of an interaction. This is fundamental for coherent and context-aware dialogue.

*   **Concept:** Keeping track of user inputs and agent responses to inform future turns in the conversation.

#### Built-in Chat History

The simplest way to give an agent short-term conversational memory is by using its built-in chat history feature.

*   **Key Components:**
    *   `add_history_to_messages=True`: When initializing an `Agent`, setting this to `True` tells the agent to automatically include previous turns of the conversation in its context when generating a new response.
    *   `num_history_runs`: This parameter, also set during `Agent` initialization, controls how many of the most recent conversational turns are included.

*   **Example: `cookbook/agent_concepts/memory/00_builtin_memory.py`**
    *   **Focus:** This script demonstrates the basic built-in memory. An agent is created with `add_history_to_messages=True`. When you interact with it multiple times, you'll see that it remembers your previous statements within the limit set by `num_history_runs`.
    *   **Code Snippet (Illustrative):**
        ```python
        from agno.agent import Agent
        from agno.models.openai import OpenAIChat

        llm = OpenAIChat()
        agent = Agent(
            model=llm,
            instructions="Remember what I say.",
            add_history_to_messages=True,
            num_history_runs=3 # Remembers the last 3 exchanges
        )

        agent.print_response("My name is Bob.", stream=True)
        # Agent: (Responds to Bob)

        agent.print_response("What is my name?", stream=True) # Agent should remember "Bob"
        # Agent: (Responds with Bob's name)
        ```
    *   **Run it:** `python cookbook/agent_concepts/memory/00_builtin_memory.py`
    *   **Observe:** Notice how the agent can answer questions based on information you provided in earlier turns of the same session. Experiment by changing `num_history_runs`.

#### Persistent Chat Sessions

While built-in history is good for a single session, persistent chat sessions allow conversation history to be stored and retrieved across multiple runs or different instances of your application. This is essential for users who expect the agent to remember them over time.

*   **Key Components:**
    *   `storage`: This parameter in the `Agent` constructor takes a storage backend object. `agno` supports various storage options, with `SqliteStorage` being a common file-based choice for simplicity.
    *   `user_id`: A unique identifier for the user interacting with the agent.
    *   `session_id`: A unique identifier for a specific conversation session. A single user can have multiple sessions.
    *   `read_chat_history=True`: When initializing the `Agent`, this tells it to load existing chat history for the given `user_id` and `session_id` from the configured `storage`.

*   **Example: `cookbook/getting_started/04_agent_with_storage.py`**
    *   **Focus:** This script shows how to set up an agent with `SqliteStorage` to persist chat history. It demonstrates initializing the agent with a `user_id` and `session_id`, allowing it to pick up the conversation where it left off, even if the script is run multiple times.
    *   **Code Snippet (Illustrative):**
        ```python
        from agno.agent import Agent
        from agno.models.openai import OpenAIChat
        from agno.storage.sqlite import SqliteStorage

        # Setup storage
        storage = SqliteStorage.from_uri("sqlite:///./chat_history.db")

        llm = OpenAIChat()
        agent = Agent(
            model=llm,
            instructions="Let's have a continuous conversation.",
            storage=storage,
            user_id="user123",
            session_id="session_abc",
            read_chat_history=True # Load previous messages
        )

        # First run:
        # agent.print_response("My favorite color is blue.", stream=True)
        # Second run:
        # agent.print_response("What is my favorite color?", stream=True)
        ```
    *   **Run it:** `python cookbook/getting_started/04_agent_with_storage.py`
    *   **Observe:** Run the script once, have a short conversation. Then, run it again *using the same `user_id` and `session_id`*. The agent should remember the previous conversation. Try changing the `session_id` to see how it starts a new conversation.

### 3.2 Knowledge Bases - External Information

Knowledge bases allow agents to access and refer to a large corpus of information, such as documents, websites, or other data sources, that go beyond their training data or immediate conversational context.

*   **Concept:** Equipping agents with the ability to perform retrieval-augmented generation (RAG), where they fetch relevant information from a knowledge source before answering a query.

*   **Key Components:**
    *   `knowledge` parameter: In the `Agent` constructor, this takes a list of `KnowledgeBase` objects.
    *   `KnowledgeBase` objects: These define the source and type of knowledge. Examples include:
        *   `PDFUrlKnowledgeBase`: For ingesting information from PDFs hosted online.
        *   `UrlKnowledge`: For ingesting content from web pages.
        *   (Other types exist for local files, text, etc.)
    *   `VectorDB`: A vector database is used to store embeddings of the knowledge content, enabling efficient similarity searches. `LanceDb` is a common choice that can run locally.
    *   `Embedder`: A model (e.g., from OpenAI or HuggingFace) that converts text chunks from the knowledge base into numerical vectors (embeddings).
    *   `knowledge.load()`: A crucial step. After defining a `KnowledgeBase`, you must call its `load()` method (or `load_and_embed()` for some versions/setups) to process the source material, create embeddings, and store them in the `VectorDB`. This only needs to be done once per knowledge source unless the source changes.

*   **Example: `cookbook/getting_started/03_agent_with_knowledge.py`**
    *   **Focus:** This script demonstrates setting up a knowledge base from a PDF document (e.g., the "Leave No Context Behind" paper). It shows how to instruct the agent to use this knowledge when answering questions.
    *   **Code Snippet (Illustrative):**
        ```python
        from agno.agent import Agent
        from agno.models.openai import OpenAIChat
        from agno.knowledge.knowledge_base import PDFUrlKnowledgeBase
        from agno.vector_store.lancedb import LanceDb # Or other VectorDB
        from agno.embeddings.openai import OpenAIEmbeddings # Or other embedder

        # Setup vector store and embedder
        vector_store = LanceDb.from_uri("data/lancedb")
        embedder = OpenAIEmbeddings()

        # Create knowledge base from a PDF URL
        pdf_knowledge = PDFUrlKnowledgeBase(
            url="https://arxiv.org/pdf/2307.03172.pdf", # Example PDF
            vector_store=vector_store,
            embedder=embedder
        )
        # IMPORTANT: Load and embed the knowledge
        # This step processes the PDF and can take time.
        pdf_knowledge.load(recreate=False) # recreate=True if PDF changed

        llm = OpenAIChat()
        agent = Agent(
            model=llm,
            instructions="Answer questions based on the provided document.",
            knowledge=[pdf_knowledge]
        )

        # agent.print_response("What is the main topic of the document?", stream=True)
        ```
    *   **Run it:** `python cookbook/getting_started/03_agent_with_knowledge.py`
    *   **Observe:** The first time you run it, the `load()` process might take a while as it downloads and processes the PDF. Subsequent runs should be faster if `recreate=False` is used. Ask questions that can only be answered by referring to the PDF content. Notice how the agent's answers are grounded in the provided document.

### 3.3 Structured Persistent Memory - Remembering Facts

Beyond conversational flow and document retrieval, agents can be given the ability to remember and recall specific, structured facts, often about users, entities, or preferences. This is like giving the agent a long-term, organized notepad.

*   **Concept:** Storing key-value like pieces of information (memories) associated with users or other identifiers, allowing for personalized and context-rich interactions over time.

*   **Key Components:**
    *   `Memory` class: The central class for managing structured memories. It's initialized with a database backend.
    *   `UserMemory` objects: Represent individual pieces of memory, typically containing a `fact` (what the agent remembers) and associated metadata like `user_id`, `entity` (who/what the fact is about), and `citable_link` (source of the fact).
    *   Database backends: e.g., `SqliteMemoryDb` for storing memories in a SQLite database. Other backends might be available.
    *   `enable_user_memories=True`: When set on an `Agent`, this allows the agent to proactively try and extract facts from the conversation and store them as `UserMemory` objects.

#### Core `Memory` Object and Persistence

This focuses on setting up the `Memory` system itself with a persistent store.

*   **File: `cookbook/agent_concepts/memory/02_persistent_memory.py`**
    *   **Focus:** Shows how to initialize the `Memory` class with a database backend (e.g., `SqliteMemoryDb`). It then demonstrates creating `UserMemory` entries and adding them to this persistent memory store. This is the foundational setup for any structured memory usage.
    *   **Code Snippet (Illustrative):**
        ```python
        from agno.memory.memory import Memory
        from agno.memory.models import UserMemory
        from agno.memory.storage.sqlite import SqliteMemoryDb

        # Initialize memory with a SQLite database
        memory_db = SqliteMemoryDb.from_uri("sqlite:///./user_memories.db")
        memory = Memory(memory_db=memory_db)

        # Create a user memory
        new_memory = UserMemory(
            user_id="user_jane",
            fact="Jane's favorite programming language is Python.",
            entity="Jane",
            citable_link="conversation_turn_4"
        )
        memory.add_user_memory(new_memory)
        # print(f"Memory added: {new_memory.fact}")
        ```
    *   **Run it:** `python cookbook/agent_concepts/memory/02_persistent_memory.py`
    *   **Observe:** This script primarily sets up the database and adds a memory. You can inspect the created `user_memories.db` file (using a SQLite browser) to see the stored data.

#### Manual Memory Management

This involves directly interacting with the `Memory` object to create, read, update, and delete memories.

*   **File: `cookbook/agent_concepts/memory/01_standalone_memory.py`**
    *   **Focus:** Demonstrates the fundamental CRUD (Create, Read, Update, Delete) operations for `UserMemory` directly using the `Memory` object. This gives you fine-grained control over the memory store.
    *   **Code Snippet (Illustrative):**
        ```python
        # (Assumes memory object is initialized as in 02_persistent_memory.py)
        
        # Create (add)
        # memory.add_user_memory(...)
        
        # Read (get)
        # retrieved_memories = memory.get_user_memories(user_id="user_jane")
        
        # Update (usually involves getting, modifying, and re-adding or a specific update method)
        # For example, if a memory object has an id:
        # mem_to_update = memory.get_user_memory_by_id(...)
        # if mem_to_update:
        #    mem_to_update.fact = "New fact"
        #    memory.update_user_memory(mem_to_update)

        # Delete
        # memory.delete_user_memory(memory_id=...) # Or by other criteria
        ```
    *   **Run it:** `python cookbook/agent_concepts/memory/01_standalone_memory.py`
    *   **Observe:** Follow the script's operations. You'll see memories being added, fetched, potentially updated, and removed. This script gives a clear picture of how to programmatically manage the memory content.

#### Searching Stored Memories

Once memories are stored, you need efficient ways to retrieve relevant ones.

*   **File: `cookbook/agent_concepts/memory/05_memory_search.py`**
    *   **Focus:** This script showcases the `search_user_memories` method of the `Memory` object. It demonstrates different search strategies:
        *   `last_n`: Retrieve the N most recently added memories.
        *   `first_n`: Retrieve the N oldest memories.
        *   `agentic`: This is a more advanced search that uses an LLM to find memories semantically relevant to a given query or context.
    *   **Code Snippet (Illustrative):**
        ```python
        from agno.models.openai import OpenAIChat
        # (Assumes memory object is initialized and populated)
        # search_results_last = memory.search_user_memories(
        #    user_id="user_jane", query="favorite language", search_type="last_n", last_n=1
        # )
        # search_results_agentic = memory.search_user_memories(
        #    user_id="user_jane", query="What does Jane like?", search_type="agentic", llm=OpenAIChat()
        # )
        ```
    *   **Run it:** `python cookbook/agent_concepts/memory/05_memory_search.py`
    *   **Observe:** See how different search types yield different results. The `agentic` search is particularly powerful for finding memories that don't exactly match keywords but are contextually related.

#### Agent Automatically Using Structured Memory

The ultimate goal is often for the agent to seamlessly use this structured memory in conversation, both by recalling relevant facts and by saving new ones.

*   **File: `cookbook/agent_concepts/memory/06_agent_with_memory.py`**
    *   **Focus:** This example brings it all together. An `Agent` is initialized with `enable_user_memories=True` and a configured `Memory` object. The script demonstrates how the agent can:
        1.  Automatically extract facts from the user's statements during a conversation.
        2.  Store these extracted facts as `UserMemory` entries.
        3.  Automatically retrieve and use relevant stored memories when responding to the user.
    *   **Code Snippet (Illustrative):**
        ```python
        from agno.agent import Agent
        from agno.models.openai import OpenAIChat
        from agno.memory.memory import Memory
        from agno.memory.storage.sqlite import SqliteMemoryDb

        llm = OpenAIChat()
        memory_db = SqliteMemoryDb.from_uri("sqlite:///./agent_user_memories.db")
        memory = Memory(memory_db=memory_db, llm=llm) # LLM can be needed for memory operations

        agent = Agent(
            model=llm,
            instructions="Remember details about me and use them.",
            memory=memory,
            enable_user_memories=True
        )

        # agent.print_response("My cat's name is Whiskers.", stream=True)
        # agent.print_response("What is my cat's name?", stream=True)
        ```
    *   **Run it:** `python cookbook/agent_concepts/memory/06_agent_with_memory.py`
    *   **Observe:** In the conversation, tell the agent a fact (e.g., "My favorite city is Paris."). Later, ask a question related to that fact (e.g., "Where do I like to visit?"). The agent should be able to recall the information. Check the database to see the `UserMemory` entries created by the agent.

### 3.4 Session Summarization - Condensing Conversations

For very long conversations, including the entire raw history can become inefficient or exceed context window limits of the LLM. Session summarization creates condensed summaries of past parts of the conversation to maintain context more efficiently.

*   **Concept:** Periodically, or at the end of a session, the agent (or a dedicated summarizer component) creates a summary of the interaction so far. This summary can then be used as a form of memory for future interactions or to re-establish context.

*   **Key Components:**
    *   `enable_session_summaries=True`: Set in the `Agent` constructor to activate automatic session summarization.
    *   `SessionSummarizer`: A component, often part of the `Memory` system, responsible for generating the summaries. It typically uses an LLM.
    *   Summaries are usually stored in the same database as other memory types (like `UserMemory` or chat history).

#### Basic Agent with Summaries

This demonstrates the fundamental mechanism of enabling and observing session summaries.

*   **File: `cookbook/agent_concepts/memory/08_agent_with_summaries.py`**
    *   **Focus:** Shows how to enable session summaries for an agent. As the conversation progresses, the agent will periodically (or based on certain triggers) generate and store summaries of the interaction.
    *   **Code Snippet (Illustrative):**
        ```python
        from agno.agent import Agent
        from agno.models.openai import OpenAIChat
        from agno.memory.memory import Memory
        from agno.memory.storage.sqlite import SqliteMemoryDb
        # (Assumes llm, memory_db, and memory objects are initialized as before)
        # memory = Memory(memory_db=memory_db, llm=llm) # Summarizer needs an LLM

        llm = OpenAIChat()
        memory_db = SqliteMemoryDb.from_uri("sqlite:///./agent_summary_memories.db")
        memory = Memory(memory_db=memory_db, llm=llm)


        agent = Agent(
            model=llm,
            instructions="Let's have a long chat.",
            memory=memory,
            enable_session_summaries=True
        )

        # agent.print_response("First topic is about AI.", stream=True)
        # ... have a few more turns ...
        # agent.print_response("Now let's talk about cooking.", stream=True)
        # ... have a few more turns ...
        # Summaries should be generated and stored in the memory_db.
        ```
    *   **Run it:** `python cookbook/agent_concepts/memory/08_agent_with_summaries.py`
    *   **Observe:** Have a conversation with multiple turns. Inspect the database used by the `Memory` object. You should find entries corresponding to the generated session summaries. The agent will use these summaries in longer conversations to maintain context.

#### Combining Built-in History with Summaries

This shows how short-term detailed history and long-term condensed summaries can work together.

*   **File: `cookbook/agent_concepts/memory/17_builtin_memory_with_session_summary.py`**
    *   **Focus:** This example illustrates a more sophisticated setup where an agent uses both:
        1.  `add_history_to_messages=True`: For immediate, turn-by-turn conversational context.
        2.  `enable_session_summaries=True`: For longer-term context retention through summaries.
        It also shows how you can customize the `SessionSummarizer` if needed, for example, by providing specific instructions or a different LLM for the summarization task.
    *   **Code Snippet (Illustrative):**
        ```python
        from agno.agent import Agent
        from agno.models.openai import OpenAIChat
        from agno.memory.memory import Memory
        from agno.memory.storage.sqlite import SqliteMemoryDb
        from agno.memory.summarizer import SessionSummarizer
        
        llm = OpenAIChat()
        memory_db = SqliteMemoryDb.from_uri("sqlite:///./agent_builtin_summary_memories.db")
        
        # Optional: Customize the summarizer
        # custom_summarizer_llm = OpenAIChat() # e.g., a specific model for summaries
        # custom_summarizer = SessionSummarizer(llm=custom_summarizer_llm)
        # memory = Memory(memory_db=memory_db, llm=llm, session_summarizer=custom_summarizer)
        memory = Memory(memory_db=memory_db, llm=llm)


        agent = Agent(
            model=llm,
            instructions="We'll discuss many things.",
            memory=memory,
            add_history_to_messages=True, # For recent turns
            num_history_runs=5,
            enable_session_summaries=True  # For long-term context
        )
        # ... interact with the agent using agent.print_response(..., stream=True) ...
        ```
    *   **Run it:** `python cookbook/agent_concepts/memory/17_builtin_memory_with_session_summary.py`
    *   **Observe:** This setup provides a good balance. The agent has access to the verbatim recent conversation (via built-in history) and also leverages summaries for the older parts of the dialogue, ensuring it doesn't lose track even in very long interactions. The example might also show how to access these summaries or customize their generation.

By understanding and utilizing these different forms of memory, you can build agents that are not only responsive but also contextually aware, knowledgeable, and capable of maintaining coherent, long-term interactions.
---
## Part 4: Advanced Concepts - Reasoning and Basic Agent Architectures

As you become more familiar with individual agents, you'll encounter scenarios that require more sophisticated cognitive abilities or collaborative problem-solving. This section delves into how agents can "reason" about tasks and how multiple agents can work together in teams.

### 4.1 Agent Reasoning (Chain-of-Thought)

Standard agents process your input and generate a response. However, for complex queries or tasks, it's often beneficial if the agent can perform intermediate "steps of thought" before arriving at a final answer. This is where Chain-of-Thought (CoT) reasoning comes in.

*   **Concept:** Chain-of-Thought reasoning enables agents to break down a problem into intermediate steps, articulate these steps (as if "thinking aloud"), and then use this internal monologue to produce a more accurate and well-reasoned final response. It mimics human problem-solving where we often follow a sequence of thoughts to tackle a complex question.

*   **Key Components:**
    *   `reasoning=True`: When you initialize an `Agent` with `reasoning=True`, you are activating its ability to use a Chain-of-Thought process. The agent will then internally generate reasoning steps before producing the final output.
    *   `reasoning_model`: Optionally, you can specify a different language model for the reasoning process than the one used for the final response. This allows you to use, for instance, a more powerful (and potentially more expensive) model for the complex reasoning part and a faster/cheaper model for generating the final user-facing answer. If not provided, it defaults to the agent's main `model`.
    *   `show_full_reasoning=True`: When using methods like `agent.print_response()`, setting `show_full_reasoning=True` will make the agent's internal reasoning steps visible in the console output, followed by the final answer. This is invaluable for debugging and understanding how the agent arrived at its conclusion.

*   **Example: `cookbook/reasoning/agents/default_chain_of_thought.py`**
    *   **Focus:** This script particularly showcases how to enable the default Chain-of-Thought reasoning and observe its output. While the script might show multiple agent configurations, we're interested in the one that explicitly enables reasoning.
    *   **Code Snippet (Illustrative - focusing on the reasoning-enabled agent):**
        ```python
        from agno.agent import Agent
        from agno.models.openai import OpenAIChat

        llm = OpenAIChat() # Assumes OPENAI_API_KEY is set in environment

        # Agent with Chain-of-Thought reasoning enabled
        reasoning_agent = Agent(
            model=llm,
            instructions="You are a helpful assistant that thinks step-by-step.",
            reasoning=True
            # Optionally, you could add:
            # reasoning_model=another_llm_instance 
        )

        # When invoking, show the reasoning
        reasoning_agent.print_response(
            "If a train leaves station A at 10 AM traveling at 60 mph, "
            "and station B is 180 miles away, what time will it arrive at station B?",
            show_full_reasoning=True,
            stream=True # Common to stream responses
        )
        ```
    *   **Run it:** `python cookbook/reasoning/agents/default_chain_of_thought.py`
    *   **Observe:** Look for the agent that has `reasoning=True`. When it responds to a query (especially a multi-step one like the train problem), you should see a "Reasoning:" section in the output detailing the intermediate thoughts before the final "Answer:". This might include steps like identifying the speed, distance, calculating time, and then determining the arrival time.

*   **Accessing Reasoning Programmatically:**
    Sometimes, you don't just want to print the reasoning; you might want to capture it in your code for logging, further analysis, or custom display.
    *   If you are **not** streaming the response (e.g., using `response = agent.invoke(...)`), the reasoning content is typically available via `response.reasoning_content`.
    *   If you **are** streaming the response (e.g., using `agent.print_response(..., stream=True)` or iterating through `agent.stream_response(...)`), the reasoning content can usually be accessed from the agent's state after the streaming is complete, often via `agent.run_response.reasoning_content`.
    *   **Example Reference:** The script `cookbook/reasoning/agents/capture_reasoning_content_default_COT.py` demonstrates how to access this `reasoning_content` programmatically. You'll see how the response object (or the agent's run state) holds this information after an invocation.

By enabling reasoning, you empower your agents to tackle more complex problems more robustly and transparently.

### 4.2 Basic Agent Teams (Coordination)

Some problems are too large or multifaceted for a single agent to handle effectively. In such cases, you can form a **Team** of agents, where each agent might have specialized skills or roles, and a coordinating mechanism orchestrates their collaboration.

*   **Concept:** Agent teams involve multiple agents working together towards a common goal. One common pattern is "coordination," where a "leader" or "manager" agent delegates tasks to "member" agents based on their capabilities and the overall objective.

*   **Key Components:**
    *   `Team` class: The primary class for creating and managing a group of agents.
    *   `members`: A list of `Agent` instances that form the team. These are your "worker" agents, each potentially with different instructions, tools, or knowledge.
    *   `mode="coordinate"`: This mode configures the team for a hierarchical coordination strategy. The `Team` object itself (or a designated leader agent within it, depending on the specific implementation details of `Team`) will take on the role of distributing tasks to the appropriate member agents. The `Team`'s own instructions will often guide this coordination.

*   **Example: `cookbook/teams/modes/coordinate.py`**
    *   **Focus:** This script illustrates how to set up a `Team` in `coordinate` mode. It typically defines:
        1.  Multiple specialized agents (e.g., one for research, one for writing, one for summarizing).
        2.  A `Team` instance that includes these agents as `members`.
        3.  Instructions for the `Team` itself, which guide how it should coordinate its members to achieve a user's request.
    *   **Code Snippet (Illustrative):**
        ```python
        from agno.agent import Agent, Team
        from agno.models.openai import OpenAIChat

        llm = OpenAIChat()

        # Define member agents with specialized roles
        researcher_agent = Agent(
            model=llm,
            instructions="You are a research assistant. Find information on the given topic."
            # Potentially with search tools
        )

        writer_agent = Agent(
            model=llm,
            instructions="You are a content writer. Write a blog post based on the provided information."
        )

        # Create the Team
        coordinator_team = Team(
            model=llm, # The team itself might use an LLM for coordination logic
            members=[researcher_agent, writer_agent],
            mode="coordinate",
            instructions="""
            Coordinate the team to write a blog post.
            1. Use the researcher_agent to gather information.
            2. Use the writer_agent to write the blog post using the gathered information.
            Ensure the final output is a complete blog post.
            """
        )

        # Invoke the team to perform the task
        # The team will internally delegate to researcher_agent then writer_agent
        # The cookbook example uses print_response for teams as well.
        coordinator_team.print_response(
            "Write a blog post about the benefits of remote work.",
            stream=True
        )
        ```
    *   **Run it:** `python cookbook/teams/modes/coordinate.py`
    *   **Observe:** When you run the script with a request (like writing a blog post), you should see (if `show_tool_calls` or similar logging is enabled for the team/members) how the team first likely invokes the `researcher_agent` and then passes its output to the `writer_agent`. The final result is the product of this coordinated effort. The `Team`'s instructions are crucial for defining this workflow.

Agent teams allow you to build more sophisticated applications by composing the strengths of multiple specialized agents, enabling a divide-and-conquer approach to complex tasks. The `coordinate` mode is a foundational pattern for achieving this kind of multi-agent collaboration.
---
## Part 5: Exploring Further

The `agno` library and its cookbook are rich with advanced features and examples that go beyond the fundamentals covered in this "in a day" guide. Once you're comfortable with the basics, here are excellent starting points for deeper exploration:

*   **Different Models: `cookbook/models/`**
    *   The library supports a wide array of language models beyond OpenAI. Explore how to integrate and use models from providers like Anthropic (Claude), Google (Gemini), open-source options via HuggingFace Transformers, or even locally run models with Ollama. This allows you to choose the LLM that best fits your budget, performance needs, or privacy requirements.

*   **Advanced Tool Concepts: `cookbook/agent_concepts/tool_concepts/custom_tools/`**
    *   Beyond basic custom tools, discover more sophisticated features. `async_tool_decorator.py` shows how to define tools that can run asynchronously, crucial for I/O-bound tasks. Learn about tool hooks (for actions before/after tool execution) and how to implement retries for tools that might fail intermittently.

*   **More on Knowledge Bases: `cookbook/agent_concepts/knowledge/`**
    *   Delve deeper into Retrieval Augmented Generation (RAG). Explore examples using different vector database solutions (beyond LanceDB), various text chunking strategies to optimize retrieval, and how to ingest diverse document types (e.g., Markdown, HTML) into your knowledge bases.

*   **More on Memory: `cookbook/agent_concepts/memory/`**
    *   Explore advanced memory configurations. `09_agents_share_memory.py` demonstrates how multiple agents can access and contribute to a shared memory store, enabling collaborative recall. `10_custom_memory.py` provides insights into creating entirely new types of memory systems if the built-in options don't fit your specific needs.

*   **Agentic Search/RAG: `cookbook/agent_concepts/agentic_search/` and `cookbook/agent_concepts/rag/`**
    *   These sections offer more focused examples on building sophisticated search and retrieval systems powered by agents. Understand how an agent can intelligently query knowledge bases, refine search results, and synthesize information for the user.

*   **Multimodal Agents: `cookbook/agent_concepts/multimodal/`**
    *   Step into the world of agents that can process and understand more than just text. These examples showcase how to build agents that can work with images (e.g., describing an image, answering questions about it) and potentially audio, opening up new interaction paradigms.

*   **Full Applications: `cookbook/apps/` and `cookbook/examples/`**
    *   See how all the pieces come together! These directories often contain more complete, albeit still example-scale, applications. They can provide inspiration and practical patterns for building your own end-to-end agentic solutions, such as simple chatbots, research assistants, or data processing pipelines.

---

## Learning in a Day - Strategy

To make the most of your day and truly grasp the core concepts, consider this approach:

*   **Focus on Parts 1, 2, and 3 First:** These parts – "Understanding the Basics," "Giving Your Agent Tools," and "Giving Your Agent Memory" – cover the absolute essentials. A solid understanding here will make everything else much easier. Don't rush through them.
*   **Run Every Example (from Parts 1-4):** The hands-on component is key. If you have the time, try typing out parts of the examples yourself rather than just copy-pasting. At a minimum, read each script carefully before running it, predict what it will do, and then verify.
*   **Tinker and Experiment:** This is where deep learning happens.
    *   Change agent instructions: Make your agent a pirate, a poet, or a five-year-old.
    *   Modify tool behavior: If a tool searches the web, try to make it search for something specific or use its parameters differently.
    *   Alter prompts: See how different phrasing in your input to the agent changes its response or its decision to use a tool.
    *   Observe the impact of these changes. What breaks? What improves? Why?
*   **Don't Get Bogged Down in Part 5 Initially:** Part 4 ("Advanced Concepts") gives you a taste of reasoning and teams, which are powerful. However, ensure your fundamentals from Parts 1-3 are strong before diving too deep into the further explorations suggested in Part 5. Part 5 is for after you've built a solid foundation.
*   **Understand the "How":** The goal isn't just to run code, but to understand *how* these components interact:
    *   How is an `Agent` defined and initialized?
    *   How is a `Model` (like `OpenAIChat`) passed to an Agent?
    *   How are `Tools` (both pre-built and custom) defined and made available to an Agent?
    *   How does an Agent use `Knowledge` bases for RAG?
    *   How is `Memory` (chat history, structured facts, summaries) configured and used?
    *   What role does `Storage` play in persisting information?
    *   How is a `Team` of agents structured and coordinated?

By actively engaging with the examples and focusing on these core interactions, you'll build a strong and practical understanding of `agno`.

---

**Happy Building!**

You've now covered the foundational concepts of building AI agents with `agno`. The journey into agentic AI is vast and continually evolving, but with the knowledge and hands-on experience gained from this guide, you're well-equipped to start creating your own intelligent applications. Continue to explore the `cookbook`, join community discussions, and don't hesitate to experiment with new ideas. The power of AI agents is at your fingertips. We're excited to see what you build!
---
