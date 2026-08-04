import json
from inspect import isawaitable, iscoroutinefunction, signature
from textwrap import dedent
from typing import Any, Callable, Dict, List, Optional, Union

from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.run import RunContext
from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error


class KnowledgeTools(Toolkit):
    def __init__(
        self,
        knowledge: Optional[Knowledge] = None,
        knowledge_retriever: Optional[Callable[..., Optional[List[Union[Dict[str, Any], str]]]]] = None,
        enable_think: bool = True,
        enable_search: bool = True,
        enable_analyze: bool = True,
        instructions: Optional[str] = None,
        add_instructions: bool = True,
        add_few_shot: bool = False,
        few_shot_examples: Optional[str] = None,
        all: bool = False,
        **kwargs,
    ):
        if knowledge is None and knowledge_retriever is None:
            raise ValueError("Either knowledge or knowledge_retriever must be provided when using KnowledgeTools")

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

        # The knowledge to search (optional when a custom retriever is provided)
        self.knowledge: Optional[Knowledge] = knowledge
        # Optional custom retriever with the same callable contract as Agent.knowledge_retriever
        self.knowledge_retriever = knowledge_retriever

        tools: List[Any] = []
        async_tools: List[Any] = []
        if enable_think or all:
            tools.append(self.think)
        if enable_search or all:
            tools.append(self.search_knowledge)
            async_tools.append((self.asearch_knowledge, "search_knowledge"))
        if enable_analyze or all:
            tools.append(self.analyze)

        super().__init__(
            name="knowledge_tools",
            tools=tools,
            async_tools=async_tools,
            instructions=self.instructions,
            add_instructions=add_instructions,
            **kwargs,
        )

    def think(self, run_context: RunContext, thought: str) -> str:
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
            session_state = run_context.session_state
            if session_state is None:
                session_state = {}
                run_context.session_state = session_state
            if "thoughts" not in session_state:
                session_state["thoughts"] = []
            session_state["thoughts"].append(thought)

            # Return the full log of thoughts and the new thought
            thoughts = "\n".join([f"- {t}" for t in session_state["thoughts"]])
            formatted_thoughts = dedent(
                f"""Thoughts:
                {thoughts}
                """
            ).strip()
            return formatted_thoughts
        except Exception as e:
            log_error(f"Error recording thought: {str(e)}")
            return f"Error recording thought: {e}"

    def _num_documents(self) -> Optional[int]:
        if self.knowledge is None:
            return None
        return getattr(self.knowledge, "max_results", None)

    def _build_retriever_kwargs(
        self,
        query: str,
        run_context: RunContext,
        filters: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Build kwargs for a custom retriever using the same contract as Agentic RAG."""
        assert self.knowledge_retriever is not None
        dependencies = run_context.dependencies if run_context else None
        sig = signature(self.knowledge_retriever)
        knowledge_retriever_kwargs: Dict[str, Any] = {}
        if "filters" in sig.parameters:
            knowledge_retriever_kwargs["filters"] = filters
        if "run_context" in sig.parameters:
            knowledge_retriever_kwargs["run_context"] = run_context
        elif "dependencies" in sig.parameters:
            knowledge_retriever_kwargs["dependencies"] = dependencies
        knowledge_retriever_kwargs.update({"query": query, "num_documents": self._num_documents()})
        return knowledge_retriever_kwargs

    def _format_docs(self, docs: Optional[List[Any]]) -> str:
        if not docs:
            return "No documents found"

        serialized: List[Any] = []
        for doc in docs:
            if isinstance(doc, Document):
                serialized.append(doc.to_dict())
            else:
                serialized.append(doc)
        return json.dumps(serialized, indent=2, default=str, ensure_ascii=False)

    def search_knowledge(self, run_context: RunContext, query: str) -> str:
        """Use this tool to search the knowledge base for relevant information.
        After thinking through the question, use this tool as many times as needed to search for relevant information.

        Args:
            query: The query to search the knowledge base for.

        Returns:
            str: A string containing the response from the knowledge base.
        """
        try:
            log_debug(f"Searching knowledge base: {query}")

            if self.knowledge_retriever is not None and callable(self.knowledge_retriever):
                if iscoroutinefunction(self.knowledge_retriever):
                    return (
                        "Error searching knowledge base: knowledge_retriever is async; "
                        "use agent.arun() / agent.aprint_response() so the async search_knowledge path runs."
                    )
                docs = self.knowledge_retriever(**self._build_retriever_kwargs(query=query, run_context=run_context))
                return self._format_docs(docs)

            if self.knowledge is None:
                return "Error searching knowledge base: no knowledge or knowledge_retriever configured"

            relevant_docs: List[Document] = self.knowledge.search(query=query)
            return self._format_docs(relevant_docs)
        except Exception as e:
            log_error(f"Error searching knowledge base: {str(e)}")
            return f"Error searching knowledge base: {e}"

    async def asearch_knowledge(self, run_context: RunContext, query: str) -> str:
        """Async variant of search_knowledge. Supports async custom retrievers.

        Args:
            query: The query to search the knowledge base for.

        Returns:
            str: A string containing the response from the knowledge base.
        """
        try:
            log_debug(f"Searching knowledge base asynchronously: {query}")

            if self.knowledge_retriever is not None and callable(self.knowledge_retriever):
                docs = self.knowledge_retriever(**self._build_retriever_kwargs(query=query, run_context=run_context))
                if isawaitable(docs):
                    docs = await docs
                return self._format_docs(docs)

            if self.knowledge is None:
                return "Error searching knowledge base: no knowledge or knowledge_retriever configured"

            aretrieve_fn = getattr(self.knowledge, "aretrieve", None)
            if callable(aretrieve_fn):
                num_documents = self._num_documents() or getattr(self.knowledge, "max_results", 10)
                relevant_docs = await aretrieve_fn(query=query, max_results=num_documents)
                return self._format_docs(relevant_docs)

            asearch_fn = getattr(self.knowledge, "asearch", None)
            if callable(asearch_fn):
                relevant_docs = await asearch_fn(query=query)
                return self._format_docs(relevant_docs)

            relevant_docs = self.knowledge.search(query=query)
            return self._format_docs(relevant_docs)
        except Exception as e:
            log_error(f"Error searching knowledge base: {str(e)}")
            return f"Error searching knowledge base: {e}"

    def analyze(self, run_context: RunContext, analysis: str) -> str:
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
            session_state = run_context.session_state
            if session_state is None:
                session_state = {}
                run_context.session_state = session_state
            if "analysis" not in session_state:
                session_state["analysis"] = []
            session_state["analysis"].append(analysis)

            # Return the full log of thoughts and the new thought
            analysis = "\n".join([f"- {a}" for a in session_state["analysis"]])
            formatted_analysis = dedent(
                f"""Analysis:
                {analysis}
                """
            ).strip()
            return formatted_analysis
        except Exception as e:
            log_error(f"Error recording analysis: {str(e)}")
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
