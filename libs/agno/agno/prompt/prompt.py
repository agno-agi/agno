import copy
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Literal, Optional, Union

from agno.db.base import BaseDb, ComponentType
from agno.exceptions import ComponentPinError, ComponentRehydrationError
from agno.utils.log import log_error, log_warning

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

    ``prompt`` is the host's own copy. ``bound_value`` is a snapshot of the text
    placed in the public field; once the field no longer equals it, whether by
    reassignment or by an in-place edit, the relationship is stale.
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

    @property
    def attributable(self) -> bool:
        """Whether a run records this relationship: catalog text, or the inline fallback that stood in for it."""
        return self.source == "published" or self.fallback


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
    handle = PromptHandle(prompt=prompt, field=field_name, bound_value=copy.deepcopy(prompt.content))
    if prompt.content is not None:
        # Text carried by the Prompt itself is usable as is; a catalog load replaces this.
        handle.source = "inline"
    handles[field_name] = handle
    return prompt.content


def retained_prompt_handle(host: Any, field_name: str) -> Optional[PromptHandle]:
    """The handle bound to ``host.<field_name>``, or None once the field no longer holds the bound text.

    A Prompt assigned to the field after construction is bound on the first
    read of the relationship, exactly as a constructor value is.
    """
    current = getattr(host, field_name, None)
    if isinstance(current, Prompt):
        setattr(host, field_name, bind_prompt_field(host, field_name, current))
        return _prompt_handles(host)[field_name]
    handles = getattr(host, "_prompt_handles", None) or {}
    handle = handles.get(field_name)
    if handle is None:
        return None
    if current != handle.bound_value:
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


def require_resolved_member_prompts(team: Any, host_label: str) -> None:
    """Apply the guard to each direct, already-created member before the leader run.

    Only a static member list is walked, as the save path does: a callable
    member factory is not invoked here, and a nested Team's own members are
    not walked. Each member's dispatcher applies the guard again when it runs.
    """
    members = getattr(team, "members", None)
    if not isinstance(members, list):
        return
    for member in members:
        member_id = getattr(member, "id", None) or getattr(member, "name", None)
        require_resolved_prompts(member, f"{host_label} member {type(member).__name__} '{member_id}'")


# Fixed reasons recorded when lenient loading falls back; tied to the requested selection.
PINNED_VERSION_MISSING = "pinned_version_missing"
NO_CURRENT_VERSION = "no_current_version"


def is_prompt_reference(value: Any) -> bool:
    return isinstance(value, dict) and "prompt_id" in value


def prompt_from_reference(reference: Dict[str, Any], links: Optional[List[Dict[str, Any]]], field_name: str) -> Prompt:
    """Rebuild the selector a stored consumer config references for one field.

    The link row for the field is authoritative: an integer child_version is a
    pin, NULL follows the current published version, and ``meta.fallback`` is
    the consumer's inline fallback. Without a link row the config's own selector
    is used, and an omitted one follows the current version.
    """
    link = next(
        (row for row in links or [] if row.get("link_kind") == "prompt" and row.get("link_key") == field_name),
        None,
    )
    if link is not None:
        prompt_id = link.get("child_component_id") or reference.get("prompt_id")
        version = link.get("child_version")
        fallback = (link.get("meta") or {}).get("fallback")
    else:
        prompt_id = reference.get("prompt_id")
        version = reference.get("version")
        fallback = None
    return Prompt(
        id=prompt_id if isinstance(prompt_id, str) else "",
        version="latest" if version is None else version,
        fallback=fallback,
    )


def bind_prompt_references(config: Dict[str, Any], links: Optional[List[Dict[str, Any]]]) -> None:
    """Replace stored identity references in a host config with Prompt selectors, in place."""
    for field_name in PROMPT_FIELDS:
        if is_prompt_reference(config.get(field_name)):
            config[field_name] = prompt_from_reference(config[field_name], links, field_name)


def _published_config(db: BaseDb, prompt_id: str, version: int) -> Optional[Dict[str, Any]]:
    row = db.get_config(component_id=prompt_id, version=version)
    if row is None or row.get("stage") != "published":
        return None
    return row


def _content_from_row(row: Dict[str, Any], field_name: str, prompt_id: str) -> PromptContent:
    content = Prompt.from_dict({**(row.get("config") or {}), "id": prompt_id}).content
    if content is None:
        raise ValueError(f"Published Prompt '{prompt_id}' version {row.get('version')} has no content")
    if field_name == "system_message" and not isinstance(content, str):
        raise ValueError(f"Prompt '{prompt_id}' holds a list of blocks; `system_message` needs string content")
    return content


def _use_published(handle: PromptHandle, row: Dict[str, Any], version: int, reason: Optional[str]) -> PromptContent:
    content = _content_from_row(row, handle.field, handle.prompt.id)
    handle.resolved_version = version
    handle.source = "published"
    handle.fallback_reason = reason
    handle.bound_value = copy.deepcopy(content)
    return content


def _use_inline(handle: PromptHandle, reason: str) -> PromptContent:
    content = handle.prompt.fallback
    if content is None:
        raise ValueError("inline fallback requested without fallback text")
    handle.resolved_version = None
    handle.source = "inline"
    handle.fallback_reason = reason
    handle.bound_value = copy.deepcopy(content)
    return content


