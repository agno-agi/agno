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
        from superagent import Agent
        from superagent.models import OpenAIChat

        llm = OpenAIChat() # Assuming you have OPENAI_API_KEY set

        # Agent with Chain-of-Thought reasoning enabled
        reasoning_agent = Agent(
            model=llm,
            instructions="You are a helpful assistant that thinks step-by-step.",
            reasoning=True
            # Optionally, you could add:
            # reasoning_model=another_llm_instance 
        )

        # When invoking, show the reasoning
        # The actual method in the script might be agent.chat() or agent.invoke()
        # followed by printing logic. For print_response, it's direct:
        reasoning_agent.print_response(
            "If a train leaves station A at 10 AM traveling at 60 mph, "
            "and station B is 180 miles away, what time will it arrive at station B?",
            show_full_reasoning=True
        )
        ```
    *   **Run it:** `python cookbook/reasoning/agents/default_chain_of_thought.py`
    *   **Observe:** Look for the agent that has `reasoning=True`. When it responds to a query (especially a multi-step one like the train problem), you should see a "Reasoning:" section in the output detailing the intermediate thoughts before the final "Answer:". This might include steps like identifying the speed, distance, calculating time, and then determining the arrival time.

*   **Accessing Reasoning Programmatically:**
    Sometimes, you don't just want to print the reasoning; you might want to capture it in your code for logging, further analysis, or custom display.
    *   If you are **not** streaming the response (e.g., using `response = agent.invoke(...)`), the reasoning content is typically available via `response.reasoning_content`.
    *   If you **are** streaming the response (e.g., using `agent.print_response(..., stream_handler=...)` or iterating through `agent.stream_response(...)`), the reasoning content can usually be accessed from the agent's state after the streaming is complete, often via `agent.run_response.reasoning_content`.
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
        from superagent import Agent, Team
        from superagent.models import OpenAIChat

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
        final_output = coordinator_team.invoke(
            "Write a blog post about the benefits of remote work."
        )
        print(final_output)
        ```
    *   **Run it:** `python cookbook/teams/modes/coordinate.py`
    *   **Observe:** When you run the script with a request (like writing a blog post), you should see (if `show_tool_calls` or similar logging is enabled for the team/members) how the team first likely invokes the `researcher_agent` and then passes its output to the `writer_agent`. The final result is the product of this coordinated effort. The `Team`'s instructions are crucial for defining this workflow.

Agent teams allow you to build more sophisticated applications by composing the strengths of multiple specialized agents, enabling a divide-and-conquer approach to complex tasks. The `coordinate` mode is a foundational pattern for achieving this kind of multi-agent collaboration.
---
