import copy
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Literal, Optional, Union

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
        # Fields are plain attributes and may have been reassigned since construction:
        # re-run the constructor validation before the first write.
        self.__post_init__()
        if self.content is None:
            raise ValueError("`content` is required to save a Prompt")

        try:
            # name=None leaves an existing catalog name alone; a new row defaults to the id.
            db.upsert_component(
                component_id=self.id,
                component_type=ComponentType.PROMPT,
                name=self.name,
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

        # Only a row the catalog types as a Prompt may be deleted here; another component
        # sharing the id is left alone. A hard delete may target an archived Prompt.
        if (
            db.get_component(component_id=self.id, component_type=ComponentType.PROMPT, include_deleted=hard_delete)
            is None
        ):
            return False

        return db.delete_component(component_id=self.id, hard_delete=hard_delete, require_no_dependents=True)


# Host fields that may be bound to a Prompt, in attribution order.
PROMPT_FIELDS = ("system_message", "instructions")


@dataclass
class PromptHandle:
    """The Prompt relationship one host field retains after binding.

    ``prompt`` is the host's own copy. ``bound_value`` is the text placed in the
    public field; once the field no longer holds it, the relationship is stale.
    Resolution state is filled in when the host is loaded from the catalog
    (``published``) or when text on the Prompt itself is used (``inline``).
    """

    prompt: Prompt
    field: str
    bound_value: Optional[PromptContent] = None
    resolved_version: Optional[int] = None
    source: Optional[str] = None
    fallback_reason: Optional[str] = None

    @property
    def selection(self) -> str:
        return "latest" if self.prompt.version == "latest" else "pinned"

    @property
    def requested_version(self) -> Optional[int]:
        return self.prompt.version if isinstance(self.prompt.version, int) else None

    @property
    def fallback(self) -> bool:
        return self.fallback_reason is not None

    @property
    def resolved(self) -> bool:
        return self.source is not None


def _prompt_handles(host: Any) -> Dict[str, PromptHandle]:
    handles = getattr(host, "_prompt_handles", None)
    if handles is None:
        handles = {}
        host._prompt_handles = handles
    return handles


def bind_prompt_field(host: Any, field_name: str, value: Any) -> Any:
    """Bind a constructor value to ``host.<field_name>``.

    A Prompt is copied into the host's retained handles and its content is
    returned for the public field, so the message builders keep reading plain
    text. Any other value is returned unchanged and leaves no handle.
    """
    handles = _prompt_handles(host)
    handles.pop(field_name, None)
    if not isinstance(value, Prompt):
        return value
    if field_name == "system_message":
        if isinstance(value.content, list):
            raise ValueError("`system_message` accepts a Prompt with string content, not a list of blocks")
        if isinstance(value.fallback, list):
            raise ValueError("`system_message` accepts a Prompt with a string fallback, not a list of blocks")
    prompt = copy.deepcopy(value)
    handle = PromptHandle(prompt=prompt, field=field_name, bound_value=prompt.content)
    if prompt.content is not None:
        # Text carried by the Prompt itself is usable as is; a catalog load replaces this.
        handle.source = "inline"
    handles[field_name] = handle
    return prompt.content


def retained_prompt_handle(host: Any, field_name: str) -> Optional[PromptHandle]:
    """The handle bound to ``host.<field_name>``, or None once the field was reassigned."""
    handles = getattr(host, "_prompt_handles", None) or {}
    handle = handles.get(field_name)
    if handle is None:
        return None
    current = getattr(host, field_name, None)
    if current is not handle.bound_value and current != handle.bound_value:
        del handles[field_name]
        return None
    return handle


def copy_prompt_handles(source: Any, target: Any, *, overridden: Iterable[str]) -> None:
    """Give ``target`` its own copies of ``source``'s handles, except for overridden fields."""
    skip = set(overridden)
    for field_name in PROMPT_FIELDS:
        if field_name in skip:
            continue
        handle = retained_prompt_handle(source, field_name)
        if handle is not None:
            _prompt_handles(target)[field_name] = copy.deepcopy(handle)


def require_resolved_prompts(host: Any, host_label: str) -> None:
    """Refuse to run while a bound Prompt has no text; called before registration or any write."""
    for field_name in PROMPT_FIELDS:
        handle = retained_prompt_handle(host, field_name)
        if handle is not None and not handle.resolved:
            raise ValueError(
                f"{host_label} `{field_name}` references Prompt '{handle.prompt.id}' but no content was resolved: "
                f"load the {host_label} from its database or give the Prompt content"
            )
