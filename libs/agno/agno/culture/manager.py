from copy import deepcopy
from dataclasses import dataclass
from os import getenv
from textwrap import dedent
from typing import Any, Callable, Dict, List, Optional, Union, cast

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.schemas.culture import CulturalKnowledge
from agno.models.base import Model
from agno.models.message import Message
from agno.models.utils import get_model
from agno.tools.function import Function
from agno.utils.log import (
    log_debug,
    log_error,
    log_warning,
    set_log_level_to_debug,
    set_log_level_to_info,
)


@dataclass
class CultureManager:
    """Culture Manager

    Notice: Culture is an experimental feature and is subject to change.
    """

    # Model used for culture management
    model: Optional[Model] = None

    # Provide the system message for the manager as a string. If not provided, the default system message will be used.
    system_message: Optional[str] = None
    # Provide the cultural knowledge capture instructions for the manager as a string. If not provided, the default cultural knowledge capture instructions will be used.
    culture_capture_instructions: Optional[str] = None
    # Additional instructions for the manager. These instructions are appended to the default system message.
    additional_instructions: Optional[str] = None

    # The database to store cultural knowledge
    db: Optional[Union[AsyncBaseDb, BaseDb]] = None

    # ----- Db tools ---------
    # If the Culture Manager can add cultural knowledge
    add_knowledge: bool = True
    # If the Culture Manager can update cultural knowledge
    update_knowledge: bool = True
    # If the Culture Manager can delete cultural knowledge
    delete_knowledge: bool = True
    # If the Culture Manager can clear cultural knowledge
    clear_knowledge: bool = True

    # ----- Internal settings ---------
    # Whether cultural knowledge were updated in the last run of the CultureManager
    knowledge_updated: bool = False
    debug_mode: bool = False

    def __init__(
        self,
        model: Optional[Union[Model, str]] = None,
        db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
        system_message: Optional[str] = None,
        culture_capture_instructions: Optional[str] = None,
        additional_instructions: Optional[str] = None,
        add_knowledge: bool = True,
        update_knowledge: bool = True,
        delete_knowledge: bool = False,
        clear_knowledge: bool = True,
        debug_mode: bool = False,
    ):
        self.model = get_model(model)
        self.db = db
        self.system_message = system_message
        self.culture_capture_instructions = culture_capture_instructions
        self.additional_instructions = additional_instructions
        self.add_knowledge = add_knowledge
        self.update_knowledge = update_knowledge
        self.delete_knowledge = delete_knowledge
        self.clear_knowledge = clear_knowledge
        self.debug_mode = debug_mode

    def get_model(self) -> Model:
        if self.model is None:
            try:
                from agno.models.openai import OpenAIChat
            except ModuleNotFoundError as e:
                log_error(e)
                log_error(
                    "Agno uses `openai` as the default model provider. Please provide a `model` or install `openai`."
                )
                exit(1)
            self.model = OpenAIChat(id="gpt-4o")
        return self.model

    def set_log_level(self):
        if self.debug_mode or getenv("AGNO_DEBUG", "false").lower() == "true":
            self.debug_mode = True
            set_log_level_to_debug()
        else:
            set_log_level_to_info()

    def initialize(self):
        self.set_log_level()

    # -*- Public functions
    def get_knowledge(self, id: str) -> Optional[CulturalKnowledge]:
        """Get the cultural knowledge by id"""
        if not self.db:
            return None

        self.db = cast(BaseDb, self.db)

        return self.db.get_cultural_knowledge(id=id)

    async def aget_knowledge(self, id: str) -> Optional[CulturalKnowledge]:
        """Get the cultural knowledge by id"""
        if not self.db:
            return None

        self.db = cast(AsyncBaseDb, self.db)

        return await self.db.get_cultural_knowledge(id=id)  # type: ignore

    def get_all_knowledge(self, name: Optional[str] = None) -> Optional[List[CulturalKnowledge]]:
        """Get all cultural knowledge in the database"""
        if not self.db:
            return None

        self.db = cast(BaseDb, self.db)

        return self.db.get_all_cultural_knowledge(name=name)

    async def aget_all_knowledge(self, name: Optional[str] = None) -> Optional[List[CulturalKnowledge]]:
        """Get all cultural knowledge in the database"""
        if not self.db:
            return None

        if isinstance(self.db, AsyncBaseDb):
            return await self.db.get_all_cultural_knowledge(name=name)  # type: ignore
        else:
            return self.db.get_all_cultural_knowledge(name=name)

    def add_cultural_knowledge(
        self,
        knowledge: CulturalKnowledge,
    ) -> Optional[str]:
        """Add a cultural knowledge
        Args:
            knowledge (CulturalKnowledge): The knowledge to add
        Returns:
            str: The id of the knowledge
        """
        if self.db:
            if knowledge.id is None:
                from uuid import uuid4

                knowledge_id = knowledge.id or str(uuid4())
                knowledge.id = knowledge_id

            if not knowledge.updated_at:
                knowledge.bump_updated_at()

            self._upsert_db_knowledge(knowledge=knowledge)
            return knowledge.id

        else:
            log_warning("Cultural knowledge database not provided.")
            return None

    def clear_all_knowledge(self) -> None:
        """Clears all cultural knowledge."""
        if self.db:
            self.db.clear_cultural_knowledge()

    # -*- Agent Functions -*-
    def create_cultural_knowledge(
        self,
        message: Optional[str] = None,
        messages: Optional[List[Message]] = None,
        run_response: Optional[Any] = None,
    ) -> str:
        """Creates a cultural knowledge from a message or a list of messages"""
        self.set_log_level()

        if self.db is None:
            log_warning("CultureDb not provided.")
            return "Please provide a db to store cultural knowledge"

        if not messages and not message:
            raise ValueError("You must provide either a message or a list of messages")

        if message:
            messages = [Message(role="user", content=message)]

        if not messages or not isinstance(messages, list):
            raise ValueError("Invalid messages list")

        cultural_knowledge = self.get_all_knowledge()
        if cultural_knowledge is None:
            cultural_knowledge = []

        existing_knowledge = [cultural_knowledge.to_dict() for cultural_knowledge in cultural_knowledge]

        self.db = cast(BaseDb, self.db)
        response = self.create_or_update_cultural_knowledge(
            messages=messages,
            existing_knowledge=existing_knowledge,
            db=self.db,
            update_knowledge=self.update_knowledge,
            add_knowledge=self.add_knowledge,
            run_response=run_response,
        )

        return response

    async def acreate_cultural_knowledge(
        self,
        message: Optional[str] = None,
        messages: Optional[List[Message]] = None,
        run_response: Optional[Any] = None,
    ) -> str:
        """Creates a cultural knowledge from a message or a list of messages"""
        self.set_log_level()

        if self.db is None:
            log_warning("CultureDb not provided.")
            return "Please provide a db to store cultural knowledge"

        if not messages and not message:
            raise ValueError("You must provide either a message or a list of messages")

        if message:
            messages = [Message(role="user", content=message)]

        if not messages or not isinstance(messages, list):
            raise ValueError("Invalid messages list")

        if isinstance(self.db, AsyncBaseDb):
            knowledge = await self.aget_all_knowledge()
        else:
            knowledge = self.get_all_knowledge()

        if knowledge is None:
            knowledge = []

        existing_knowledge = [knowledge.preview() for knowledge in knowledge]

        self.db = cast(AsyncBaseDb, self.db)
        response = await self.acreate_or_update_cultural_knowledge(
            messages=messages,
            existing_knowledge=existing_knowledge,
            db=self.db,
            update_knowledge=self.update_knowledge,
            add_knowledge=self.add_knowledge,
            run_response=run_response,
        )

        return response

    def update_culture_task(self, task: str) -> str:
        """Updates the culture with a task"""

        if not self.db:
            log_warning("CultureDb not provided.")
            return "Please provide a db to store cultural knowledge"

        if not isinstance(self.db, BaseDb):
            raise ValueError(
                "update_culture_task() is not supported with an async DB. Please use aupdate_culture_task() instead."
            )

        knowledge = self.get_all_knowledge()
        if knowledge is None:
            knowledge = []

        existing_knowledge = [knowledge.preview() for knowledge in knowledge]

        self.db = cast(BaseDb, self.db)
        response = self.run_cultural_knowledge_task(
            task=task,
            existing_knowledge=existing_knowledge,
            db=self.db,
            delete_knowledge=self.delete_knowledge,
            update_knowledge=self.update_knowledge,
            add_knowledge=self.add_knowledge,
            clear_knowledge=self.clear_knowledge,
        )

        return response

    async def aupdate_culture_task(
        self,
        task: str,
    ) -> str:
        """Updates the culture with a task asynchronously"""

        if not self.db:
            log_warning("CultureDb not provided.")
            return "Please provide a db to store cultural knowledge"

        if not isinstance(self.db, AsyncBaseDb):
            raise ValueError(
                "aupdate_culture_task() is not supported with a sync DB. Please use update_culture_task() instead."
            )

        knowledge = await self.aget_all_knowledge()
        if knowledge is None:
            knowledge = []

        existing_knowledge = [_knowledge.preview() for _knowledge in knowledge]

        self.db = cast(AsyncBaseDb, self.db)
        response = await self.arun_cultural_knowledge_task(
            task=task,
            existing_knowledge=existing_knowledge,
            db=self.db,
            delete_knowledge=self.delete_knowledge,
            update_knowledge=self.update_knowledge,
            add_knowledge=self.add_knowledge,
            clear_knowledge=self.clear_knowledge,
        )

        return response

    # -*- Utility Functions -*-
    def _determine_tools_for_model(self, tools: List[Callable]) -> List[Union[Function, dict]]:
        # Have to reset each time, because of different user IDs

        _function_names = []
        _functions: List[Union[Function, dict]] = []

        for tool in tools:
            try:
                function_name = tool.__name__
                if function_name in _function_names:
                    continue
                _function_names.append(function_name)
                func = Function.from_callable(tool, strict=True)  # type: ignore
                func.strict = True
                _functions.append(func)
                log_debug(f"Added function {func.name}")
            except Exception as e:
                log_warning(f"Could not add function {tool}: {e}")

        return _functions

    def get_system_message(
        self,
        existing_knowledge: Optional[List[Dict[str, Any]]] = None,
        enable_delete_knowledge: bool = True,
        enable_clear_knowledge: bool = True,
        enable_update_knowledge: bool = True,
        enable_add_knowledge: bool = True,
    ) -> Message:
        """Build the system prompt that instructs the model how to maintain cultural knowledge."""

        if self.system_message is not None:
            return Message(role="system", content=self.system_message)

        # Default capture instructions
        culture_capture_instructions = self.culture_capture_instructions or dedent(
            """
            Cultural knowledge should capture shared knowledge, insights, and practices that can improve performance across agents:
            - Best practices and successful approaches discovered in previous interactions
            - Common patterns in user behavior, team workflows, or recurring issues
            - Processes, design principles, or rules of operation
            - Guardrails, decision rationales, or ethical guidelines
            - Domain-specific lessons that generalize beyond one case
            - Communication styles or collaboration methods that lead to better outcomes
            - Any other valuable insight that should persist across agents and time
            """
        )

        system_prompt_lines: List[str] = [
            "You are the **Cultural Knowledge Manager**, responsible for maintaining, evolving, and safeguarding "
            "the shared cultural knowledge for Agents and Multi-Agent Teams. ",
            "",
            "Given a user message, your task is to distill, organize, and extract collective intelligence from it, including insights, lessons, "
            "rules, principles, and narratives that guide future behavior across agents and teams.",
            "",
            "You will be provided with criteria for cultural knowledge to capture in the <knowledge_to_capture> section, "
            "and the existing cultural knowledge in the <existing_knowledge> section.",
            "",
            "## When to add or update cultural knowledge",
            "- Decide if knowledge should be **added, updated, deleted**, or if **no changes are needed**.",
            "- If new insights meet the criteria in <knowledge_to_capture> and are not already captured in the <existing_knowledge> section, add them.",
            "- If existing practices evolve, update relevant entries (while preserving historical context if useful).",
            "- If nothing new or valuable emerged, respond with exactly: `No changes needed`.",
            "",
            "## How to add or update cultural knowledge",
            "- Write entries that are **clear, specific, and actionable** (avoid vague abstractions).",
            "- Each entry should capture one coherent idea or rule — use multiple entries if necessary.",
            "- Do **not** duplicate information; update similar entries instead.",
            "- When updating, append new insights rather than overwriting useful context.",
            "- Use short Markdown lists, examples, or code blocks to increase clarity.",
            "",
            "## Criteria for creating cultural knowledge",
            "<knowledge_to_capture>" + culture_capture_instructions + "</knowledge_to_capture>",
            "",
            "## Metadata & structure (use these fields when creating/updating)",
            "- `name`: short, specific title (required).",
            "- `summary`: one-line purpose or takeaway.",
            "- `content`: reusable insight, rule, or guideline (required).",
            "- `categories`: list of tags (e.g., ['guardrails', 'rules', 'principles', 'practices', 'patterns', 'behaviors', 'stories']).",
            "- `notes`: list of contextual notes, rationale, or examples.",
            "- `metadata`: optional structured info (e.g., source, author, version).",
            "",
            "## De-duplication, lineage, and precedence",
            "- Search <existing_knowledge> by name/category before adding new entries.",
            "- If a similar entry exists, **update** it instead of creating a duplicate.",
            "- Preserve lineage via `notes` when revising entries.",
            "- When entries conflict, prefer the entry with higher `confidence`.",
            "",
            "## Safety & privacy",
            "- Never include secrets, credentials, personal data, or proprietary information.",
            "",
            "## Tool usage",
            "You can call multiple tools in a single response. Use them only when valuable cultural knowledge emerges.",
        ]

        # Tool permissions (based on flags)
        tool_lines: List[str] = []
        if enable_add_knowledge:
            tool_lines.append("- Add new entries using the `add_knowledge` tool.")
        if enable_update_knowledge:
            tool_lines.append("- Update existing entries using the `update_knowledge` tool.")
        if enable_delete_knowledge:
            tool_lines.append("- Delete entries using the `delete_knowledge` tool (use sparingly; prefer deprecate).")
        if enable_clear_knowledge:
            tool_lines.append("- Clear all entries using the `clear_knowledge` tool (only when explicitly instructed).")
        if tool_lines:
            system_prompt_lines += [""] + tool_lines

        if existing_knowledge and len(existing_knowledge) > 0:
            system_prompt_lines.append("\n<existing_knowledge>")
            for _existing_knowledge in existing_knowledge:  # type: ignore
                system_prompt_lines.append("--------------------------------")
                system_prompt_lines.append(f"Knowledge ID: {_existing_knowledge.get('id')}")
                system_prompt_lines.append(f"Name: {_existing_knowledge.get('name')}")
                system_prompt_lines.append(f"Summary: {_existing_knowledge.get('summary')}")
                system_prompt_lines.append(f"Categories: {_existing_knowledge.get('categories')}")
                system_prompt_lines.append(f"Content: {_existing_knowledge.get('content')}")
            system_prompt_lines.append("</existing_knowledge>")

        # Final guardrail for no-op
        system_prompt_lines += [
            "",
            "## When no changes are needed",
            "If no valuable cultural knowledge emerges, or everything is already captured, respond with exactly:",
            "`No changes needed`",
        ]

        if self.additional_instructions:
            system_prompt_lines.append(self.additional_instructions)

        return Message(role="system", content="\n".join(system_prompt_lines))

    def create_or_update_cultural_knowledge(
        self,
        messages: List[Message],
        existing_knowledge: List[Dict[str, Any]],
        db: BaseDb,
        update_knowledge: bool = True,
        add_knowledge: bool = True,
        run_response: Optional[Any] = None,
    ) -> str:
        if self.model is None:
            log_error("No model provided for culture manager")
            return "No model provided for culture manager"

        log_debug("CultureManager Start", center=True)

        model_copy = deepcopy(self.model)
        # Update the Model (set defaults, add logit etc.)
        _tools = self._determine_tools_for_model(
            self._get_db_tools(
                db,
                enable_add_knowledge=add_knowledge,
                enable_update_knowledge=update_knowledge,
                enable_delete_knowledge=False,
                enable_clear_knowledge=False,
            ),
        )

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [
            self.get_system_message(
                existing_knowledge=existing_knowledge,
                enable_update_knowledge=update_knowledge,
                enable_add_knowledge=add_knowledge,
                enable_delete_knowledge=False,
                enable_clear_knowledge=False,
            ),
            *messages,
        ]

        # Generate a response from the Model (includes running function calls)
        response = model_copy.response(
            messages=messages_for_model,
            tools=_tools,
        )

        # Accumulate culture model metrics to run_response
        if run_response is not None and response.response_usage is not None:
            from agno.metrics import ModelType, accumulate_model_metrics

            accumulate_model_metrics(response, model_copy, ModelType.CULTURE_MODEL, run_response)

        if response.tool_calls is not None and len(response.tool_calls) > 0:
            self.knowledge_updated = True

        log_debug("Culture Manager End", center=True)

        return response.content or "No response from model"

    async def acreate_or_update_cultural_knowledge(
        self,
        messages: List[Message],
        existing_knowledge: List[Dict[str, Any]],
        db: AsyncBaseDb,
        update_knowledge: bool = True,
        add_knowledge: bool = True,
        run_response: Optional[Any] = None,
    ) -> str:
        if self.model is None:
            log_error("No model provided for cultural manager")
            return "No model provided for cultural manager"

        log_debug("Cultural Manager Start", center=True)

        model_copy = deepcopy(self.model)
        db = cast(AsyncBaseDb, db)

        _tools = self._determine_tools_for_model(
            await self._aget_db_tools(
                db,
                enable_update_knowledge=update_knowledge,
                enable_add_knowledge=add_knowledge,
            ),
        )

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [
            self.get_system_message(
                existing_knowledge=existing_knowledge,
                enable_update_knowledge=update_knowledge,
                enable_add_knowledge=add_knowledge,
            ),
            # For models that require a non-system message
            *messages,
        ]

        # Generate a response from the Model (includes running function calls)
        response = await model_copy.aresponse(
            messages=messages_for_model,
            tools=_tools,
        )

        # Accumulate culture model metrics to run_response
        if run_response is not None and response.response_usage is not None:
            from agno.metrics import ModelType, accumulate_model_metrics

            accumulate_model_metrics(response, model_copy, ModelType.CULTURE_MODEL, run_response)

        if response.tool_calls is not None and len(response.tool_calls) > 0:
            self.knowledge_updated = True

        log_debug("Cultural Knowledge Manager End", center=True)

        return response.content or "No response from model"

    def run_cultural_knowledge_task(
        self,
        task: str,
        existing_knowledge: List[Dict[str, Any]],
        db: BaseDb,
        delete_knowledge: bool = True,
        update_knowledge: bool = True,
        add_knowledge: bool = True,
        clear_knowledge: bool = True,
    ) -> str:
        if self.model is None:
            log_error("No model provided for cultural manager")
            return "No model provided for cultural manager"

        log_debug("Cultural Knowledge Manager Start", center=True)

        model_copy = deepcopy(self.model)
        # Update the Model (set defaults, add logit etc.)
        _tools = self._determine_tools_for_model(
            self._get_db_tools(
                db,
                enable_delete_knowledge=delete_knowledge,
                enable_clear_knowledge=clear_knowledge,
                enable_update_knowledge=update_knowledge,
                enable_add_knowledge=add_knowledge,
            ),
        )

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [
            self.get_system_message(
                existing_knowledge,
                enable_delete_knowledge=delete_knowledge,
                enable_clear_knowledge=clear_knowledge,
                enable_update_knowledge=update_knowledge,
                enable_add_knowledge=add_knowledge,
            ),
            # For models that require a non-system message
            Message(role="user", content=task),
        ]

        # Generate a response from the Model (includes running function calls)
        response = model_copy.response(
            messages=messages_for_model,
            tools=_tools,
        )

        if response.tool_calls is not None and len(response.tool_calls) > 0:
            self.knowledge_updated = True

        log_debug("Cultural Knowledge Manager End", center=True)

        return response.content or "No response from model"

    async def arun_cultural_knowledge_task(
        self,
        task: str,
        existing_knowledge: List[Dict[str, Any]],
        db: Union[BaseDb, AsyncBaseDb],
        delete_knowledge: bool = True,
        clear_knowledge: bool = True,
        update_knowledge: bool = True,
        add_knowledge: bool = True,
    ) -> str:
        if self.model is None:
            log_error("No model provided for cultural manager")
            return "No model provided for cultural manager"

        log_debug("Cultural Manager Start", center=True)

        model_copy = deepcopy(self.model)
        # Update the Model (set defaults, add logit etc.)
        if isinstance(db, AsyncBaseDb):
            _tools = self._determine_tools_for_model(
                await self._aget_db_tools(
                    db,
                    enable_delete_knowledge=delete_knowledge,
                    enable_clear_knowledge=clear_knowledge,
                    enable_update_knowledge=update_knowledge,
                    enable_add_knowledge=add_knowledge,
                ),
            )
        else:
            _tools = self._determine_tools_for_model(
                self._get_db_tools(
                    db,
                    enable_delete_knowledge=delete_knowledge,
                    enable_clear_knowledge=clear_knowledge,
                    enable_update_knowledge=update_knowledge,
                    enable_add_knowledge=add_knowledge,
                ),
            )

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [
            self.get_system_message(
                existing_knowledge,
                enable_delete_knowledge=delete_knowledge,
                enable_clear_knowledge=clear_knowledge,
                enable_update_knowledge=update_knowledge,
                enable_add_knowledge=add_knowledge,
            ),
            # For models that require a non-system message
            Message(role="user", content=task),
        ]

        # Generate a response from the Model (includes running function calls)
        response = await model_copy.aresponse(
            messages=messages_for_model,
            tools=_tools,
        )

        if response.tool_calls is not None and len(response.tool_calls) > 0:
            self.knowledge_updated = True

        log_debug("Cultural Manager End", center=True)

        return response.content or "No response from model"

    # -*- DB Functions -*-
    def _clear_db_knowledge(self) -> str:
        """Use this function to clear all cultural knowledge from the database."""
        try:
            if not self.db:
                raise ValueError("Culture db not initialized")
            self.db = cast(BaseDb, self.db)
            self.db.clear_cultural_knowledge()
            return "Cultural knowledge cleared successfully"
        except Exception as e:
            log_warning(f"Error clearing cultural knowledge in db: {e}")
            return f"Error clearing cultural knowledge: {e}"

    async def _aclear_db_knowledge(self) -> str:
        """Use this function to clear all cultural knowledge from the database."""
        try:
            if not self.db:
                raise ValueError("Culture db not initialized")
            self.db = cast(AsyncBaseDb, self.db)
            await self.db.clear_cultural_knowledge()
            return "Cultural knowledge cleared successfully"
        except Exception as e:
            log_warning(f"Error clearing cultural knowledge in db: {e}")
            return f"Error clearing cultural knowledge: {e}"

    def _delete_db_knowledge(self, knowledge_id: str) -> str:
        """Use this function to delete a cultural knowledge from the database."""
        try:
            if not self.db:
                raise ValueError("Culture db not initialized")
            self.db = cast(BaseDb, self.db)
            self.db.delete_cultural_knowledge(id=knowledge_id)
            return "Cultural knowledge deleted successfully"
        except Exception as e:
            log_warning(f"Error deleting cultural knowledge in db: {e}")
            return f"Error deleting cultural knowledge: {e}"

    async def _adelete_db_knowledge(self, knowledge_id: str) -> str:
        """Use this function to delete a cultural knowledge from the database."""
        try:
            if not self.db:
                raise ValueError("Culture db not initialized")
            self.db = cast(AsyncBaseDb, self.db)
            await self.db.delete_cultural_knowledge(id=knowledge_id)
            return "Cultural knowledge deleted successfully"
        except Exception as e:
            log_warning(f"Error deleting cultural knowledge in db: {e}")
            return f"Error deleting cultural knowledge: {e}"

    def _upsert_db_knowledge(self, knowledge: CulturalKnowledge) -> str:
        """Use this function to add a cultural knowledge to the database."""
        try:
            if not self.db:
                raise ValueError("Culture db not initialized")
            self.db = cast(BaseDb, self.db)
            self.db.upsert_cultural_knowledge(cultural_knowledge=knowledge)
            return "Cultural knowledge added successfully"
        except Exception as e:
            log_warning(f"Error storing cultural knowledge in db: {e}")
            return f"Error adding cultural knowledge: {e}"

    # -* Get DB Tools -*-
    def _get_db_tools(
        self,
        db: Union[BaseDb, AsyncBaseDb],
        enable_add_knowledge: bool = True,
        enable_update_knowledge: bool = True,
        enable_delete_knowledge: bool = True,
        enable_clear_knowledge: bool = True,
    ) -> List[Callable]:
        def add_cultural_knowledge(
            name: str,
            summary: Optional[str] = None,
            content: Optional[str] = None,
            categories: Optional[List[str]] = None,
        ) -> str:
            """Use this function to add a cultural knowledge to the database.
            Args:
                name (str): The name of the cultural knowledge. Short, specific title.
                summary (Optional[str]): The summary of the cultural knowledge. One-line purpose or takeaway.
                content (Optional[str]): The content of the cultural knowledge. Reusable insight, rule, or guideline.
                categories (Optional[List[str]]): The categories of the cultural knowledge. List of tags (e.g. ["guardrails", "rules", "principles", "practices", "patterns", "behaviors", "stories"]).
            Returns:
                str: A message indicating if the cultural knowledge was added successfully or not.
            """
            from uuid import uuid4

            try:
                knowledge_id = str(uuid4())
                db.upsert_cultural_knowledge(
                    CulturalKnowledge(
                        id=knowledge_id,
                        name=name,
                        summary=summary,
                        content=content,
                        categories=categories,
                    )
                )
                log_debug(f"Cultural knowledge added: {knowledge_id}")
                return "Cultural knowledge added successfully"
            except Exception as e:
                log_warning(f"Error storing cultural knowledge in db: {e}")
                return f"Error adding cultural knowledge: {e}"

        def update_cultural_knowledge(
            knowledge_id: str,
            name: str,
            summary: Optional[str] = None,
            content: Optional[str] = None,
            categories: Optional[List[str]] = None,
        ) -> str:
            """Use this function to update an existing cultural knowledge in the database.
            Args:
                knowledge_id (str): The id of the cultural knowledge to be updated.
                name (str): The name of the cultural knowledge. Short, specific title.
                summary (Optional[str]): The summary of the cultural knowledge. One-line purpose or takeaway.
                content (Optional[str]): The content of the cultural knowledge. Reusable insight, rule, or guideline.
                categories (Optional[List[str]]): The categories of the cultural knowledge. List of tags (e.g. ["guardrails", "rules", "principles", "practices", "patterns", "behaviors", "stories"]).
            Returns:
                str: A message indicating if the cultural knowledge was updated successfully or not.
            """
            from agno.db.base import CulturalKnowledge

            try:
                db.upsert_cultural_knowledge(
                    CulturalKnowledge(
                        id=knowledge_id,
                        name=name,
                        summary=summary,
                        content=content,
                        categories=categories,
                    )
                )
                log_debug("Cultural knowledge updated")
                return "Cultural knowledge updated successfully"
            except Exception as e:
                log_warning(f"Error storing cultural knowledge in db: {e}")
                return f"Error adding cultural knowledge: {e}"

        def delete_cultural_knowledge(knowledge_id: str) -> str:
            """Use this function to delete a single cultural knowledge from the database.
            Args:
                knowledge_id (str): The id of the cultural knowledge to be deleted.
            Returns:
                str: A message indicating if the cultural knowledge was deleted successfully or not.
            """
            try:
                db.delete_cultural_knowledge(id=knowledge_id)
                log_debug("Cultural knowledge deleted")
                return "Cultural knowledge deleted successfully"
            except Exception as e:
                log_warning(f"Error deleting cultural knowledge in db: {e}")
                return f"Error deleting cultural knowledge: {e}"

        def clear_cultural_knowledge() -> str:
            """Use this function to remove all (or clear all) cultural knowledge from the database.
            Returns:
                str: A message indicating if the cultural knowledge was cleared successfully or not.
            """
            db.clear_cultural_knowledge()
            log_debug("Cultural knowledge cleared")
            return "Cultural knowledge cleared successfully"

        functions: List[Callable] = []
        if enable_add_knowledge:
            functions.append(add_cultural_knowledge)
        if enable_update_knowledge:
            functions.append(update_cultural_knowledge)
        if enable_delete_knowledge:
            functions.append(delete_cultural_knowledge)
        if enable_clear_knowledge:
            functions.append(clear_cultural_knowledge)
        return functions

    async def _aget_db_tools(
        self,
        db: AsyncBaseDb,
        enable_add_knowledge: bool = True,
        enable_update_knowledge: bool = True,
        enable_delete_knowledge: bool = True,
        enable_clear_knowledge: bool = True,
    ) -> List[Callable]:
        async def add_cultural_knowledge(
            name: str,
            summary: Optional[str] = None,
            content: Optional[str] = None,
            categories: Optional[List[str]] = None,
        ) -> str:
            """Use this function to add a cultural knowledge to the database.
            Args:
                name (str): The name of the cultural knowledge.
                summary (Optional[str]): The summary of the cultural knowledge.
                content (Optional[str]): The content of the cultural knowledge.
                categories (Optional[List[str]]): The categories of the cultural knowledge (e.g. ["name", "hobbies", "location"]).
            Returns:
                str: A message indicating if the cultural knowledge was added successfully or not.
            """
            from uuid import uuid4

            try:
                knowledge_id = str(uuid4())
                await db.upsert_cultural_knowledge(
                    CulturalKnowledge(
                        id=knowledge_id,
                        name=name,
                        summary=summary,
                        content=content,
                        categories=categories,
                    )
                )
                log_debug(f"Cultural knowledge added: {knowledge_id}")
                return "Cultural knowledge added successfully"
            except Exception as e:
                log_warning(f"Error storing cultural knowledge in db: {e}")
                return f"Error adding cultural knowledge: {e}"

        async def update_cultural_knowledge(
            knowledge_id: str,
            name: str,
            summary: Optional[str] = None,
            content: Optional[str] = None,
            categories: Optional[List[str]] = None,
        ) -> str:
            """Use this function to update an existing cultural knowledge in the database.
            Args:
                knowledge_id (str): The id of the cultural knowledge to be updated.
                name (str): The name of the cultural knowledge.
                summary (Optional[str]): The summary of the cultural knowledge.
                content (Optional[str]): The content of the cultural knowledge.
                categories (Optional[List[str]]): The categories of the cultural knowledge (e.g. ["name", "hobbies", "location"]).
            Returns:
                str: A message indicating if the cultural knowledge was updated successfully or not.
            """
            from agno.db.base import CulturalKnowledge

            try:
                await db.upsert_cultural_knowledge(
                    CulturalKnowledge(
                        id=knowledge_id,
                        name=name,
                        summary=summary,
                        content=content,
                        categories=categories,
                    )
                )
                log_debug("Cultural knowledge updated")
                return "Cultural knowledge updated successfully"
            except Exception as e:
                log_warning(f"Error storing cultural knowledge in db: {e}")
                return f"Error updating cultural knowledge: {e}"

        async def delete_cultural_knowledge(knowledge_id: str) -> str:
            """Use this function to delete a single cultural knowledge from the database.
            Args:
                knowledge_id (str): The id of the cultural knowledge to be deleted.
            Returns:
                str: A message indicating if the cultural knowledge was deleted successfully or not.
            """
            try:
                await db.delete_cultural_knowledge(id=knowledge_id)
                log_debug("Cultural knowledge deleted")
                return "Cultural knowledge deleted successfully"
            except Exception as e:
                log_warning(f"Error deleting cultural knowledge in db: {e}")
                return f"Error deleting cultural knowledge: {e}"

        async def clear_cultural_knowledge() -> str:
            """Use this function to remove all (or clear all) cultural knowledge from the database.
            Returns:
                str: A message indicating if the cultural knowledge was cleared successfully or not.
            """
            await db.clear_cultural_knowledge()
            log_debug("Cultural knowledge cleared")
            return "Cultural knowledge cleared successfully"

        functions: List[Callable] = []
        if enable_add_knowledge:
            functions.append(add_cultural_knowledge)
        if enable_update_knowledge:
            functions.append(update_cultural_knowledge)
        if enable_delete_knowledge:
            functions.append(delete_cultural_knowledge)
        if enable_clear_knowledge:
            functions.append(clear_cultural_knowledge)
        return functions
