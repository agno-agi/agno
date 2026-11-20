import asyncio
import base64
import hashlib
import json
import posixpath
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple, Union

import yaml

from agno.skills.errors import SkillError
from agno.skills.loaders.base import SkillLoader
from agno.skills.skill import Skill
from agno.skills.validator import _validate_description, _validate_name
from agno.utils.log import log_debug, log_warning

SKILLS_EXTENSION = "io.modelcontextprotocol/skills"

# Per-skill limits every conforming host must accept.
MAX_SKILL_RESOURCES = 512
MAX_SKILL_BYTES = 16 * 1024 * 1024

_LIST_MAX_PAGES = 250
_SKILL_MD = "SKILL.md"
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


class SkillVerificationError(SkillError):
    """Raised when MCP-served skill content does not match the entry the server published."""

    pass


class _ContentMismatch(SkillVerificationError):
    """A listed file's bytes do not match its digest or size."""

    pass


@dataclass
class _HeldEntry:
    """A validated `skills/list` / `skills/get` entry for one skill."""

    uri: str
    frontmatter: Dict[str, Any]
    # resource uri -> (digest, size); None when the server marks the skill "dynamic"
    resources: Optional[Dict[str, Tuple[str, int]]]
    retrieved_bytes: int = field(default=0)

    @property
    def root(self) -> str:
        return self.uri[: -len(_SKILL_MD)]