def resolve_prompt_handle(handle: PromptHandle, *, db: BaseDb, strict: bool, host_label: str) -> PromptContent:
    """Resolve one retained handle against published Prompt versions.

    Strict loading refuses any miss. Lenient loading degrades in a bounded,
    recorded way: a missing pin uses the current published version, and a
    missing current version uses the consumer's inline fallback. Malformed
    configs and database errors always propagate.
    """
    prompt = handle.prompt
    label = f"{host_label} `{handle.field}`"
    # The catalog row gates every lookup: a missing, archived, or non-Prompt row has no usable version,
    # so a config stored under the same id by another component type is never read as Prompt text.
    component = db.get_component(component_id=prompt.id, component_type=ComponentType.PROMPT)
    current_version = component.get("current_version") if component is not None else None
    current_row = _published_config(db, prompt.id, current_version) if current_version is not None else None

    if handle.selection == "pinned":
        requested = handle.requested_version
        row = _published_config(db, prompt.id, requested) if component is not None and requested is not None else None
        if row is not None and requested is not None:
            return _use_published(handle, row, requested, None)
        if strict:
            raise ComponentPinError(
                f"{label} pins Prompt '{prompt.id}' at version {requested}, which is not published. "
                f"Restore that version, or bind `{handle.field}` to a published version and save the {host_label}."
            )
        if current_row is not None and current_version is not None:
            log_warning(
                f"{label} pins Prompt '{prompt.id}' at version {requested}, which is not published; "
                f"using the current published version {current_version} instead."
            )
            return _use_published(handle, current_row, current_version, PINNED_VERSION_MISSING)
        if prompt.fallback is not None:
            log_warning(
                f"{label} pins Prompt '{prompt.id}' at version {requested}, which is not published and has no "
                "current published version; using the inline fallback text."
            )
            return _use_inline(handle, PINNED_VERSION_MISSING)
        raise ComponentRehydrationError(
            f"{label} pins Prompt '{prompt.id}' at version {requested}; neither that version nor a current "
            "published version exists and no fallback was given."
        )

    if current_row is not None and current_version is not None:
        return _use_published(handle, current_row, current_version, None)
    if not strict and prompt.fallback is not None:
        log_warning(
            f"{label} follows the latest version of Prompt '{prompt.id}', which has no current published "
            "version; using the inline fallback text."
        )
        return _use_inline(handle, NO_CURRENT_VERSION)
    raise ComponentRehydrationError(
        f"{label} follows the latest version of Prompt '{prompt.id}', which has no current published version."
    )


def resolve_prompt_fields(host: Any, *, db: BaseDb, strict: bool, host_label: str) -> None:
    """Resolve every bound field on a loaded host and place the text in its public field."""
    for field_name in PROMPT_FIELDS:
        handle = retained_prompt_handle(host, field_name)
        if handle is not None:
            setattr(host, field_name, resolve_prompt_handle(handle, db=db, strict=strict, host_label=host_label))


def prompt_links_for_save(host: Any, *, db: BaseDb, host_label: str) -> List[Dict[str, Any]]:
    """Validate every bound Prompt against the catalog and build its link rows.

    Runs before the first host write and changes nothing on the host. An
    omitted selector links the current published version; an explicit pin must
    be published; "latest" stores NULL. The requested selector is kept as is,
    so a handle that fell back at load time is refused until its selector is
    publishable again or the field is rebound. Host saves never publish Prompt
    text.
    """
    links: List[Dict[str, Any]] = []
    for position, field_name in enumerate(PROMPT_FIELDS):
        handle = retained_prompt_handle(host, field_name)
        if handle is None:
            continue
        prompt = handle.prompt
        label = f"{host_label} `{field_name}`"
        component = db.get_component(component_id=prompt.id, component_type=ComponentType.PROMPT)
        if component is None:
            raise ValueError(
                f"{label} references Prompt '{prompt.id}', which is not an active Prompt component. "
                "Call Prompt.save() first."
            )
        current_version = component.get("current_version")
        if prompt.version == "latest":
            target_version = current_version
            child_version = None
        else:
            target_version = prompt.version if prompt.version is not None else current_version
            child_version = target_version
        row = _published_config(db, prompt.id, target_version) if target_version is not None else None
        if row is None:
            if target_version is not None:
                raise ValueError(
                    f"{label} pins Prompt '{prompt.id}' at version {target_version}, which is not published. Only "
                    f"published Prompt versions can be linked: restore that version, or bind `{field_name}` to one."
                )
            raise ValueError(
                f"{label} references Prompt '{prompt.id}', which has no published version. Only published Prompt "
                "versions can be linked; call Prompt.save() first."
            )
        if prompt.content is not None and prompt.content != (row.get("config") or {}).get("content"):
            raise ValueError(
                f"{label} carries Prompt '{prompt.id}' content that differs from published version "
                f"{row.get('version')}. Host saves never publish Prompt text; call Prompt.save() to publish "
                "it explicitly."
            )
        link: Dict[str, Any] = {
            "link_kind": "prompt",
            "link_key": field_name,
            "child_component_id": prompt.id,
            "child_version": child_version,
            "position": position,
        }
        if prompt.fallback is not None:
            link["meta"] = {"fallback": prompt.fallback}
        links.append(link)
    return links


def pin_stored_prompt_references(config: Dict[str, Any], links: List[Dict[str, Any]]) -> None:
    """Write each integer link pin into the matching reference of a serialized host config, in place.

    The saved reference then records the same pin as its link row, so a config
    version written later without Prompt links still loads pinned. The live
    handle is left alone until the save has succeeded.
    """
    for link in links:
        reference = config.get(link["link_key"])
        if isinstance(reference, dict) and is_prompt_reference(reference) and link["child_version"] is not None:
            reference["version"] = link["child_version"]


def pin_saved_prompt_selectors(host: Any, links: List[Dict[str, Any]]) -> None:
    """Pin each omitted selector to the version its link row stored; called only after the host save succeeded."""
    for link in links:
        handle = retained_prompt_handle(host, link["link_key"])
        if handle is not None and handle.prompt.version is None:
            handle.prompt.version = link["child_version"]
