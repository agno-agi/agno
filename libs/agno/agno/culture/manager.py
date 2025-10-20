from copy import deepcopy
from dataclasses import dataclass
from os import getenv
from textwrap import dedent
from typing import Any, Callable, Dict, List, Optional, Union, cast

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.schemas.culture import CulturalKnowledge
from agno.models.base import Model
from agno.models.message import Message
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
    """Culture Manager"""

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
        model: Optional[Model] = None,
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
        self.model = model
        if self.model is not None and isinstance(self.model, str):
            raise ValueError("Model must be a Model object, not a string")
        self.db = db
        self.system_message = system_message
        self.culture_capture_instructions = culture_capture_instructions
        self.additional_instructions = additional_instructions
        self.add_knowledge = add_knowledge
        self.update_knowledge = update_knowledge
        self.delete_knowledge = delete_knowledge
        self.clear_knowledge = clear_knowledge
        self.debug_mode = debug_mode
        self._tools_for_model: Optional[List[Dict[str, Any]]] = None
        self._functions_for_model: Optional[Dict[str, Function]] = None

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

        return await self.db.get_cultural_knowledge(id=id)

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

        self.db = cast(AsyncBaseDb, self.db)

        return await self.db.get_all_cultural_knowledge(name=name)

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

        existing_knowledge = [cultural_knowledge.preview() for cultural_knowledge in cultural_knowledge]

        self.db = cast(BaseDb, self.db)
        response = self.create_or_update_cultural_knowledge(
            messages=messages,
            existing_knowledge=existing_knowledge,
            db=self.db,
            update_knowledge=self.update_knowledge,
            add_knowledge=self.add_knowledge,
        )

        return response

    async def acreate_cultural_knowledge(
        self,
        message: Optional[str] = None,
        messages: Optional[List[Message]] = None,
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
    def determine_tools_for_model(self, tools: List[Callable]) -> None:
        # Have to reset each time, because of different user IDs
        self._tools_for_model = []
        self._functions_for_model = {}

        for tool in tools:
            try:
                function_name = tool.__name__
                if function_name not in self._functions_for_model:
                    func = Function.from_callable(tool, strict=True)  # type: ignore
                    func.strict = True
                    self._functions_for_model[func.name] = func
                    self._tools_for_model.append({"type": "function", "function": func.to_dict()})
                    log_debug(f"Added function {func.name}")
            except Exception as e:
                log_warning(f"Could not add function {tool}: {e}")

    def get_system_message(
        self,
        existing_knowledge: Optional[List[Dict[str, Any]]] = None,
        enable_delete_knowledge: bool = True,
        enable_clear_knowledge: bool = True,
        enable_update_knowledge: bool = True,
        enable_add_knowledge: bool = True,
    ) -> Message:
        if self.system_message is not None:
            return Message(role="system", content=self.system_message)

        culture_capture_instructions = self.culture_capture_instructions or dedent(
            """\
            Cultural knowledge should capture shared knowledge, insights, and practices that can improve your performance across conversations:
            - Best practices and successful approaches discovered during previous conversations
            - Common patterns in user behavior, preferences, or needs that remain true across conversations
            - Organizational knowledge, processes, or contextual information
            - Insights about effective communication styles or problem-solving methods
            - Domain-specific knowledge or expertise that emerges from conversations
            - Any other valuable understanding that should be preserved and shared across agents
        """
        )

        system_prompt_lines = [
            "You are a Culture Manager responsible for managing organizational cultural knowledge and insights. "
            "You will be provided with criteria for cultural knowledge to capture in the <knowledge_to_capture> section and the existing cultural knowledge in the <existing_knowledge> section.",
            "",
            "## When to add or update cultural knowledge",
            "- Your first task is to decide if cultural knowledge needs to be added, updated, or deleted based on discovered insights OR if no changes are needed.",
            "- If you discover knowledge that meets the criteria in the <knowledge_to_capture> section and is not already captured in the <existing_knowledge> section, you should capture it as a cultural knowledge.",
            "- If no valuable organizational knowledge emerges from the interaction, no knowledge updates are needed.",
            "- If the existing knowledge in the <existing_knowledge> section capture all relevant insights, no knowledge updates are needed.",
            "",
            "## How to add or update cultural knowledge",
            "- If you decide to add a new knowledge, create knowledge that capture key insights for future reference across the organization.",
            "- Knowledge should be clear, actionable statements that encapsulate valuable knowledge without being overly specific to individual cases.",
            "  - Example: If multiple users struggle with a concept, a knowledge could be `Users often need step-by-step guidance when learning API integration`.",
            "  - Example: If a particular approach works well, a knowledge could be `Visual examples significantly improve user understanding of complex workflows`.",
            "- Don't make a single knowledge too broad or complex, create multiple knowledge if needed to capture distinct insights.",
            "- Don't duplicate information across knowledge. Rather update existing knowledge if they cover similar ground.",
            "- If organizational practices change, update relevant knowledge to reflect current approaches while preserving historical context when valuable.",
            "- When updating a knowledge, enhance it with new insights rather than completely overwriting existing knowledge.",
            "- Focus on knowledge that transcends individual conversations and provides value to future interactions.",
            "",
            "## Criteria for creating cultural knowledge",
            "Use the following criteria to determine if discovered knowledge should be captured as a cultural knowledge.",
            "",
            "<knowledge_to_capture>",
            culture_capture_instructions,
            "</knowledge_to_capture>",
            "",
            "## Updating cultural knowledge",
            "You will also be provided with a list of existing cultural knowledge in the <existing_knowledge> section. You can:",
            "  - Decide to make no changes.",
            "",
            "## When no changes are needed",
            "If no valuable organizational knowledge emerges from the interaction, just respond with 'No changes needed'. Do not answer the user's message.",
        ]

        if enable_add_knowledge:
            system_prompt_lines.append("  - Decide to add a new cultural knowledge, using the `add_knowledge` tool.")
        if enable_update_knowledge:
            system_prompt_lines.append(
                "  - Decide to update an existing cultural knowledge, using the `update_knowledge` tool."
            )
        if enable_delete_knowledge:
            system_prompt_lines.append(
                "  - Decide to delete an existing cultural knowledge, using the `delete_knowledge` tool."
            )
        if enable_clear_knowledge:
            system_prompt_lines.append("  - Decide to clear all cultural knowledge, using the `clear_knowledge` tool.")

        system_prompt_lines += [
            "You can call multiple tools in a single response if needed. ",
            "Only add or update cultural knowledge if valuable organizational knowledge emerges that should be preserved and shared.",
        ]

        if existing_knowledge and len(existing_knowledge) > 0:
            system_prompt_lines.append("\n<existing_knowledge>")
            for _existing_knowledge in existing_knowledge:  # type: ignore
                system_prompt_lines.append(f"Knowledge: {_existing_knowledge.get('content')}")
                system_prompt_lines.append("")
            system_prompt_lines.append("</existing_knowledge>")

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
    ) -> str:
        if self.model is None:
            log_error("No model provided for culture manager")
            return "No model provided for culture manager"

        log_debug("CultureManager Start", center=True)

        model_copy = deepcopy(self.model)
        # Update the Model (set defaults, add logit etc.)
        self.determine_tools_for_model(
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
            tools=self._tools_for_model,
            functions=self._functions_for_model,
        )

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
    ) -> str:
        if self.model is None:
            log_error("No model provided for cultural manager")
            return "No model provided for cultural manager"

        log_debug("Cultural Manager Start", center=True)

        model_copy = deepcopy(self.model)
        db = cast(AsyncBaseDb, db)

        self.determine_tools_for_model(
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
            tools=self._tools_for_model,
            functions=self._functions_for_model,
        )

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
        self.determine_tools_for_model(
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
            tools=self._tools_for_model,
            functions=self._functions_for_model,
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
            self.determine_tools_for_model(
                await self._aget_db_tools(
                    db,
                    enable_delete_knowledge=delete_knowledge,
                    enable_clear_knowledge=clear_knowledge,
                    enable_update_knowledge=update_knowledge,
                    enable_add_knowledge=add_knowledge,
                ),
            )
        else:
            self.determine_tools_for_model(
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
            tools=self._tools_for_model,
            functions=self._functions_for_model,
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

    async def _aupsert_db_knowledge(self, knowledge: CulturalKnowledge) -> str:
        """Use this function to add a cultural knowledge to the database."""
        try:
            if not self.db:
                raise ValueError("Culture db not initialized")
            self.db = cast(AsyncBaseDb, self.db)
            await self.db.upsert_cultural_knowledge(cultural_knowledge=knowledge)
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
                name (str): The name of the cultural knowledge.
                summary (Optional[str]): The summary of the cultural knowledge.
                content (Optional[str]): The content of the cultural knowledge.
                categories (Optional[List[str]]): The categories of the cultural knowledge (e.g. ["name", "hobbies", "location"]).
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