class MCPSkills(SkillLoader):
    """Loads skills served by an MCP server through the Skills extension (`io.modelcontextprotocol/skills`).

    Listing happens on the first async run: only the entries from `skills/list`
    (and `skills/get` for `skill_uris`) are fetched. `SKILL.md` and supporting
    files are read lazily with `resources/read` when the agent asks for them, and
    every read is verified against the entry's digest and size.

    MCP-served skills are untrusted: they are tagged with their origin in the
    model's context, their scripts are never executed, and `allowed-tools` is ignored.

    The loader owns its MCP client: it connects on demand, and the agent or team
    closes it at the end of each run.

    Args:
        command: Command that starts a stdio MCP server.
        url: URL of a Streamable HTTP or SSE MCP server.
        transport: "stdio", "sse" or "streamable-http". Inferred from `command`/`url` when omitted.
        server_params: Connection parameters (StdioServerParameters, SSEClientParams or StreamableHTTPClientParams).
        env: Environment variables for a stdio server.
        headers: Static HTTP headers for HTTP transports.
        timeout_seconds: Read timeout for MCP requests.
        label: Host-assigned name for the server, without "/". Skill names are
            namespaced as `<label>/<skill-path>`. Defaults to a name derived from `command` or `url`.
        skill_uris: `SKILL.md` URIs to load with `skills/get` in addition to the
            listing, for skills a server does not enumerate.
        allow_dynamic: Load skills whose content the server marks "dynamic". Their
            content cannot be verified, so they are skipped by default.
        gated_tools: Names of the agent's own tools that execute code, in addition to agno's
            built-in execution tools (ShellTools, PythonTools, ...). Once a run loads a skill
            from this server, calls to these tools require confirmation for the rest of the run.
        gate_all_tools: Require confirmation for every other tool, not only execution tools,
            once a run loads a skill from this server.

    The gate covers the tools of the agent or team that loads the skill. A team's members
    run separately and are not gated: give `MCPSkills` to the member that runs code, or set
    `requires_confirmation` on the members' execution tools.
    """

    requires_async = True

    def __init__(
        self,
        command: Optional[str] = None,
        *,
        url: Optional[str] = None,
        transport: Optional[Literal["stdio", "sse", "streamable-http"]] = None,
        server_params: Optional[Any] = None,
        env: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, Any]] = None,
        timeout_seconds: float = 10,
        label: Optional[str] = None,
        skill_uris: Optional[List[str]] = None,
        allow_dynamic: bool = False,
        gated_tools: Optional[List[str]] = None,
        gate_all_tools: bool = False,
    ):
        if not (command or url or server_params):
            raise ValueError("MCPSkills needs a command, url or server_params")
        # Imported here: `agno.skills` is imported by every Agent, and these modules require the `mcp` extra.
        from agno.tools.mcp.mcp import create_mcp_client
        from agno.utils.mcp import get_default_toolkit_name

        # The Skills extension is only advertised on protocol revision 2026-07-28, which "auto" negotiates.
        self._client: Any = create_mcp_client(
            command,
            url=url,
            transport=transport,
            server_params=server_params,
            env=env,
            headers=headers,
            timeout_seconds=timeout_seconds,
            protocol_mode="auto",
        )
        self._connected = False
        self._connection_lock: Optional[asyncio.Lock] = None

        self.label: str = label or get_default_toolkit_name(url=url, command=command, server_params=server_params)
        if not self.label:
            raise ValueError("MCPSkills requires a label to identify the MCP server")
        # Skill names are "<label>/<skill-path>": a "/" in the label would let two origins produce the same name.
        if "/" in self.label:
            raise ValueError(f"MCPSkills label cannot contain '/': {self.label!r}")
        self.skill_uris = list(skill_uris or [])
        self.allow_dynamic = allow_dynamic
        self.gated_tools = list(gated_tools or [])
        self.gate_all_tools = gate_all_tools
        self._entries: Dict[str, _HeldEntry] = {}
        self._skills: Dict[str, Skill] = {}
        self._cache: Dict[Tuple[str, str], bytes] = {}
        # Skills whose server copy changed after their instructions were loaded.
        self._changed: set = set()

    def __repr__(self) -> str:
        return f"MCPSkills(label={self.label!r})"

    def load(self) -> List[Skill]:
        raise SkillError("MCPSkills loads skills over MCP and needs an async run (agent.arun) or `await aload()`")

    async def aload(self) -> List[Skill]:
        """List the server's skills and build the registry from their entries.

        Returns:
            Skills with metadata only. Instructions are read on demand.
        """
        session = await self._aclient_session()
        capabilities = session.server_capabilities
        extensions = getattr(capabilities, "extensions", None) or {}
        if SKILLS_EXTENSION not in extensions:
            log_warning(
                f"MCP server '{self.label}' does not declare the {SKILLS_EXTENSION} extension. "
                "Servers advertise it on protocol revision 2026-07-28: create MCPTools with protocol_mode='auto'."
            )
            return []
        if getattr(capabilities, "resources", None) is None:
            log_warning(f"MCP server '{self.label}' declares {SKILLS_EXTENSION} without the resources capability")
            return []

        raw_entries = await self._list_entries()
        listed_uris = {entry.get("uri") for entry in raw_entries if isinstance(entry, dict)}
        for uri in self.skill_uris:
            if uri in listed_uris:
                continue
            try:
                raw_entries.append(await self._get_entry(uri))
            except Exception as e:
                log_warning(f"Could not get skill '{uri}' from MCP server '{self.label}': {e}")

        self._entries.clear()
        self._skills.clear()
        self._cache.clear()
        self._changed.clear()
        for raw in raw_entries:
            try:
                entry = _parse_entry(raw)
            except ValueError as e:
                log_warning(f"Skipping invalid skill entry from MCP server '{self.label}': {e}")
                continue
            if entry.resources is None and not self.allow_dynamic:
                log_warning(
                    f"Skipping skill '{entry.uri}' from MCP server '{self.label}': its content is dynamic and cannot "
                    "be verified. Pass allow_dynamic=True to load it."
                )
                continue

            name = self._qualified_name(entry.uri)
            if name in self._entries:
                # Same skill path under two schemes: keep both, distinguished by scheme.
                name = f"{self.label}/{entry.uri}"
            self._entries[name] = entry
            self._skills[name] = self._build_skill(name, entry)

        log_debug(f"Listed {len(self._skills)} skills from MCP server '{self.label}'")
        return list(self._skills.values())

    async def aread_instructions(self, skill_name: str) -> str:
        """Read a skill's `SKILL.md`, verify it, and return the instructions body.

        Loading instructions starts acting on the skill afresh, so a skill that changed
        on the server is refreshed with `skills/get` and read under its new entry.
        """
        entry = self._held_entry(skill_name)
        try:
            data = await self._read_against(entry, entry.uri)
        except _ContentMismatch:
            entry = await self._refresh(skill_name)
            data = await self._read_against(entry, entry.uri)

        content = data.decode("utf-8")
        match = _FRONTMATTER_PATTERN.match(content)
        if match is None:
            raise SkillVerificationError(f"SKILL.md for '{skill_name}' has no YAML frontmatter")
        try:
            frontmatter = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError as e:
            raise SkillVerificationError(f"SKILL.md frontmatter for '{skill_name}' is not valid YAML: {e}") from e
        if _normalize(frontmatter) != _normalize(entry.frontmatter):
            raise SkillVerificationError(f"SKILL.md frontmatter for '{skill_name}' does not match the skill entry")
        self._changed.discard(skill_name)
        return match.group(2).strip()

    async def aread_file(self, skill_name: str, relative_path: str) -> str:
        """Read a supporting file by its path relative to the skill root.

        Reads stay bound to the entry the instructions were loaded under. If the server
        changed the skill since, the read fails until the instructions are loaded again,
        so old instructions are never paired with new files.
        """
        entry = self._held_entry(skill_name)
        # Checked before normalizing: normpath folds "a://b" into "a:/b".
        normalized = posixpath.normpath(relative_path) if relative_path and ":" not in relative_path else ""
        if not normalized or normalized in (".", "..", _SKILL_MD) or normalized.startswith(("/", "../")):
            raise SkillVerificationError(f"Invalid path '{relative_path}' for skill '{skill_name}'")
        if skill_name in self._changed:
            raise SkillVerificationError(_changed_message(skill_name))
        try:
            data = await self._read_against(entry, entry.root + normalized)
        except _ContentMismatch:
            if entry.resources is None:
                raise
            # Refresh so the next instructions load sees the new entry; a server that still
            # publishes the same files is serving content that does not match them.
            refreshed = await self._refresh(skill_name)
            if refreshed.resources == entry.resources:
                raise
            self._changed.add(skill_name)
            raise SkillVerificationError(_changed_message(skill_name)) from None
        return data.decode("utf-8", errors="replace")

    async def aclose(self) -> None:
        """Close the MCP connection. Later reads reconnect on demand."""
        async with self._lock():
            if self._connected:
                self._connected = False
                await self._client.__aexit__(None, None, None)

    def _lock(self) -> asyncio.Lock:
        # Created lazily so the lock binds to the running event loop.
        if self._connection_lock is None:
            self._connection_lock = asyncio.Lock()
        return self._connection_lock

    async def _aclient_session(self) -> Any:
        async with self._lock():
            if not self._connected:
                try:
                    await self._client.__aenter__()
                except Exception as e:
                    raise SkillError(f"Could not connect to MCP server '{self.label}': {e}") from e
                self._connected = True
        # fastmcp's Client wraps the SDK ClientSession that carries the raw request API.
        return self._client.session

    def _qualified_name(self, uri: str) -> str:
        skill_path = uri.split("://", 1)[1][: -len("/" + _SKILL_MD)]
        return f"{self.label}/{skill_path}"

    def _build_skill(self, name: str, entry: _HeldEntry) -> Skill:
        scripts: List[str] = []
        references: List[str] = []
        for uri in sorted(entry.resources or {}):
            if uri == entry.uri:
                continue
            relative = uri[len(entry.root) :]
            if relative.startswith("scripts/"):
                scripts.append(relative[len("scripts/") :])
            else:
                references.append(relative)
        frontmatter = entry.frontmatter
        return Skill(
            name=name,
            description=str(frontmatter["description"]),
            instructions="",
            source_path=entry.uri,
            scripts=scripts,
            references=references,
            metadata=frontmatter.get("metadata") if isinstance(frontmatter.get("metadata"), dict) else None,
            license=frontmatter.get("license"),
            compatibility=frontmatter.get("compatibility"),
            # A remote server cannot widen the host's tool permissions.
            allowed_tools=None,
            origin=self.label,
        )

    def _held_entry(self, skill_name: str) -> _HeldEntry:
        entry = self._entries.get(skill_name)
        if entry is None:
            raise SkillError(f"Skill '{skill_name}' is not served by MCP server '{self.label}'")
        return entry

    async def _refresh(self, skill_name: str) -> _HeldEntry:
        """Replace the held entry with the server's current one from `skills/get`."""
        entry = self._held_entry(skill_name)
        log_debug(f"Refreshing skill '{skill_name}' from MCP server '{self.label}'")
        try:
            refreshed = _parse_entry(await self._get_entry(entry.uri))
        except Exception as e:
            raise SkillVerificationError(f"Refreshing skill '{skill_name}' failed: {e}") from e
        if refreshed.resources is None and not self.allow_dynamic:
            raise SkillVerificationError(f"Skill '{skill_name}' is now dynamic and cannot be verified")
        self._entries[skill_name] = refreshed
        # Update in place: `Skills` holds this object in its registry.
        current, rebuilt = self._skills[skill_name], self._build_skill(skill_name, refreshed)
        current.description, current.scripts, current.references = (
            rebuilt.description,
            rebuilt.scripts,
            rebuilt.references,
        )
        return refreshed

    async def _read_against(self, entry: _HeldEntry, uri: str) -> bytes:
        if entry.resources is None:
            data = await self._fetch(uri)
            entry.retrieved_bytes += len(data)
            if entry.retrieved_bytes > MAX_SKILL_BYTES:
                raise SkillVerificationError(f"Skill '{entry.uri}' exceeded {MAX_SKILL_BYTES} bytes of content")
            return data

        expected = entry.resources.get(uri)
        if expected is None:
            raise SkillVerificationError(f"'{uri}' is not a file of skill '{entry.uri}'")
        digest, size = expected
        cached = self._cache.get((uri, digest))
        if cached is not None:
            return cached
        data = await self._fetch(uri)
        if len(data) != size or "sha256:" + hashlib.sha256(data).hexdigest() != digest:
            raise _ContentMismatch(f"Content of '{uri}' does not match the skill entry digest")
        self._cache[(uri, digest)] = data
        return data

    async def _fetch(self, uri: str) -> bytes:
        result = await (await self._aclient_session()).read_resource(uri)
        contents = getattr(result, "contents", None) or []
        for content in contents:
            if str(content.uri) != uri:
                continue
            text = getattr(content, "text", None)
            if text is not None:
                return text.encode("utf-8")
            blob = getattr(content, "blob", None)
            if blob is not None:
                return base64.b64decode(blob)
        raise SkillVerificationError(f"MCP server '{self.label}' returned no content for '{uri}'")

    async def _list_entries(self) -> List[Any]:
        from mcp.types import PaginatedRequestParams, Request

        entries: List[Any] = []
        cursor: Optional[str] = None
        for _ in range(_LIST_MAX_PAGES):
            params = PaginatedRequestParams(cursor=cursor) if cursor is not None else None
            result = await self._send(Request(method="skills/list", params=params))
            page = result.get("skills")
            if not isinstance(page, list):
                raise SkillError(f"MCP server '{self.label}' returned a skills/list result without 'skills'")
            entries.extend(page)
            cursor = result.get("nextCursor")
            if cursor is None:
                return entries
        raise SkillError(f"skills/list on MCP server '{self.label}' reached the page limit ({_LIST_MAX_PAGES})")

    async def _get_entry(self, uri: str) -> Any:
        from mcp.types import Request, RequestParams

        class GetSkillParams(RequestParams):
            uri: str

        result = await self._send(Request(method="skills/get", params=GetSkillParams(uri=uri)))
        return result.get("skill")

    async def _send(self, request: Any) -> Dict[str, Any]:
        from pydantic import TypeAdapter

        return await (await self._aclient_session()).send_request(request, TypeAdapter(Dict[str, Any]))


