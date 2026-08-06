import asyncio
import json
import unicodedata
from _thread import LockType
from contextlib import asynccontextmanager
from copy import copy
from io import BytesIO
from textwrap import dedent
from threading import Lock
from typing import Any, AsyncIterator, List, Optional, Tuple
from weakref import WeakValueDictionary

from agno.agent.agent import Agent
from agno.fs._paths import normalize_namespace, normalize_template_value, parse_namespace_template
from agno.fs.errors import InvalidPathError
from agno.knowledge.content import Content, ContentStatus, FileData
from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.run import RunContext
from agno.team.team import Team
from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error
from agno.utils.string import generate_id

DEFAULT_MAX_CONTENT_BYTES = 1_000_000
DEFAULT_MAX_NAMESPACE_BYTES = 20_000_000
MAX_NAME_BYTES = 255


class KnowledgeTools(Toolkit):
    def __init__(
        self,
        knowledge: Knowledge,
        enable_think: bool = True,
        enable_search: bool = True,
        enable_analyze: bool = True,
        instructions: Optional[str] = None,
        add_instructions: bool = True,
        add_few_shot: bool = False,
        few_shot_examples: Optional[str] = None,
        all: bool = False,
        *,
        namespace: Optional[str] = None,
        enable_add: bool = False,
        max_content_bytes: int = DEFAULT_MAX_CONTENT_BYTES,
        max_namespace_bytes: int = DEFAULT_MAX_NAMESPACE_BYTES,
        **kwargs,
    ):
        if knowledge is None:
            raise ValueError("knowledge must be provided when using KnowledgeTools")
        if max_content_bytes <= 0:
            raise ValueError("max_content_bytes must be greater than zero")
        if max_namespace_bytes <= 0:
            raise ValueError("max_namespace_bytes must be greater than zero")
        if max_content_bytes > max_namespace_bytes:
            raise ValueError("max_content_bytes cannot exceed max_namespace_bytes")
        if enable_add and knowledge.contents_db is None:
            raise ValueError("knowledge.contents_db must be provided when enable_add=True")

        self.namespace = normalize_namespace(namespace) if namespace is not None else None
        self.template_placeholders: Tuple[str, ...] = (
            parse_namespace_template(self.namespace) if self.namespace is not None else ()
        )
        if enable_add and self.namespace is None:
            raise ValueError("enable_add=True requires an agent namespace")
        if self.namespace is not None and self.template_placeholders != ("agent_id",):
            raise ValueError("namespace must contain exactly one {agent_id} placeholder")
        if self.namespace is not None and not getattr(knowledge.vector_db, "supports_namespaced_knowledge", False):
            raise ValueError(
                "namespace requires a vector database that supports namespaced knowledge; "
                "PgVector is currently supported"
            )
        self.max_content_bytes = max_content_bytes
        self.max_namespace_bytes = max_namespace_bytes
        self.enable_add = enable_add
        self._write_locks: WeakValueDictionary[str, LockType] = WeakValueDictionary()
        self._write_locks_guard = Lock()

        # Add instructions for using this toolkit
        if instructions is None:
            self.instructions = self.DEFAULT_INSTRUCTIONS
            if add_few_shot:
                if few_shot_examples is not None:
                    self.instructions += "\n" + few_shot_examples
                else:
                    self.instructions += "\n" + self.FEW_SHOT_EXAMPLES
            if enable_add:
                self.instructions += "\n" + self.ADD_INSTRUCTIONS
        else:
            self.instructions = instructions

        # The knowledge to search
        self.knowledge: Knowledge = knowledge

        tools: List[Any] = []
        if enable_think or all:
            tools.append(self.think)
        if enable_search or all:
            tools.append(self.search_knowledge)
        if enable_analyze or all:
            tools.append(self.analyze)
        if enable_add:
            tools.append(self.add_text_to_knowledge)

        async_tools: List[tuple[Any, str]] = list(kwargs.pop("async_tools", None) or [])
        # Preserve the existing static KnowledgeTools execution path when the
        # namespace feature is not enabled.
        if self.namespace is not None and (enable_search or all):
            async_tools.append((self.asearch_knowledge, "search_knowledge"))
        if enable_add:
            async_tools.append((self.aadd_text_to_knowledge, "add_text_to_knowledge"))

        super().__init__(
            name=kwargs.pop("name", "knowledge_tools"),
            tools=tools,
            async_tools=async_tools,
            instructions=self.instructions,
            add_instructions=add_instructions,
            **kwargs,
        )

    def _resolve_namespace(
        self,
        run_context: Optional[RunContext],
        agent: Optional[Agent],
        team: Optional[Team],
    ) -> Optional[str]:
        """Resolve the configured namespace from framework-injected context."""
        if self.namespace is None:
            return None

        values = {
            "user_id": getattr(run_context, "user_id", None) if run_context is not None else None,
            "agent_id": getattr(agent, "id", None) if agent is not None else None,
            "team_id": getattr(team, "id", None) if team is not None else None,
        }
        resolved = self.namespace
        for placeholder in set(self.template_placeholders):
            value = values.get(placeholder)
            if value is None:
                raise InvalidPathError(
                    f"this agent's knowledge requires {placeholder} for this run and none was provided."
                )
            resolved = resolved.replace(
                "{" + placeholder + "}",
                normalize_template_value(placeholder, value),
            )
        return normalize_namespace(resolved)

    def _resolved(
        self,
        run_context: Optional[RunContext],
        agent: Optional[Agent],
        team: Optional[Team],
    ) -> Knowledge:
        """Return an isolated per-call Knowledge view without mutating the template."""
        namespace = self._resolve_namespace(run_context, agent, team)
        if namespace is None:
            return self.knowledge
        knowledge = copy(self.knowledge)
        knowledge.name = namespace
        knowledge.isolate_vector_search = True
        knowledge._enforce_content_isolation = True
        return knowledge

    def _get_write_lock(self, namespace: str) -> LockType:
        with self._write_locks_guard:
            lock = self._write_locks.get(namespace)
            if lock is None:
                lock = Lock()
                self._write_locks[namespace] = lock
            return lock

    @asynccontextmanager
    async def _acquire_async_write_lock(self, namespace: str) -> AsyncIterator[None]:
        """Acquire the same namespace lock used by synchronous writers."""
        lock = self._get_write_lock(namespace)
        while not lock.acquire(blocking=False):
            await asyncio.sleep(0.01)
        try:
            yield
        finally:
            lock.release()

    @staticmethod
    def _text_content_hash(knowledge: Knowledge, name: str, text_content: str, size_bytes: int) -> str:
        content = Content(
            name=name,
            file_data=FileData(content=text_content, type="Text", size=size_bytes),
        )
        return knowledge._build_content_hash(content)

    @staticmethod
    def _text_content_id(knowledge: Knowledge, name: str, text_content: str, size_bytes: int) -> str:
        return generate_id(KnowledgeTools._text_content_hash(knowledge, name, text_content, size_bytes))

    def _check_content_size(self, text_content: str) -> int:
        size_bytes = len(text_content.encode("utf-8"))
        if size_bytes > self.max_content_bytes:
            raise ValueError(
                f"content is {size_bytes} bytes (limit {self.max_content_bytes} bytes per item). "
                "Split it into smaller items and retry."
            )
        return size_bytes

    @staticmethod
    def _check_name(name: str) -> None:
        if not name.strip():
            raise ValueError("name must not be empty")
        if any(unicodedata.category(character) == "Cc" for character in name):
            raise ValueError("name must not contain control characters")
        size_bytes = len(name.encode("utf-8"))
        if size_bytes > MAX_NAME_BYTES:
            raise ValueError(f"name is {size_bytes} bytes (limit {MAX_NAME_BYTES} bytes)")

    @staticmethod
    def _expected_text_documents(knowledge: Knowledge, name: str, text_content: str) -> int:
        reader = knowledge._select_reader("Text")
        documents = reader.read(BytesIO(text_content.encode("utf-8")), name=name)
        if not documents:
            raise RuntimeError("knowledge text could not be read")
        return len(documents)

    def _check_namespace_quota(
        self,
        contents: List[Content],
        existing: Optional[Content],
        size_bytes: int,
    ) -> int:
        # Failed rows count conservatively: if vector cleanup could not be
        # confirmed, excluding them could leave searchable but unmetered data.
        # A retry with the same stable name still uses delta accounting.
        used_bytes = sum(content.size or 0 for content in contents)
        existing_bytes = (existing.size or 0) if existing is not None else 0
        projected_bytes = used_bytes - existing_bytes + size_bytes
        if projected_bytes > self.max_namespace_bytes:
            raise ValueError(
                f"knowledge is full ({projected_bytes} bytes after this write; limit {self.max_namespace_bytes} bytes)."
            )
        return projected_bytes

    @staticmethod
    def _require_completed_insert(status: Optional[ContentStatus], status_message: Optional[str]) -> None:
        if status == ContentStatus.COMPLETED:
            return
        detail = status_message or (f"content status is {status.value}" if status is not None else "content not found")
        raise RuntimeError(f"knowledge indexing did not complete: {detail}")

    @staticmethod
    def _mark_insert_failed(knowledge: Knowledge, content_id: str, message: str) -> None:
        content = knowledge.get_content_by_id(content_id)
        if content is not None:
            content.status = ContentStatus.FAILED
            content.status_message = message
            knowledge.patch_content(content)

    @staticmethod
    async def _amark_insert_failed(knowledge: Knowledge, content_id: str, message: str) -> None:
        content = await knowledge.aget_content_by_id(content_id)
        if content is not None:
            content.status = ContentStatus.FAILED
            content.status_message = message
            await knowledge.apatch_content(content)

    @staticmethod
    def _cleanup_failed_vectors(knowledge: Knowledge, content_id: str) -> None:
        if knowledge.vector_db is None:
            return
        try:
            if not knowledge.vector_db.delete_by_content_id(content_id):
                log_error(f"Could not confirm vector cleanup for failed knowledge content {content_id}")
        except Exception as error:
            log_error(f"Could not clean up vectors for failed knowledge content {content_id}: {error}")

    @staticmethod
    async def _acleanup_failed_vectors(knowledge: Knowledge, content_id: str) -> None:
        if knowledge.vector_db is None:
            return
        try:
            deleted = await asyncio.to_thread(knowledge.vector_db.delete_by_content_id, content_id)
            if not deleted:
                log_error(f"Could not confirm vector cleanup for failed knowledge content {content_id}")
        except Exception as error:
            log_error(f"Could not clean up vectors for failed knowledge content {content_id}: {error}")

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

    def search_knowledge(
        self,
        run_context: RunContext,
        query: str,
        *,
        agent: Optional[Agent] = None,
        team: Optional[Team] = None,
    ) -> str:
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
            knowledge = self._resolved(run_context, agent, team)
            relevant_docs: List[Document] = knowledge.search(query=query)
            if len(relevant_docs) == 0:
                return "No documents found"
            return json.dumps([doc.to_dict() for doc in relevant_docs])
        except Exception as e:
            log_error(f"Error searching knowledge base: {str(e)}")
            return f"Error searching knowledge base: {e}"

    async def asearch_knowledge(
        self,
        run_context: RunContext,
        query: str,
        *,
        agent: Optional[Agent] = None,
        team: Optional[Team] = None,
    ) -> str:
        """Async variant of search_knowledge."""
        try:
            log_debug(f"Searching knowledge base: {query}")
            knowledge = self._resolved(run_context, agent, team)
            relevant_docs: List[Document] = await knowledge.asearch(query=query)
            if len(relevant_docs) == 0:
                return "No documents found"
            return json.dumps([doc.to_dict() for doc in relevant_docs])
        except Exception as e:
            log_error(f"Error searching knowledge base: {str(e)}")
            return f"Error searching knowledge base: {e}"

    def add_text_to_knowledge(
        self,
        run_context: RunContext,
        name: str,
        text_content: str,
        *,
        agent: Optional[Agent] = None,
        team: Optional[Team] = None,
    ) -> str:
        """Add one bounded text item to this agent's knowledge.

        Args:
            name: A short, stable name for the content.
            text_content: The UTF-8 text to add.

        Returns:
            str: A success message or an error starting with "Error".
        """
        try:
            self._check_name(name)
            if not text_content:
                raise ValueError("text_content must not be empty")
            size_bytes = self._check_content_size(text_content)
            knowledge = self._resolved(run_context, agent, team)
            namespace = knowledge.name or "knowledge"
            content_hash = self._text_content_hash(knowledge, name, text_content, size_bytes)
            content_id = generate_id(content_hash)
            expected_documents = self._expected_text_documents(knowledge, name, text_content)

            with self._get_write_lock(namespace):
                contents, _ = knowledge.get_content()
                existing = knowledge.get_content_by_id(content_id)
                projected_bytes = self._check_namespace_quota(contents, existing, size_bytes)
                knowledge.insert(name=name, text_content=text_content)
                status, status_message = knowledge.get_content_status(content_id)
                try:
                    self._require_completed_insert(status, status_message)
                except RuntimeError:
                    self._cleanup_failed_vectors(knowledge, content_id)
                    raise
                if knowledge.vector_db is None or not knowledge.vector_db.content_hash_is_indexed(
                    content_hash, expected_documents
                ):
                    message = "knowledge indexing did not produce a searchable vector"
                    self._cleanup_failed_vectors(knowledge, content_id)
                    self._mark_insert_failed(knowledge, content_id, message)
                    raise RuntimeError(message)

            return (
                f"Added {size_bytes} bytes to knowledge as {name!r} "
                f"({projected_bytes} of {self.max_namespace_bytes} bytes used)."
            )
        except Exception as e:
            log_error(f"Error adding text to knowledge: {str(e)}")
            return f"Error adding text to knowledge: {e}"

    async def aadd_text_to_knowledge(
        self,
        run_context: RunContext,
        name: str,
        text_content: str,
        *,
        agent: Optional[Agent] = None,
        team: Optional[Team] = None,
    ) -> str:
        """Async variant of add_text_to_knowledge."""
        try:
            self._check_name(name)
            if not text_content:
                raise ValueError("text_content must not be empty")
            size_bytes = self._check_content_size(text_content)
            knowledge = self._resolved(run_context, agent, team)
            namespace = knowledge.name or "knowledge"
            content_hash = self._text_content_hash(knowledge, name, text_content, size_bytes)
            content_id = generate_id(content_hash)
            expected_documents = self._expected_text_documents(knowledge, name, text_content)

            async with self._acquire_async_write_lock(namespace):
                contents, _ = await knowledge.aget_content()
                existing = await knowledge.aget_content_by_id(content_id)
                projected_bytes = self._check_namespace_quota(contents, existing, size_bytes)
                await knowledge.ainsert(name=name, text_content=text_content)
                status, status_message = await knowledge.aget_content_status(content_id)
                try:
                    self._require_completed_insert(status, status_message)
                except RuntimeError:
                    await self._acleanup_failed_vectors(knowledge, content_id)
                    raise
                indexed = (
                    await asyncio.to_thread(
                        knowledge.vector_db.content_hash_is_indexed,
                        content_hash,
                        expected_documents,
                    )
                    if knowledge.vector_db is not None
                    else False
                )
                if not indexed:
                    message = "knowledge indexing did not produce a searchable vector"
                    await self._acleanup_failed_vectors(knowledge, content_id)
                    await self._amark_insert_failed(knowledge, content_id, message)
                    raise RuntimeError(message)

            return (
                f"Added {size_bytes} bytes to knowledge as {name!r} "
                f"({projected_bytes} of {self.max_namespace_bytes} bytes used)."
            )
        except Exception as e:
            log_error(f"Error adding text to knowledge: {str(e)}")
            return f"Error adding text to knowledge: {e}"

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

    ADD_INSTRUCTIONS = dedent("""\
        ## Adding knowledge
        - Use `add_text_to_knowledge` only when the user asks you to remember or index text.
        - Give each item a short, stable name and keep it within the tool's byte limit.
        - Added text is scoped to the current Agent's persistent knowledge namespace.\
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
