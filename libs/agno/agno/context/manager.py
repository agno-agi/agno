import re
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from textwrap import dedent
from typing import Any, Dict, List, Optional, Tuple, Union, cast
from uuid import uuid4

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.schemas.context import ContextItem
from agno.models.base import Model
from agno.models.message import Message
from agno.models.utils import get_model
from agno.utils.log import log_debug


@dataclass
class ContextManager:
    """Context Manager for managing prompt content
     **Context is an experimental feature**
    """

    # Model used for optimization
    model: Optional[Model] = None

    # The database to store context items
    db: Optional[Union[AsyncBaseDb, BaseDb]] = None

    # Optimization instructions
    optimization_instructions: Optional[str] = None

    # Strict mode: if True, fail when variables are missing, if False, leave placeholders
    strict_mode: bool = False

    # In-memory storage (used when db is None)
    _items: Dict[str, ContextItem] = field(default_factory=dict, repr=False)

    def __init__(
        self,
        model: Optional[Union[Model, str]] = None,
        db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
        optimization_instructions: Optional[str] = None,
        strict_mode: bool = False,
    ):
        self.model = get_model(model) if model else None
        self.db = db
        self.optimization_instructions = optimization_instructions
        self.strict_mode = strict_mode
        self._items = {}

    def create(
        self,
        name: str,
        content: str,
        label: Optional[str] = None,
        description: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """Create a new context item (content)

        Args:
            name (str): Unique identifier for the content
            content (str): The prompt content
            label (Optional[str]): Label like "production", "development", "optimized"
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
            label=label,
            description=description,
            variables=variables,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            **kwargs,
        )

        # Store in DB or in-memory
        if self.db:
            self.db = cast(BaseDb, self.db)
            self.db.upsert_context_item(item)
        else:
            # Store in-memory with key as name:label
            key = f"{name}:{label}" if label else name
            self._items[key] = item

        log_debug(f"Created context item: {item.id} ({name})")
        return item.id

    async def acreate(
        self,
        name: str,
        content: str,
        label: Optional[str] = None,
        description: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """Async version of create"""
        variables = self._extract_variables(content)

        item = ContextItem(
            id=str(uuid4()),
            name=name,
            content=content,
            label=label,
            description=description,
            variables=variables,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            **kwargs,
        )

        if self.db:
            self.db = cast(AsyncBaseDb, self.db)
            await self.db.upsert_context_item(item)
        else:
            key = f"{name}:{label}" if label else name
            self._items[key] = item

        log_debug(f"Created context item: {item.id} ({name})")
        return item.id

    def get(self, context_name: str, label: Optional[str] = None, **variables: Any) -> str:
        """Get and render a content

        Args:
            context_name (str): Name of the context
            label (Optional[str]): Label to filter by
            **variables: Variables to fill in the content

        Returns:
            str: Rendered content

        Raises:
            ValueError: If content not found or variables are missing in strict mode
        """
        # Fetch item from DB or memory
        item = self._get_item(context_name, label)

        if not item:
            raise ValueError(f"Content '{context_name}' with label '{label}' not found")

        # Verify variables if strict mode
        if self.strict_mode:
            is_valid, missing = self._verify_variables(item.content, variables)
            if not is_valid:
                raise ValueError(f"Missing required variables: {missing}")

        # Render content
        return self._render(item.content, **variables)

    async def aget(self, context_name: str, label: Optional[str] = None, **variables: Any) -> str:
        """Async version of get"""
        item = await self._aget_item(context_name, label)

        if not item:
            raise ValueError(f"Content '{context_name}' with label '{label}' not found")

        if self.strict_mode:
            is_valid, missing = self._verify_variables(item.content, variables)
            if not is_valid:
                raise ValueError(f"Missing required variables: {missing}")

        return self._render(item.content, **variables)

    def update(
        self,
        context_name: str,
        label: Optional[str] = None,
        content: Optional[str] = None,
        description: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Update an existing context item

        Args:
            context_name (str): Name of the context to update
            label (Optional[str]): Label to filter by
            content (Optional[str]): New content
            description (Optional[str]): New description
            **kwargs: Other fields to update
        """
        item = self._get_item(context_name, label)
        if not item:
            raise ValueError(f"Content '{context_name}' with label '{label}' not found")

        # Update fields
        if content:
            item.content = content
            item.variables = self._extract_variables(content)
        if description:
            item.description = description
        for key, value in kwargs.items():
            if hasattr(item, key):
                setattr(item, key, value)

        item.updated_at = datetime.now(timezone.utc)

        # Save back
        if self.db:
            self.db = cast(BaseDb, self.db)
            self.db.upsert_context_item(item)
        else:
            key = f"{context_name}:{label}" if label else context_name
            self._items[key] = item

        log_debug(f"Updated context item: {item.id} ({context_name})")

    async def aupdate(
        self,
        context_name: str,
        label: Optional[str] = None,
        content: Optional[str] = None,
        description: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Async version of update"""
        item = await self._aget_item(context_name, label)
        if not item:
            raise ValueError(f"Content '{context_name}' with label '{label}' not found")

        if content:
            item.content = content
            item.variables = self._extract_variables(content)
        if description:
            item.description = description
        for key, value in kwargs.items():
            if hasattr(item, key):
                setattr(item, key, value)

        item.updated_at = datetime.now(timezone.utc)

        if self.db:
            self.db = cast(AsyncBaseDb, self.db)
            await self.db.upsert_context_item(item)
        else:
            key = f"{context_name}:{label}" if label else context_name
            self._items[key] = item

        log_debug(f"Updated context item: {item.id} ({context_name})")

    def delete(self, context_name: str, label: Optional[str] = None) -> None:
        """Delete a context item

        Args:
            context_name (str): Name of the context to delete
            label (Optional[str]): Label to filter by
        """
        item = self._get_item(context_name, label)
        if not item:
            raise ValueError(f"Content '{context_name}' with label '{label}' not found")

        if self.db:
            self.db = cast(BaseDb, self.db)
            self.db.delete_context_item(item.id)
        else:
            key = f"{context_name}:{label}" if label else context_name
            del self._items[key]

        log_debug(f"Deleted context item: {item.id} ({context_name})")

    async def adelete(self, context_name: str, label: Optional[str] = None) -> None:
        """Async version of delete"""
        item = await self._aget_item(context_name, label)
        if not item:
            raise ValueError(f"Content '{context_name}' with label '{label}' not found")

        if self.db:
            self.db = cast(AsyncBaseDb, self.db)
            await self.db.delete_context_item(item.id)
        else:
            key = f"{context_name}:{label}" if label else context_name
            del self._items[key]

        log_debug(f"Deleted context item: {item.id} ({context_name})")

    def list(self, label: Optional[str] = None) -> List[ContextItem]:
        """List all context items

        Args:
            label (Optional[str]): Filter by label

        Returns:
            List[ContextItem]: List of context items
        """
        if self.db:
            self.db = cast(BaseDb, self.db)
            return self.db.get_all_context_items(label=label)
        else:
            items = list(self._items.values())
            if label:
                items = [i for i in items if i.label == label]
            return items

    async def alist(self, label: Optional[str] = None) -> List[ContextItem]:
        """Async version of list"""
        if self.db:
            self.db = cast(AsyncBaseDb, self.db)
            return await self.db.get_all_context_items(label=label)
        else:
            items = list(self._items.values())
            if label:
                items = [i for i in items if i.label == label]
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
        context_name: str,
        label: Optional[str] = None,
        optimization_instructions: Optional[str] = None,
        create_new_version: bool = True,
        new_label: Optional[str] = None,
    ) -> str:
        """Optimize a content

        Args:
            context_name (str): Name of the context to optimize
            label (Optional[str]): Label to filter by
            optimization_instructions (Optional[str]): Custom instructions, overrides default
            create_new_version (bool): If True, create new version; if False, update in place
            new_label (Optional[str]): Label for the new version (if create_new_version=True)

        Returns:
            str: The optimized content

        Raises:
            ValueError: If content not found or model not provided
        """
        if not self.model:
            raise ValueError("Model is required for optimization. Please provide a model when initializing ContextManager.")

        # Get the item
        item = self._get_item(context_name, label)
        if not item:
            raise ValueError(f"Content '{context_name}' with label '{label}' not found")

        # Get optimization instructions
        instructions = optimization_instructions or self.optimization_instructions or self._get_default_optimization_instructions()

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
            """).strip()
        )

        # Call model
        model_copy = deepcopy(self.model)
        response = model_copy.response(messages=[system_message])

        optimized_content = response.content.strip() if response.content else item.content

        # Store the optimized version
        if create_new_version:
            # Create new version
            new_item_label = new_label or f"{label or 'default'}_optimized"
            self.create(
                name=context_name,
                content=optimized_content,
                label=new_item_label,
                description=item.description,
                version=item.version + 1,
                parent_id=item.id,
                optimization_notes=optimization_instructions or "Optimized using default instructions",
            )
            log_debug(f"Created optimized version: {context_name} (label: {new_item_label})")
        else:
            # Update in place
            self.update(
                context_name=context_name,
                label=label,
                content=optimized_content,
                optimization_notes=optimization_instructions or "Optimized using default instructions",
            )
            log_debug(f"Updated content in place: {context_name}")

        return optimized_content

    async def aoptimize(
        self,
        context_name: str,
        label: Optional[str] = None,
        optimization_instructions: Optional[str] = None,
        create_new_version: bool = True,
        new_label: Optional[str] = None,
    ) -> str:
        """Async version of optimize"""
        if not self.model:
            raise ValueError("Model is required for optimization. Please provide a model when initializing ContextManager.")

        item = await self._aget_item(context_name, label)
        if not item:
            raise ValueError(f"Content '{context_name}' with label '{label}' not found")

        instructions = optimization_instructions or self.optimization_instructions or self._get_default_optimization_instructions()

        system_message = Message(
            role="system",
            content=dedent(f"""
                {instructions}

                Current content:
                ```
                {item.content}
                ```

                Provide only the optimized content, nothing else.
            """).strip()
        )

        model_copy = deepcopy(self.model)
        response = await model_copy.aresponse(messages=[system_message])

        optimized_content = response.content.strip() if response.content else item.content

        if create_new_version:
            new_item_label = new_label or f"{label or 'default'}_optimized"
            await self.acreate(
                name=context_name,
                content=optimized_content,
                label=new_item_label,
                description=item.description,
                version=item.version + 1,
                parent_id=item.id,
                optimization_notes=optimization_instructions or "Optimized using default instructions",
            )
            log_debug(f"Created optimized version: {context_name} (label: {new_item_label})")
        else:
            await self.aupdate(
                context_name=context_name,
                label=label,
                content=optimized_content,
                optimization_notes=optimization_instructions or "Optimized using default instructions",
            )
            log_debug(f"Updated content in place: {context_name}")

        return optimized_content

    def _get_item(self, name: str, label: Optional[str] = None) -> Optional[ContextItem]:
        """Get a single context item from DB or memory"""
        if self.db:
            self.db = cast(BaseDb, self.db)
            items = self.db.get_all_context_items(name=name, label=label)
            return items[0] if items else None
        else:
            key = f"{name}:{label}" if label else name
            return self._items.get(key)

    async def _aget_item(self, name: str, label: Optional[str] = None) -> Optional[ContextItem]:
        """Async version of _get_item"""
        if self.db:
            self.db = cast(AsyncBaseDb, self.db)
            items = await self.db.get_all_context_items(name=name, label=label)
            return items[0] if items else None
        else:
            key = f"{name}:{label}" if label else name
            return self._items.get(key)

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
        pattern = r'\{(\w+)\}'
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