def _parse_entry(raw: Any) -> _HeldEntry:
    """Validate a raw skill entry against the extension's structural rules."""
    if not isinstance(raw, dict):
        raise ValueError("entry is not an object")
    uri = raw.get("uri")
    if not isinstance(uri, str) or "://" not in uri or not uri.endswith("/" + _SKILL_MD):
        raise ValueError(f"uri {uri!r} is not a SKILL.md resource URI")
    skill_path = uri.split("://", 1)[1][: -len("/" + _SKILL_MD)]
    if not skill_path or any(segment in ("", ".", "..") for segment in skill_path.split("/")):
        raise ValueError(f"uri {uri!r} has an invalid skill path")

    frontmatter = raw.get("frontmatter")
    if not isinstance(frontmatter, dict):
        raise ValueError(f"{uri}: frontmatter is not an object")
    name, description = frontmatter.get("name"), frontmatter.get("description")
    if not isinstance(name, str) or not isinstance(description, str):
        raise ValueError(f"{uri}: frontmatter needs string 'name' and 'description'")
    # The Agent Skills limits also bound what a server can put in every system prompt.
    errors = _validate_name(name) + _validate_description(description)
    if errors:
        raise ValueError(f"{uri}: {'; '.join(errors)}")
    if skill_path.rsplit("/", 1)[-1] != name:
        raise ValueError(f"{uri}: final path segment does not equal frontmatter name {name!r}")

    resources = raw.get("resources")
    if resources == "dynamic":
        return _HeldEntry(uri=uri, frontmatter=frontmatter, resources=None)
    if not isinstance(resources, list):
        raise ValueError(f"{uri}: resources must be a list or 'dynamic'")
    return _HeldEntry(uri=uri, frontmatter=frontmatter, resources=_parse_resources(uri, resources))


