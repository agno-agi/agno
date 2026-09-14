from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Union

from agno.db.base import BaseDb, ComponentType
from agno.utils.log import log_error

PromptContent = Union[str, List[str]]
PromptSelector = Optional[Union[int, Literal["latest"]]]


def _validate_content(value: Any, field_name: str) -> None:
    if value is None or isinstance(value, str):
        return
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return
    raise ValueError(f"`{field_name}` must be a string or a list of strings")


@dataclass
class Prompt:
    """One reusable text block; every explicit save publishes a new immutable version.

    ``content`` is a string or a list of instruction blocks. ``version`` and
    ``fallback`` describe how one Agent or Team uses this Prompt: they are
    relationship state and never enter the stored component config.
    """

    id: str
    content: Optional[PromptContent] = None
    name: Optional[str] = None
    description: Optional[str] = None
    version: PromptSelector = None
    fallback: Optional[PromptContent] = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("`id` must be a non-empty string")
        _validate_content(self.content, "content")
        _validate_content(self.fallback, "fallback")
        if self.version is not None and self.version != "latest":
            # bool is an int subclass; True would otherwise pass as version 1.
            if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
                raise ValueError("`version` must be a positive integer, 'latest', or None")

    def to_dict(self) -> Dict[str, Any]:
        """Convert the Prompt to its stored component config."""
        config: Dict[str, Any] = {"type": ComponentType.PROMPT.value, "id": self.id}
        if self.content is not None:
            config["content"] = self.content
        if self.name is not None:
            config["name"] = self.name
        if self.description is not None:
            config["description"] = self.description
        return config

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Prompt":
        """Rebuild a Prompt from its stored component config."""
        component_type = data.get("type")
        if component_type is not None and component_type != ComponentType.PROMPT.value:
            raise ValueError(f"Expected a prompt config, got type {component_type!r}")
        return cls(
            id=data.get("id", ""),
            content=data.get("content"),
            name=data.get("name"),
            description=data.get("description"),
        )

    def _to_reference(self) -> Dict[str, Any]:
        """The identity-only form a consumer config stores: the id and the selector it asked for."""
        reference: Dict[str, Any] = {"prompt_id": self.id}
        if self.version is not None:
            reference["version"] = self.version
        return reference

    def save(self, *, db: BaseDb) -> int:
        """Append a new published version of this Prompt.

        Every call appends, so identical content still receives a fresh version
        number; published versions are immutable and no draft is created.

        Args:
            db: The database to save the component and config to.

        Returns:
            The version number of the published config.
        """
        if not isinstance(db, BaseDb):
            raise ValueError("Async databases not yet supported for save(). Use a sync database.")
        if self.content is None:
            raise ValueError("`content` is required to save a Prompt")

        try:
            db.upsert_component(
                component_id=self.id,
                component_type=ComponentType.PROMPT,
                name=self.name if self.name is not None else self.id,
                description=self.description,
            )
            config = db.upsert_config(component_id=self.id, config=self.to_dict(), stage="published")
            return config["version"]
        except Exception as e:
            log_error(f"Error saving Prompt to database: {str(e)}")
            raise

    @classmethod
    def load(
        cls,
        id: str,
        *,
        db: BaseDb,
        version: Optional[int] = None,
        label: Optional[str] = None,
    ) -> Optional["Prompt"]:
        """Load a Prompt by id.

        Without a version or label this reads the current published pointer and
        never falls back to a draft. An explicit version or label returns that
        exact stored config. An id that names a component of another type
        returns None.

        Args:
            id: The id of the Prompt to load.
            db: The database to load the Prompt from.
            version: The exact version to load.
            label: The label of the version to load. Ignored when version is given.

        Returns:
            The Prompt loaded from the database or None if not found.
        """
        # Configs are not typed by themselves; the catalog row is what says this id is a Prompt.
        if db.get_component(component_id=id, component_type=ComponentType.PROMPT) is None:
            return None

        if version is None and label is None:
            data = db.get_current_config(component_id=id)
        else:
            data = db.get_config(component_id=id, version=version, label=label)
        if data is None:
            return None

        config = data.get("config")
        if config is None:
            return None

        # The requested id wins: a config written through the generic component API need not carry one.
        return cls.from_dict({**config, "id": id})

    def delete(self, *, db: BaseDb, hard_delete: bool = False) -> bool:
        """Delete the Prompt component.

        Deletion always refuses while a saved Agent or Team references this
        Prompt; there is no force option.

        Args:
            db: The database to delete the component from.
            hard_delete: Whether to hard delete the component.

        Returns:
            True if the component was deleted, False if there was nothing to delete.

        Raises:
            ComponentDependencyError: If another component references this Prompt.
        """
        if not isinstance(db, BaseDb):
            raise ValueError("Async databases not yet supported for delete(). Use a sync database.")

        return db.delete_component(component_id=self.id, hard_delete=hard_delete, require_no_dependents=True)
