## Part 3: Giving Your Agent Memory - Context and Learning

Memory is a crucial aspect of intelligent agents, allowing them to recall past interactions, utilize vast amounts of external knowledge, and maintain context over extended conversations. This capability transforms an agent from a simple command-processor into a more adaptive and knowledgeable conversational partner. In `superagent`, memory can take several forms, each serving a distinct purpose.

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
        from superagent import Agent
        from superagent.models import OpenAIChat

        llm = OpenAIChat()
        agent = Agent(
            model=llm,
            instructions="Remember what I say.",
            add_history_to_messages=True,
            num_history_runs=3 # Remembers the last 3 exchanges
        )

        response1 = agent.invoke("My name is Bob.")
        print(f"Agent: {response1}")

        response2 = agent.invoke("What is my name?") # Agent should remember "Bob"
        print(f"Agent: {response2}")
        ```
    *   **Run it:** `python cookbook/agent_concepts/memory/00_builtin_memory.py`
    *   **Observe:** Notice how the agent can answer questions based on information you provided in earlier turns of the same session. Experiment by changing `num_history_runs`.

#### Persistent Chat Sessions

While built-in history is good for a single session, persistent chat sessions allow conversation history to be stored and retrieved across multiple runs or different instances of your application. This is essential for users who expect the agent to remember them over time.

*   **Key Components:**
    *   `storage`: This parameter in the `Agent` constructor takes a storage backend object. `superagent` supports various storage options, with `SqliteStorage` being a common file-based choice for simplicity.
    *   `user_id`: A unique identifier for the user interacting with the agent.
    *   `session_id`: A unique identifier for a specific conversation session. A single user can have multiple sessions.
    *   `read_chat_history=True`: When initializing the `Agent`, this tells it to load existing chat history for the given `user_id` and `session_id` from the configured `storage`.

*   **Example: `cookbook/getting_started/04_agent_with_storage.py`**
    *   **Focus:** This script shows how to set up an agent with `SqliteStorage` to persist chat history. It demonstrates initializing the agent with a `user_id` and `session_id`, allowing it to pick up the conversation where it left off, even if the script is run multiple times.
    *   **Code Snippet (Illustrative):**
        ```python
        from superagent import Agent
        from superagent.models import OpenAIChat
        from superagent.storage.sqlite import SqliteStorage

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
        # agent.print_response("My favorite color is blue.")
        # Second run:
        # agent.print_response("What is my favorite color?")
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
        from superagent import Agent
        from superagent.models import OpenAIChat
        from superagent.knowledge import PDFUrlKnowledgeBase
        from superagent.vector_store.lancedb import LanceDb # Or other VectorDB
        from superagent.embeddings.openai import OpenAIEmbeddings # Or other embedder

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
        # This might be pdf_knowledge.load() or pdf_knowledge.load_and_embed()
        # depending on the library version and specific setup.
        # Check the example script for the exact method.
        # This step can take time as it processes the PDF.
        pdf_knowledge.load(recreate=False) # recreate=True if PDF changed

        llm = OpenAIChat()
        agent = Agent(
            model=llm,
            instructions="Answer questions based on the provided document.",
            knowledge=[pdf_knowledge]
        )

        # agent.print_response("What is the main topic of the document?")
        ```
    *   **Run it:** `python cookbook/getting_started/03_agent_with_knowledge.py`
    *   **Observe:** The first time you run it, the `load()` process might take a while as it downloads and processes the PDF. Subsequent runs should be faster if `recreate=False` (or similar logic) is used. Ask questions that can only be answered by referring to the PDF content. Notice how the agent's answers are grounded in the provided document.

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
        from superagent.memory.memory import Memory
        from superagent.memory.models import UserMemory
        from superagent.memory.storage.sqlite import SqliteMemoryDb

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
        from superagent import Agent
        from superagent.models import OpenAIChat
        from superagent.memory.memory import Memory
        from superagent.memory.storage.sqlite import SqliteMemoryDb

        llm = OpenAIChat()
        memory_db = SqliteMemoryDb.from_uri("sqlite:///./agent_user_memories.db")
        memory = Memory(memory_db=memory_db, llm=llm) # LLM can be needed for memory operations

        agent = Agent(
            model=llm,
            instructions="Remember details about me and use them.",
            memory=memory,
            enable_user_memories=True
        )

        # agent.print_response("My cat's name is Whiskers.")
        # agent.print_response("What is my cat's name?")
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
        # (Assumes llm, memory_db, and memory objects are initialized as before)
        # memory = Memory(memory_db=memory_db, llm=llm) # Summarizer needs an LLM

        agent = Agent(
            model=llm,
            instructions="Let's have a long chat.",
            memory=memory,
            enable_session_summaries=True
        )

        # agent.print_response("First topic is about AI.")
        # ... have a few more turns ...
        # agent.print_response("Now let's talk about cooking.")
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
        from superagent.memory.summarizer import SessionSummarizer
        # (Assumes llm, memory_db, and memory objects are initialized)

        # Optional: Customize the summarizer
        # custom_summarizer_llm = OpenAIChat(model_name="gpt-3.5-turbo") # e.g., a cheaper model for summaries
        # custom_summarizer = SessionSummarizer(llm=custom_summarizer_llm)
        # memory = Memory(memory_db=memory_db, llm=llm, session_summarizer=custom_summarizer)


        agent = Agent(
            model=llm,
            instructions="We'll discuss many things.",
            memory=memory,
            add_history_to_messages=True, # For recent turns
            num_history_runs=5,
            enable_session_summaries=True  # For long-term context
        )
        # ... interact with the agent ...
        ```
    *   **Run it:** `python cookbook/agent_concepts/memory/17_builtin_memory_with_session_summary.py`
    *   **Observe:** This setup provides a good balance. The agent has access to the verbatim recent conversation (via built-in history) and also leverages summaries for the older parts of the dialogue, ensuring it doesn't lose track even in very long interactions. The example might also show how to access these summaries or customize their generation.

By understanding and utilizing these different forms of memory, you can build agents that are not only responsive but also contextually aware, knowledgeable, and capable of maintaining coherent, long-term interactions.
---
