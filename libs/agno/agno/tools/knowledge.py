import json
from textwrap import dedent
from typing import Any, List, Optional, Union

from agno.agent import Agent
from agno.document import Document
from agno.knowledge.agent import AgentKnowledge
from agno.team.team import Team
from agno.tools import Toolkit
from agno.utils.log import log_debug, logger


class KnowledgeTools(Toolkit):
    def __init__(
        self,
        knowledge: AgentKnowledge,
        think: bool = True,
        search: bool = True,
        analyze: bool = True,
        instructions: Optional[str] = None,
        add_instructions: bool = True,
        add_few_shot: bool = False,
        few_shot_examples: Optional[str] = None,
        **kwargs,
    ):
        if knowledge is None:
            raise ValueError("knowledge must be provided when using KnowledgeTools")

        # Add instructions for using this toolkit
        if instructions is None:
            self.instructions = self.DEFAULT_INSTRUCTIONS
            if add_few_shot:
                if few_shot_examples is not None:
                    self.instructions += "\n" + few_shot_examples
                else:
                    self.instructions += "\n" + self.FEW_SHOT_EXAMPLES
        else:
            self.instructions = instructions

        # The knowledge to search
        self.knowledge: AgentKnowledge = knowledge

        tools: List[Any] = []
        if think:
            tools.append(self.think)
        if search:
            tools.append(self.search)
        if analyze:
            tools.append(self.analyze)

        super().__init__(
            name="knowledge_tools",
            instructions=self.instructions,
            add_instructions=add_instructions,
            tools=tools,
            **kwargs,
        )

    def think(self, agent: Union[Agent, Team], thought: str) -> str:
        """Use this tool as a scratchpad to reason about the question, refine your approach, brainstorm search terms, or revise your plan.

        Call `Think` whenever you need to figure out what to do next, analyze the user's question, or plan your approach.
        You should use this tool as frequently as needed.

        Args:
            thought: Your thought process and reasoning.

        Returns:
            str: The full log of reasoning and the new thought.
        """
        try:
            log_debug(f"Thought: {thought}")

            # Add the thought to the Agent state
            if agent.session_state is None:
                agent.session_state = {}
            if "thoughts" not in agent.session_state:
                agent.session_state["thoughts"] = []
            agent.session_state["thoughts"].append(thought)

            # Return the full log of thoughts and the new thought
            thoughts = "\n".join([f"- {t}" for t in agent.session_state["thoughts"]])
            formatted_thoughts = dedent(
                f"""Thoughts:
                {thoughts}
                """
            ).strip()
            return formatted_thoughts
        except Exception as e:
            logger.error(f"Error recording thought: {e}")
            return f"Error recording thought: {e}"

    def search(self, agent: Union[Agent, Team], query: str) -> str:
        """Use this tool to search the knowledge base for relevant information.
        After thinking through the question, use this tool as many times as needed to search for relevant information.

        Args:
            query: The query to search the knowledge base for.

        Returns:
            str: A string containing the response from the knowledge base.
        """
        try:
            log_debug(f"Searching knowledge base: {query}")

            # Get the relevant documents from the knowledge base
            relevant_docs: List[Document] = self.knowledge.search(query=query)
            if len(relevant_docs) == 0:
                return "No documents found"
            return json.dumps([doc.to_dict() for doc in relevant_docs])
        except Exception as e:
            logger.error(f"Error searching knowledge base: {e}")
            return f"Error searching knowledge base: {e}"

    def analyze(self, agent: Union[Agent, Team], analysis: str) -> str:
        """Use this tool to evaluate whether the returned documents are correct and sufficient.
        If not, go back to "Think" or "Search" with refined queries.

        Args:
            analysis: A thought to think about and log.

        Returns:
            str: The full log of thoughts and the new thought.
        """
        try:
            log_debug(f"Analysis: {analysis}")

            # Add the thought to the Agent state
            if agent.session_state is None:
                agent.session_state = {}
            if "analysis" not in agent.session_state:
                agent.session_state["analysis"] = []
            agent.session_state["analysis"].append(analysis)

            # Return the full log of thoughts and the new thought
            analysis = "\n".join([f"- {a}" for a in agent.session_state["analysis"]])
            formatted_analysis = dedent(
                f"""Analysis:
                {analysis}
                """
            ).strip()
            return formatted_analysis
        except Exception as e:
            logger.error(f"Error recording analysis: {e}")
            return f"Error recording analysis: {e}"

    DEFAULT_INSTRUCTIONS = dedent("""\
        You have access to the Think, Search, and Analyze tools that will help you search your knowledge for relevant information. Use these tools as frequently as needed to find the most relevant information.

        ## How to use the Think, Search, and Analyze tools:
        1. **Think**
        - Purpose: A scratchpad for planning, brainstorming keywords, and refining your approach. You never reveal your "Think" content to the user.
        - Usage: Call `think` whenever you need to figure out what to do next, analyze your approach, or decide new search terms before (or after) you look up documents.

        2. **Search**
        - Purpose: Executes a query against the knowledge base.
        - Usage: Call `search` with a clear query string whenever you want to retrieve documents or data. You can and should call this tool multiple times in one conversation.
            - For complex topics, use multiple focused searches rather than one broad search
            - Try different phrasing and keywords if initial searches don't yield useful results
            - Use quotes for exact phrases and OR for alternative terms (e.g., "protein synthesis" OR "protein formation")

        3. **Analyze**
        - Purpose: Evaluate whether the returned documents are correct and sufficient. If not, go back to "Think" or "Search" with refined queries.
        - Usage: Call `analyze` after getting search results to verify the quality and correctness of that information. Consider:
            - Relevance: Do the documents directly address the user's question?
            - Completeness: Is there enough information to provide a thorough answer?
            - Reliability: Are the sources credible and up-to-date?
            - Consistency: Do the documents agree or contradict each other?

        **Important Guidelines**:
        - Do not include your internal chain-of-thought in direct user responses.
        - Use "Think" to reason internally. These notes are never exposed to the user.
        - Iterate through the cycle (Think → Search → Analyze) as many times as needed until you have a final answer.
        - When you do provide a final answer to the user, be clear, concise, and accurate.
        - If search results are sparse or contradictory, acknowledge limitations in your response.
        - Synthesize information from multiple sources rather than relying on a single document.\
    """)

    FEW_SHOT_EXAMPLES = dedent("""\
        You can refer to the examples below as guidance for how to use each tool.
        ### Examples

        #### Example 1: Multiple Searches and Analysis

        User: What are the recommended dietary guidelines for someone with mild hypertension?
        Think: The user is asking about dietary guidelines for mild hypertension. I'll start broad, then refine if needed.
        Search: "dietary guidelines for mild hypertension", "salt intake recommendations for mild hypertension"
        Analyze: I got one document referencing the DASH diet, but it's quite brief. I might need more info about salt intake recommendations specifically.
        Think: Let me refine my search to see if there are official guidelines from recognized health organizations.
        Search: "WHO or American Heart Association guidelines for hypertension", "fruits and vegetables for mild hypertension"
        Analyze: The new documents mention daily sodium limits, recommended fruit/vegetable intake, and more. This seems thorough. I'm ready to formulate the answer.

        Final Answer: For mild hypertension, the guidelines typically recommend following the DASH diet, which emphasizes ...

        #### Example 2: Invalid or Insufficient Search Results

        User: Do you have any documentation on the 'XYZ Project' from last year?
        Think: I'll try searching for 'XYZ Project last year' but if that fails, I'll look for internal code names or older references.
        Search: "XYZ Project last year"
        Analyze: No relevant documents. Let me refine my search to check for 'XYZ Project' in different date ranges or alternate titles.
        Think: Possibly it's under 'XYZ Initiative' or 'XYZ Rollout.' Let's do a second search.
        Search: "XYZ Initiative OR 'XYZ Rollout' from last year"
        Analyze: Found a relevant archive for 'XYZ Initiative'. Looks correct and references last year's timeline. I'll proceed with that info.

        Final Answer: Yes, we have some archived documentation under the name 'XYZ Initiative.' It includes ...

        #### Example 3: Synthesizing Complex Information

        User: How do quantum computers differ from classical computers in terms of performance?
        Think: This is a technical question requiring clear explanations of quantum vs. classical computing performance characteristics.
        Search: "quantum computing performance vs classical computing"
        Analyze: Found general information but need more specifics on actual performance metrics and use cases.
        Think: Let me search for specific quantum advantages and limitations.
        Search: "quantum supremacy examples", "quantum computing limitations"
        Search: "quantum computing speedup for specific algorithms"
        Analyze: Now I have concrete examples of quantum speedup for certain algorithms, limitations for others, and real-world benchmarks.

        Final Answer: Quantum computers differ from classical computers in three key ways: [synthesized explanation with specific examples]...\
    """)