def _parse_resources(uri: str, resources: Sequence[Any]) -> Dict[str, Tuple[str, int]]:
    root = uri[: -len(_SKILL_MD)]
    parsed: Dict[str, Tuple[str, int]] = {}
    for item in resources:
        if not isinstance(item, dict):
            raise ValueError(f"{uri}: resource entry is not an object")
        resource_uri, digest, size = item.get("uri"), item.get("digest"), item.get("size")
        if not isinstance(resource_uri, str) or not resource_uri.startswith(root) or resource_uri == root:
            raise ValueError(f"{uri}: resource {resource_uri!r} is outside the skill directory")
        if ".." in resource_uri[len(root) :].split("/"):
            raise ValueError(f"{uri}: resource {resource_uri!r} escapes the skill directory")
        if not isinstance(digest, str) or not _DIGEST_PATTERN.match(digest):
            raise ValueError(f"{uri}: resource {resource_uri!r} has an invalid digest")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ValueError(f"{uri}: resource {resource_uri!r} has an invalid size")
        if resource_uri in parsed:
            raise ValueError(f"{uri}: resource {resource_uri!r} is listed twice")
        parsed[resource_uri] = (digest, size)
    if uri not in parsed:
        raise ValueError(f"{uri}: resources do not include SKILL.md")
    if len(parsed) > MAX_SKILL_RESOURCES:
        raise ValueError(f"{uri}: {len(parsed)} files exceeds the {MAX_SKILL_RESOURCES}-file limit")
    total = sum(size for _, size in parsed.values())
    if total > MAX_SKILL_BYTES:
        raise ValueError(f"{uri}: {total} bytes exceeds the {MAX_SKILL_BYTES}-byte limit")
    return parsed


def _changed_message(skill_name: str) -> str:
    return (
        f"Skill '{skill_name}' changed on the MCP server after its instructions were loaded. "
        "Load its instructions again before reading its files."
    )


def _normalize(value: Union[Dict[str, Any], Any]) -> Any:
    """Render YAML-parsed and JSON-received frontmatter in one comparable form."""
    return json.loads(json.dumps(value, sort_keys=True, default=str))
