import re
from copy import deepcopy
from dataclasses import dataclass, field
from os import getenv
from textwrap import dedent
from typing import Any, Dict, List, Optional, Tuple, Union, cast
from uuid import uuid4

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.schemas.context import ContextItem
from agno.models.base import Model
from agno.models.message import Message
from agno.models.utils import get_model
from agno.utils.log import log_debug, log_error, set_log_level_to_debug, set_log_level_to_info


@dataclass
class ContextManager:
    """Context Manager for managing prompt content

    **Context is an experimental feature**
    """

    # Model used for optimization
    model: Optional[Model] = None

    # Optimization instructions
    optimization_instructions: Optional[str] = None

    # Strict mode: if True, fail when variables are missing, if False, leave placeholders
    strict_mode: bool = False

    # The database to store context items
    db: Optional[Union[BaseDb, AsyncBaseDb]] = None

    # Enable debug mode
    debug_mode: bool = False

    # In-memory storage (used when db is None)
    _items: Dict[str, ContextItem] = field(default_factory=dict, repr=False)

    def __init__(
        self,
        model: Optional[Union[Model, str]] = None,
        optimization_instructions: Optional[str] = None,
        strict_mode: bool = False,
        db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
        debug_mode: bool = False,
    ):
        self.model = model  # type: ignore[assignment]
        self.optimization_instructions = optimization_instructions
        self.strict_mode = strict_mode
        self.db = db
        self.debug_mode = debug_mode
        self._items = {}
        self._get_models()

    def _get_models(self) -> None:
        if self.model is not None:
            self.model = get_model(self.model)

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

    def create(
        self,
        name: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        description: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """Create a new context item (content)

        Args:
            name (str): Unique identifier for the content
            content (str): The prompt content
            metadata (Optional[Dict[str, Any]]): Metadata for the content
            description (Optional[str]): Description of the content

        Returns:
            str: The ID of the created context item
        """
        # Extract variables from content
        variables = self._extract_variables(content)

        # Create ContextItem
        item = ContextItem(
            id=str(uuid4()),
            name=name,
            content=content,
            metadata=metadata,
            description=description,
            variables=variables,
            **kwargs,
        )

        # Store in DB or in-memory
        if self.db:
            self.db = cast(BaseDb, self.db)
            self.db.upsert_context_item(item)
        else:
            # Store in-memory with key as id
            self._items[item.id] = item  # type: ignore[index]

        log_debug(f"Created context item: {item.id} ({name})")
        return item.id  # type: ignore[return-value]

    async def acreate(
        self,
        name: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        description: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """Async version of create"""
        variables = self._extract_variables(content)

        # Create ContextItem
        item = ContextItem(
            id=str(uuid4()),
            name=name,
            content=content,
            metadata=metadata,
            description=description,
            variables=variables,
            **kwargs,
        )

        if self.db:
            self.db = cast(AsyncBaseDb, self.db)
            await self.db.upsert_context_item(item)
        else:
            self._items[item.id] = item  # type: ignore[index]

        log_debug(f"Created context item: {item.id} ({name})")
        return item.id  # type: ignore[return-value]

    def get(self, name: str, metadata: Optional[Dict[str, Any]] = None, **variables: Any) -> str:
        """Get and render a content

        Args:
            name (str): Name of the context
            metadata (Optional[Dict[str, Any]]): Metadata to filter by
            **variables: Variables to fill in the content

        Returns:
            str: Rendered content

        Raises:
            ValueError: If content not found or variables are missing in strict mode
        """
        # Fetch item from DB or memory
        item = self._get_item(name, metadata)

        if not item:
            raise ValueError(f"Content '{name}' with metadata '{metadata}' not found")

        # Verify variables if strict mode
        if self.strict_mode:
            is_valid, missing = self._verify_variables(item.content, variables)
            if not is_valid:
                raise ValueError(f"Missing required variables: {missing}")

        # Render content
        return self._render(item.content, **variables)

    async def aget(self, name: str, metadata: Optional[Dict[str, Any]] = None, **variables: Any) -> str:
        """Async version of get"""
        item = await self._aget_item(name, metadata)

        if not item:
            raise ValueError(f"Content '{name}' with metadata '{metadata}' not found")

        if self.strict_mode:
            is_valid, missing = self._verify_variables(item.content, variables)
            if not is_valid:
                raise ValueError(f"Missing required variables: {missing}")

        return self._render(item.content, **variables)

    def update(
        self,
        name: str,
        metadata: Optional[Dict[str, Any]] = None,
        content: Optional[str] = None,
        description: Optional[str] = None,
        new_metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """Update an existing context item

        Args:
            name (str): Name of the context to update
            metadata (Optional[Dict[str, Any]]): Metadata to filter by
            content (Optional[str]): New content
            description (Optional[str]): New description
            new_metadata (Optional[Dict[str, Any]]): New metadata to set
            **kwargs: Other fields to update
        """
        item = self._get_item(name, metadata)
        if not item:
            raise ValueError(f"Content '{name}' with metadata '{metadata}' not found")

        # Update fields
        if content:
            item.content = content
            item.variables = self._extract_variables(content)
        if description:
            item.description = description
        if new_metadata is not None:
            item.metadata = new_metadata
        for key, value in kwargs.items():
            if hasattr(item, key):
                setattr(item, key, value)

        item.bump_updated_at()

        # Save back
        if self.db:
            self.db = cast(BaseDb, self.db)
            self.db.upsert_context_item(item)
        else:
            self._items[item.id] = item  # type: ignore[index]

        log_debug(f"Updated context item: {item.id} ({name})")

    async def aupdate(
        self,
        name: str,
        metadata: Optional[Dict[str, Any]] = None,
        content: Optional[str] = None,
        description: Optional[str] = None,
        new_metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """Async version of update"""
        item = await self._aget_item(name, metadata)
        if not item:
            raise ValueError(f"Content '{name}' with metadata '{metadata}' not found")

        if content:
            item.content = content
            item.variables = self._extract_variables(content)
        if description:
            item.description = description
        if new_metadata is not None:
            item.metadata = new_metadata
        for key, value in kwargs.items():
            if hasattr(item, key):
                setattr(item, key, value)

        item.bump_updated_at()

        if self.db:
            self.db = cast(AsyncBaseDb, self.db)
            await self.db.upsert_context_item(item)
        else:
            self._items[item.id] = item  # type: ignore[index]

        log_debug(f"Updated context item: {item.id} ({name})")

    def delete(self, name: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Delete a context item

        Args:
            name (str): Name of the context to delete
            metadata (Optional[Dict[str, Any]]): Metadata to filter by
        """
        item = self._get_item(name, metadata)
        if not item:
            raise ValueError(f"Content '{name}' with metadata '{metadata}' not found")

        if self.db:
            self.db = cast(BaseDb, self.db)
            self.db.delete_context_item(item.id)  # type: ignore[arg-type]
        else:
            del self._items[item.id]  # type: ignore[arg-type]

        log_debug(f"Deleted context item: {item.id} ({name})")

    async def adelete(self, name: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Async version of delete"""
        item = await self._aget_item(name, metadata)
        if not item:
            raise ValueError(f"Content '{name}' with metadata '{metadata}' not found")

        if self.db:
            self.db = cast(AsyncBaseDb, self.db)
            await self.db.delete_context_item(item.id)  # type: ignore[arg-type]
        else:
            del self._items[item.id]  # type: ignore[arg-type]

        log_debug(f"Deleted context item: {item.id} ({name})")

    def list(self, metadata: Optional[Dict[str, Any]] = None) -> List[ContextItem]:
        """List all context items

        Args:
            metadata (Optional[Dict[str, Any]]): Filter by metadata

        Returns:
            List[ContextItem]: List of context items
        """
        if self.db:
            self.db = cast(BaseDb, self.db)
            result = self.db.get_all_context_items(metadata=metadata)
            return result if result is not None else []
        else:
            items = list(self._items.values())
            if metadata:
                items = [i for i in items if self._metadata_contains(i.metadata, metadata)]
            return items

    async def alist(self, metadata: Optional[Dict[str, Any]] = None) -> List[ContextItem]:
        """Async version of list"""
        if self.db:
            self.db = cast(AsyncBaseDb, self.db)
            result = await self.db.get_all_context_items(metadata=metadata)
            return result if result is not None else []
        else:
            items = list(self._items.values())
            if metadata:
                items = [i for i in items if self._metadata_contains(i.metadata, metadata)]
            return items

    def clear(self) -> None:
        """Clear all context items"""
        if self.db:
            self.db = cast(BaseDb, self.db)
            self.db.clear_context_items()
        else:
            self._items.clear()

        log_debug("Cleared all context items")

    async def aclear(self) -> None:
        """Async version of clear"""
        if self.db:
            self.db = cast(AsyncBaseDb, self.db)
            await self.db.clear_context_items()
        else:
            self._items.clear()

        log_debug("Cleared all context items")

    def optimize(
        self,
        name: str,
        metadata: Optional[Dict[str, Any]] = None,
        optimization_instructions: Optional[str] = None,
        create_new_version: bool = True,
        new_metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Optimize a content

        Args:
            name (str): Name of the context to optimize
            metadata (Optional[Dict[str, Any]]): Metadata to filter by
            optimization_instructions (Optional[str]): Custom instructions, overrides default
            create_new_version (bool): If True, create new version; if False, update in place
            new_metadata (Optional[Dict[str, Any]]): Metadata for the new version (if create_new_version=True)

        Returns:
            str: The optimized content

        Raises:
            ValueError: If content not found or model not provided
        """
        # Get the item
        item = self._get_item(name, metadata)
        if not item:
            raise ValueError(f"Content '{name}' with metadata '{metadata}' not found")

        # Get optimization instructions
        instructions = (
            optimization_instructions or self.optimization_instructions or self._get_default_optimization_instructions()
        )

        # Build prompt
        system_message = Message(
            role="system",
            content=dedent(f"""
                {instructions}

                Current content:
                ```
                {item.content}
                ```

                Provide only the optimized content, nothing else.
            """).strip(),
        )

        # Call model
        model_copy = deepcopy(self.get_model())
        response = model_copy.response(messages=[system_message])

        optimized_content = response.content.strip() if response.content else item.content

        # Store the optimized version
        if create_new_version:
            # Create new version
            new_item_metadata = new_metadata or {**(metadata or {}), "optimized": True}
            self.create(
                name=name,
                content=optimized_content,
                metadata=new_item_metadata,
                description=item.description,
                version=item.version + 1,
                parent_id=item.id,
                optimization_notes=optimization_instructions or "Optimized using default instructions",
            )
            log_debug(f"Created optimized version: {name} (metadata: {new_item_metadata})")
        else:
            # Update in place
            self.update(
                name=name,
                metadata=metadata,
                content=optimized_content,
                optimization_notes=optimization_instructions or "Optimized using default instructions",
            )
            log_debug(f"Updated content in place: {name}")

        return optimized_content

    async def aoptimize(
        self,
        name: str,
        metadata: Optional[Dict[str, Any]] = None,
        optimization_instructions: Optional[str] = None,
        create_new_version: bool = True,
        new_metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Async version of optimize"""
        item = await self._aget_item(name, metadata)
        if not item:
            raise ValueError(f"Content '{name}' with metadata '{metadata}' not found")

        instructions = (
            optimization_instructions or self.optimization_instructions or self._get_default_optimization_instructions()
        )

        system_message = Message(
            role="system",
            content=dedent(f"""
                {instructions}

                Current content:
                ```
                {item.content}
                ```

                Provide only the optimized content, nothing else.
            """).strip(),
        )

        model_copy = deepcopy(self.get_model())
        response = await model_copy.aresponse(messages=[system_message])

        optimized_content = response.content.strip() if response.content else item.content

        if create_new_version:
            new_item_metadata = new_metadata or {**(metadata or {}), "optimized": True}
            await self.acreate(
                name=name,
                content=optimized_content,
                metadata=new_item_metadata,
                description=item.description,
                version=item.version + 1,
                parent_id=item.id,
                optimization_notes=optimization_instructions or "Optimized using default instructions",
            )
            log_debug(f"Created optimized version: {name} (metadata: {new_item_metadata})")
        else:
            await self.aupdate(
                name=name,
                metadata=metadata,
                content=optimized_content,
                optimization_notes=optimization_instructions or "Optimized using default instructions",
            )
            log_debug(f"Updated content in place: {name}")

        return optimized_content

    def _metadata_contains(self, item_metadata: Optional[Dict[str, Any]], filter_metadata: Dict[str, Any]) -> bool:
        """Check if item_metadata contains all key-value pairs from filter_metadata"""
        if item_metadata is None:
            return False
        for key, value in filter_metadata.items():
            if key not in item_metadata or item_metadata[key] != value:
                return False
        return True

    def _get_item(self, name: str, metadata: Optional[Dict[str, Any]] = None) -> Optional[ContextItem]:
        """Get a single context item from DB or memory"""
        if self.db:
            self.db = cast(BaseDb, self.db)
            items = self.db.get_all_context_items(name=name, metadata=metadata)
            return items[0] if items else None
        else:
            # Search through items by name and optionally metadata
            for item in self._items.values():
                if item.name == name:
                    if metadata is None or self._metadata_contains(item.metadata, metadata):
                        return item
            return None

    async def _aget_item(self, name: str, metadata: Optional[Dict[str, Any]] = None) -> Optional[ContextItem]:
        """Async version of _get_item"""
        if self.db:
            self.db = cast(AsyncBaseDb, self.db)
            items = await self.db.get_all_context_items(name=name, metadata=metadata)
            return items[0] if items else None
        else:
            # Search through items by name and optionally metadata
            for item in self._items.values():
                if item.name == name:
                    if metadata is None or self._metadata_contains(item.metadata, metadata):
                        return item
            return None

    def _render(self, content: str, **variables: Any) -> str:
        """Render content with variables using safe formatting logic

        Uses Python's string formatting with {variable} syntax.
        In non-strict mode, missing variables remain as {variable}
        """
        try:
            if self.strict_mode:
                return content.format(**variables)
            else:
                return self._safe_format(content, **variables)
        except KeyError as e:
            if self.strict_mode:
                raise ValueError(f"Missing required variable: {e}")
            return content

    def _safe_format(self, content: str, **variables: Any) -> str:
        """Safely format content, keeping missing variables as {variable}

        Args:
            content (str): Content with {variable} placeholders
            **variables: Variables to substitute

        Returns:
            str: Formatted content with missing variables preserved
        """
        result = content
        all_vars = self._extract_variables(content)

        for var in all_vars:
            if var in variables:
                # Replace this specific variable
                result = result.replace(f"{{{var}}}", str(variables[var]))

        return result

    def _extract_variables(self, content: str) -> List[str]:
        """Extract variable names from content

        Finds all {variable} placeholders in the content
        """
        pattern = r"\{(\w+)\}"
        matches = re.findall(pattern, content)
        return list(set(matches))

    def _verify_variables(self, content: str, variables: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Verify all required variables are provided

        Args:
            content (str): The content to check
            variables (Dict[str, Any]): Provided variables

        Returns:
            Tuple[bool, List[str]]: (is_valid, missing_variables)
        """
        required = self._extract_variables(content)
        provided = set(variables.keys())
        missing = [var for var in required if var not in provided]
        return len(missing) == 0, missing

    def _get_default_optimization_instructions(self) -> str:
        """Get default optimization instructions"""
        return dedent("""
            You are a prompt optimization expert. Your task is to improve the given content while preserving its core intent and placeholder variables.

            Optimization goals:
            - Clarity: Make instructions clearer and more specific
            - Conciseness: Remove redundancy without losing meaning
            - Effectiveness: Improve the content's ability to guide the agent
            - Structure: Organize information logically
            - Preserve variables: Keep all {variable} placeholders intact

            Return only the optimized content, nothing else.
        """).strip()
