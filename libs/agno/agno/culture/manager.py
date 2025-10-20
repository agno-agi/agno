from copy import deepcopy
from dataclasses import dataclass
from os import getenv
from textwrap import dedent
from typing import Any, Callable, Dict, List, Optional, Union, cast

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.schemas.culture import CulturalNotion
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
    # Provide the cultural notion capture instructions for the manager as a string. If not provided, the default cultural notion capture instructions will be used.
    culture_capture_instructions: Optional[str] = None
    # Additional instructions for the manager. These instructions are appended to the default system message.
    additional_instructions: Optional[str] = None

    # The database to store cultural notions
    db: Optional[Union[AsyncBaseDb, BaseDb]] = None

    # ----- db tools ---------
    # If the CultureManager can add cultural notions
    add_notions: bool = True
    # If the CultureManager can update cultural notions
    update_notions: bool = True
    # If the CultureManager can delete cultural notions
    delete_notions: bool = True
    # If the CultureManager can clear cultural notions
    clear_notions: bool = True

    # ----- internal settings ---------
    # Whether cultural notions were updated in the last run of the CultureManager
    notions_updated: bool = False
    debug_mode: bool = False

    def __init__(
        self,
        model: Optional[Model] = None,
        db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
        add_notions: bool = True,
        update_notions: bool = True,
        delete_notions: bool = False,
        clear_notions: bool = True,
        debug_mode: bool = False,
    ):
        self.model = model
        if self.model is not None and isinstance(self.model, str):
            raise ValueError("Model must be a Model object, not a string")
        self.db = db
        self.add_notions = add_notions
        self.update_notions = update_notions
        self.delete_notions = delete_notions
        self.clear_notions = clear_notions
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
    def get_notion(self, id: str) -> Optional[CulturalNotion]:
        """Get the cultural notion by id"""
        if not self.db:
            return None

        self.db = cast(BaseDb, self.db)

        return self.db.get_cultural_notion(id=id)

    async def aget_notion(self, id: str) -> Optional[CulturalNotion]:
        """Get the cultural notion by id"""
        if not self.db:
            return None

        self.db = cast(AsyncBaseDb, self.db)

        return await self.db.get_cultural_notion(id=id)

    def get_all_notions(self, name: Optional[str] = None) -> Optional[List[CulturalNotion]]:
        """Get all cultural notions in the database"""
        if not self.db:
            return None

        self.db = cast(BaseDb, self.db)

        return self.db.get_cultural_notions(name=name)

    async def aget_all_notions(self, name: Optional[str] = None) -> Optional[List[CulturalNotion]]:
        """Get all cultural notions in the database"""
        if not self.db:
            return None

        self.db = cast(AsyncBaseDb, self.db)

        return await self.db.get_cultural_notions(name=name)

    def add_notion(
        self,
        notion: CulturalNotion,
    ) -> Optional[str]:
        """Add a cultural notion
        Args:
            notion (CulturalNotion): The notion to add
        Returns:
            str: The id of the notion
        """
        if self.db:
            if notion.id is None:
                from uuid import uuid4

                notion_id = notion.id or str(uuid4())
                notion.id = notion_id

            if not notion.updated_at:
                notion.bump_updated_at()

            self._upsert_db_notion(notion=notion)
            return notion.id

        else:
            log_warning("CultureDb not provided.")
            return None

    def clear_all_notions(self) -> None:
        """Clears all cultural knowledge."""
        if self.db:
            self.db.clear_cultural_notions()

    # -*- Agent Functions -*-
    def create_cultural_notions(
        self,
        message: Optional[str] = None,
        messages: Optional[List[Message]] = None,
    ) -> str:
        """Creates a cultural notion from a message or a list of messages"""
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

        notions = self.get_all_notions()
        if notions is None:
            notions = []

        existing_notions = [notion.preview() for notion in notions]

        self.db = cast(BaseDb, self.db)
        response = self.create_or_update_notions(
            messages=messages,
            existing_notions=existing_notions,
            db=self.db,
            update_notions=self.update_notions,
            add_notions=self.add_notions,
        )

        return response

    async def acreate_cultural_notions(
        self,
        message: Optional[str] = None,
        messages: Optional[List[Message]] = None,
    ) -> str:
        """Creates a cultural notion from a message or a list of messages"""
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

        knowledge = self.get_all_notions()
        if knowledge is None:
            knowledge = []

        existing_notions = [notion.preview() for notion in knowledge]

        self.db = cast(AsyncBaseDb, self.db)
        response = await self.acreate_or_update_notions(
            messages=messages,
            existing_notions=existing_notions,
            db=self.db,
            update_notions=self.update_notions,
            add_notions=self.add_notions,
        )

        return response

    def create_or_update_notions(
        self,
        messages: List[Message],
        existing_notions: List[Dict[str, Any]],
        db: BaseDb,
        add_notions: bool = True,
        clear_notions: bool = True,
        delete_notions: bool = False,
        update_notions: bool = True,
    ) -> str:
        if self.model is None:
            log_error("No model provided for CultureManager")
            return "No model provided for CultureManager"

        log_debug("CultureManager Start", center=True)

        model_copy = deepcopy(self.model)
        # Update the Model (set defaults, add logit etc.)
        self.determine_tools_for_model(
            self._get_db_tools(
                db=db,
                enable_add_notions=add_notions,
                enable_update_notions=update_notions,
                enable_delete_notions=delete_notions,
                enable_clear_notions=clear_notions,
            ),
        )

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [
            self.get_system_message(
                existing_notions=existing_notions,
                enable_update_notions=update_notions,
                enable_add_notions=add_notions,
                enable_delete_notions=delete_notions,
                enable_clear_notions=clear_notions,
            ),
        ]

        # # Generate a response from the Model (includes running function calls)
        response = model_copy.response(
            messages=messages_for_model,
            tools=self._tools_for_model,
            functions=self._functions_for_model,
        )

        if response.tool_calls is not None and len(response.tool_calls) > 0:
            self.notions_updated = True

        log_debug("Cultural Notion Manager End", center=True)

        return response.content or "No response from model"

    async def acreate_or_update_notions(
        self,
        messages: List[Message],
        existing_notions: List[Dict[str, Any]],
        db: AsyncBaseDb,
        add_notions: bool = True,
        clear_notions: bool = True,
        delete_notions: bool = False,
        update_notions: bool = True,
    ) -> str:
        if self.model is None:
            log_error("No model provided for CultureManager")
            return "No model provided for CultureManager"

        log_debug("CultureManager Start", center=True)

        model_copy = deepcopy(self.model)
        db = cast(AsyncBaseDb, db)

        self.determine_tools_for_model(
            await self._aget_db_tools(
                db=db,
                enable_add_notions=add_notions,
                enable_update_notions=update_notions,
                enable_delete_notions=delete_notions,
                enable_clear_notions=clear_notions,
            ),
        )

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [
            self.get_system_message(
                existing_notions=existing_notions,
                enable_update_notions=update_notions,
                enable_add_notions=add_notions,
                enable_delete_notions=delete_notions,
                enable_clear_notions=clear_notions,
            ),
        ]

        # # Generate a response from the Model (includes running function calls)
        response = await model_copy.aresponse(
            messages=messages_for_model,
            tools=self._tools_for_model,
            functions=self._functions_for_model,
        )

        if response.tool_calls is not None and len(response.tool_calls) > 0:
            self.notions_updated = True

        log_debug("Cultural Notion Manager End", center=True)

        return response.content or "No response from model"

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
        existing_notions: Optional[List[Dict[str, Any]]] = None,
        enable_delete_notions: bool = True,
        enable_clear_notions: bool = True,
        enable_update_notions: bool = True,
        enable_add_notions: bool = True,
    ) -> Message:
        if self.system_message is not None:
            return Message(role="system", content=self.system_message)

        culture_capture_instructions = self.culture_capture_instructions or dedent(
            """\
            WIP
            """
        )

        # -*- Return a system message for the culture manager
        system_prompt_lines = [
            "WIP",
            "",
            culture_capture_instructions,
            "",
        ]
        if enable_add_notions:
            system_prompt_lines.append("  - Decide to add a new cultural notion, using the `add_cultural_notion` tool.")
        if enable_update_notions:
            system_prompt_lines.append(
                "  - Decide to update an existing cultural notion, using the `update_cultural_notion` tool."
            )
        if enable_delete_notions:
            system_prompt_lines.append(
                "  - Decide to delete an existing cultural notion, using the `delete_cultural_notion` tool."
            )
        if enable_clear_notions:
            system_prompt_lines.append(
                "  - Decide to clear all cultural notions, using the `clear_cultural_notions` tool."
            )

        system_prompt_lines += [
            "You can call multiple tools in a single response if needed. ",
            "Only add or update memories if it is necessary to capture key information provided by the user.",
        ]

        if existing_notions and len(existing_notions) > 0:
            system_prompt_lines.append("\n<existing_memories>")
            for existing_notion in existing_notions:
                system_prompt_lines.append(f"ID: {existing_notion['id']}")
                system_prompt_lines.append(f"Notion: {existing_notion['notion']}")
                system_prompt_lines.append("")
            system_prompt_lines.append("</existing_memories>")

        if self.additional_instructions:
            system_prompt_lines.append(self.additional_instructions)

        return Message(role="system", content="\n".join(system_prompt_lines))

    def run_cultural_notion_task(
        self,
        task: str,
        existing_notions: List[Dict[str, Any]],
        db: BaseDb,
        delete_notions: bool = True,
        update_notions: bool = True,
        add_notions: bool = True,
        clear_notions: bool = True,
    ) -> str:
        if self.model is None:
            log_error("No model provided for cultural notion manager")
            return "No model provided for cultural notion manager"

        log_debug("Cultural Notion Manager Start", center=True)

        model_copy = deepcopy(self.model)
        # Update the Model (set defaults, add logit etc.)
        self.determine_tools_for_model(
            self._get_db_tools(
                db,
                task,
                enable_delete_notions=delete_notions,
                enable_clear_notions=clear_notions,
                enable_update_notions=update_notions,
                enable_add_notions=add_notions,
            ),
        )

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [
            self.get_system_message(
                existing_notions,
                enable_delete_notions=delete_notions,
                enable_clear_notions=clear_notions,
                enable_update_notions=update_notions,
                enable_add_notions=add_notions,
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
            self.notions_updated = True

        log_debug("Cultural Notion Manager End", center=True)

        return response.content or "No response from model"

    async def arun_cultural_notion_task(
        self,
        task: str,
        existing_notions: List[Dict[str, Any]],
        db: Union[BaseDb, AsyncBaseDb],
        delete_notions: bool = True,
        clear_notions: bool = True,
        update_notions: bool = True,
        add_notions: bool = True,
    ) -> str:
        if self.model is None:
            log_error("No model provided for cultural notion manager")
            return "No model provided for cultural notion manager"

        log_debug("Cultural Notion Manager Start", center=True)

        model_copy = deepcopy(self.model)
        # Update the Model (set defaults, add logit etc.)
        if isinstance(db, AsyncBaseDb):
            self.determine_tools_for_model(
                await self._aget_db_tools(
                    db,
                    task,
                    enable_delete_notions=delete_notions,
                    enable_clear_notions=clear_notions,
                    enable_update_notions=update_notions,
                    enable_add_notions=add_notions,
                ),
            )
        else:
            self.determine_tools_for_model(
                self._get_db_tools(
                    db,
                    task,
                    enable_delete_notions=delete_notions,
                    enable_clear_notions=clear_notions,
                    enable_update_notions=update_notions,
                    enable_add_notions=add_notions,
                ),
            )

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [
            self.get_system_message(
                existing_notions,
                enable_delete_notions=delete_notions,
                enable_clear_notions=clear_notions,
                enable_update_notions=update_notions,
                enable_add_notions=add_notions,
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
            self.notions_updated = True

        log_debug("Cultural Notion Manager End", center=True)

        return response.content or "No response from model"

    # -*- DB Functions -*-
    def _clear_db_notions(self) -> str:
        """Use this function to clear all cultural notions from the database."""
        try:
            if not self.db:
                raise ValueError("Culture db not initialized")
            self.db = cast(BaseDb, self.db)
            self.db.clear_cultural_notions()
            return "Cultural notions cleared successfully"
        except Exception as e:
            log_warning(f"Error clearing cultural notions in db: {e}")
            return f"Error clearing cultural notions: {e}"

    async def _aclear_db_notions(self) -> str:
        """Use this function to clear all cultural notions from the database."""
        try:
            if not self.db:
                raise ValueError("Culture db not initialized")
            self.db = cast(AsyncBaseDb, self.db)
            await self.db.clear_cultural_notions()
            return "Cultural notions cleared successfully"
        except Exception as e:
            log_warning(f"Error clearing cultural notions in db: {e}")
            return f"Error clearing cultural notions: {e}"

    def _delete_db_notion(self, notion_id: str) -> str:
        """Use this function to delete a cultural notion from the database."""
        try:
            if not self.db:
                raise ValueError("Culture db not initialized")
            self.db = cast(BaseDb, self.db)
            self.db.delete_cultural_notion(id=notion_id)
            return "Cultural notion deleted successfully"
        except Exception as e:
            log_warning(f"Error deleting cultural notion in db: {e}")
            return f"Error deleting cultural notion: {e}"

    async def _adelete_db_notion(self, notion_id: str) -> str:
        """Use this function to delete a cultural notion from the database."""
        try:
            if not self.db:
                raise ValueError("Culture db not initialized")
            self.db = cast(AsyncBaseDb, self.db)
            await self.db.delete_cultural_notion(id=notion_id)
            return "Cultural notion deleted successfully"
        except Exception as e:
            log_warning(f"Error deleting cultural notion in db: {e}")
            return f"Error deleting cultural notion: {e}"

    def _upsert_db_notion(self, notion: CulturalNotion) -> str:
        """Use this function to add a cultural notion to the database."""
        try:
            if not self.db:
                raise ValueError("Culture db not initialized")
            self.db = cast(BaseDb, self.db)
            self.db.upsert_cultural_notion(cultural_notion=notion)
            return "Cultural notion added successfully"
        except Exception as e:
            log_warning(f"Error storing cultural notion in db: {e}")
            return f"Error adding cultural notion: {e}"

    async def _aupsert_db_notion(self, notion: CulturalNotion) -> str:
        """Use this function to add a cultural notion to the database."""
        try:
            if not self.db:
                raise ValueError("Culture db not initialized")
            self.db = cast(AsyncBaseDb, self.db)
            await self.db.upsert_cultural_notion(cultural_notion=notion)
            return "Cultural notion added successfully"
        except Exception as e:
            log_warning(f"Error storing cultural notion in db: {e}")
            return f"Error adding cultural notion: {e}"

    # -* Get DB Tools -*-
    def _get_db_tools(
        self,
        db: Union[BaseDb, AsyncBaseDb],
        enable_add_notions: bool = True,
        enable_update_notions: bool = True,
        enable_delete_notions: bool = True,
        enable_clear_notions: bool = True,
    ) -> List[Callable]:
        def add_cultural_notion(
            name: str,
            summary: Optional[str] = None,
            content: Optional[str] = None,
            categories: Optional[List[str]] = None,
        ) -> str:
            """Use this function to add a cultural notion to the database.
            Args:
                name (str): The name of the cultural notion.
                summary (Optional[str]): The summary of the cultural notion.
                content (Optional[str]): The content of the cultural notion.
                categories (Optional[List[str]]): The categories of the cultural notion (e.g. ["name", "hobbies", "location"]).
            Returns:
                str: A message indicating if the cultural notion was added successfully or not.
            """
            from uuid import uuid4

            try:
                notion_id = str(uuid4())
                db.upsert_cultural_notion(
                    CulturalNotion(
                        id=notion_id,
                        name=name,
                        summary=summary,
                        content=content,
                        categories=categories,
                    )
                )
                log_debug(f"Cultural notion added: {notion_id}")
                return "Cultural notion added successfully"
            except Exception as e:
                log_warning(f"Error storing cultural notion in db: {e}")
                return f"Error adding cultural notion: {e}"

        def update_cultural_notion(
            notion_id: str,
            name: str,
            summary: Optional[str] = None,
            content: Optional[str] = None,
            categories: Optional[List[str]] = None,
        ) -> str:
            """Use this function to update an existing cultural notion in the database.
            Args:
                notion_id (str): The id of the cultural notion to be updated.
                name (str): The name of the cultural notion.
                summary (Optional[str]): The summary of the cultural notion.
                content (Optional[str]): The content of the cultural notion.
                categories (Optional[List[str]]): The categories of the cultural notion (e.g. ["name", "hobbies", "location"]).
            Returns:
                str: A message indicating if the cultural notion was updated successfully or not.
            """
            from agno.db.base import CulturalNotion

            try:
                db.upsert_cultural_notion(
                    CulturalNotion(
                        id=notion_id,
                        name=name,
                        summary=summary,
                        content=content,
                        categories=categories,
                    )
                )
                log_debug("Memory updated")
                return "Memory updated successfully"
            except Exception as e:
                log_warning(f"Error storing memory in db: {e}")
                return f"Error adding memory: {e}"

        def delete_cultural_notion(notion_id: str) -> str:
            """Use this function to delete a single cultural notion from the database.
            Args:
                notion_id (str): The id of the cultural notion to be deleted.
            Returns:
                str: A message indicating if the cultural notion was deleted successfully or not.
            """
            try:
                db.delete_cultural_notion(id=notion_id)
                log_debug("Cultural notion deleted")
                return "Cultural notion deleted successfully"
            except Exception as e:
                log_warning(f"Error deleting cultural notion in db: {e}")
                return f"Error deleting cultural notion: {e}"

        def clear_cultural_notions() -> str:
            """Use this function to remove all (or clear all) cultural knowledge from the database.
            Returns:
                str: A message indicating if the cultural notion was cleared successfully or not.
            """
            db.clear_cultural_notions()
            log_debug("Cultural notion cleared")
            return "Cultural notion cleared successfully"

        functions: List[Callable] = []
        if enable_add_notions:
            functions.append(add_cultural_notion)
        if enable_update_notions:
            functions.append(update_cultural_notion)
        if enable_delete_notions:
            functions.append(delete_cultural_notion)
        if enable_clear_notions:
            functions.append(clear_cultural_notions)
        return functions

    async def _aget_db_tools(
        self,
        db: AsyncBaseDb,
        enable_add_notions: bool = True,
        enable_update_notions: bool = True,
        enable_delete_notions: bool = True,
        enable_clear_notions: bool = True,
    ) -> List[Callable]:
        async def add_cultural_notion(
            name: str,
            summary: Optional[str] = None,
            content: Optional[str] = None,
            categories: Optional[List[str]] = None,
        ) -> str:
            """Use this function to add a cultural notion to the database.
            Args:
                name (str): The name of the cultural notion.
                summary (Optional[str]): The summary of the cultural notion.
                content (Optional[str]): The content of the cultural notion.
                categories (Optional[List[str]]): The categories of the cultural notion (e.g. ["name", "hobbies", "location"]).
            Returns:
                str: A message indicating if the cultural notion was added successfully or not.
            """
            from uuid import uuid4

            try:
                notion_id = str(uuid4())
                await db.upsert_cultural_notion(
                    CulturalNotion(
                        id=notion_id,
                        name=name,
                        summary=summary,
                        content=content,
                        categories=categories,
                    )
                )
                log_debug(f"Cultural notion added: {notion_id}")
                return "Cultural notion added successfully"
            except Exception as e:
                log_warning(f"Error storing cultural notion in db: {e}")
                return f"Error adding cultural notion: {e}"

        async def update_cultural_notion(
            notion_id: str,
            name: str,
            summary: Optional[str] = None,
            content: Optional[str] = None,
            categories: Optional[List[str]] = None,
        ) -> str:
            """Use this function to update an existing cultural notion in the database.
            Args:
                notion_id (str): The id of the cultural notion to be updated.
                name (str): The name of the cultural notion.
                summary (Optional[str]): The summary of the cultural notion.
                content (Optional[str]): The content of the cultural notion.
                categories (Optional[List[str]]): The categories of the cultural notion (e.g. ["name", "hobbies", "location"]).
            Returns:
                str: A message indicating if the cultural notion was updated successfully or not.
            """
            from agno.db.base import CulturalNotion

            try:
                await db.upsert_cultural_notion(
                    CulturalNotion(
                        id=notion_id,
                        name=name,
                        summary=summary,
                        content=content,
                        categories=categories,
                    )
                )
                log_debug("Memory updated")
                return "Memory updated successfully"
            except Exception as e:
                log_warning(f"Error storing memory in db: {e}")
                return f"Error adding memory: {e}"

        async def delete_cultural_notion(notion_id: str) -> str:
            """Use this function to delete a single cultural notion from the database.
            Args:
                notion_id (str): The id of the cultural notion to be deleted.
            Returns:
                str: A message indicating if the cultural notion was deleted successfully or not.
            """
            try:
                await db.delete_cultural_notion(id=notion_id)
                log_debug("Cultural notion deleted")
                return "Cultural notion deleted successfully"
            except Exception as e:
                log_warning(f"Error deleting cultural notion in db: {e}")
                return f"Error deleting cultural notion: {e}"

        async def clear_cultural_notions() -> str:
            """Use this function to remove all (or clear all) cultural knowledge from the database.
            Returns:
                str: A message indicating if the cultural notion was cleared successfully or not.
            """
            await db.clear_cultural_notions()
            log_debug("Cultural notion cleared")
            return "Cultural notion cleared successfully"

        functions: List[Callable] = []
        if enable_add_notions:
            functions.append(add_cultural_notion)
        if enable_update_notions:
            functions.append(update_cultural_notion)
        if enable_delete_notions:
            functions.append(delete_cultural_notion)
        if enable_clear_notions:
            functions.append(clear_cultural_notions)
        return functions
