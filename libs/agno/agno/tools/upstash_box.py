import asyncio
import json
import shlex
import threading
import weakref
from os import getenv
from textwrap import dedent
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, TypeVar
from uuid import uuid4

from agno.run import RunContext
from agno.tools import Toolkit
from agno.utils.code_execution import prepare_python_code
from agno.utils.log import log_debug, log_info

try:
    from upstash_box import AsyncBox, Box, BoxError
except ImportError:
    raise ImportError("`upstash-box` not installed. Please install using `pip install upstash-box`")

DEFAULT_INSTRUCTIONS = dedent(
    """\
    You have access to an Upstash Box: an isolated cloud Linux environment for running code.
    The box persists across tool calls, so files you write and packages you install remain available.
    Commands run in /workspace/home, and relative file paths resolve against it.
    Available tools:
    - `run_python_code`: Execute Python code and return its output
    - `run_command`: Execute a shell command
    - `create_file`: Create or overwrite a file
    - `read_file`: Read a file's contents
    - `list_files`: List the contents of a directory
    - `delete_file`: Delete a file or directory
    - `get_box_info`: Inspect the current box
    - `list_boxes`: List boxes created by this toolkit
    - `shutdown_box`: Delete the current box
    - `shutdown_box_by_id`: Delete a specific box by its id
    - `get_public_url`: Get a public URL for a port a process in the box is listening on
    When asked to run or verify code, write it, execute it with run_python_code or run_command, and show the real output.
    Install missing packages with run_command, for example `pip install <package>`.
    """
)

# Key under which the session's box id is stored in the run's session state, which
# agno persists, so the same box is reused across tool calls and across runs.
SESSION_STATE_BOX_ID = "upstash_box_id"

# Label added to every box this toolkit creates, so list_boxes can scope to them.
DEFAULT_LABEL = "agno"

# Default runtime. Every Box image ships python3; the python runtime adds pip.
DEFAULT_RUNTIME = "python"

# The box's working directory: commands start here and relative paths resolve against it.
WORKSPACE = "/workspace/home"

# How many times a box lookup re-resolves after a concurrent call superseded it.
MAX_LOOKUP_ATTEMPTS = 5

T = TypeVar("T")


class UpstashBoxTools(Toolkit):
    """Run agent-generated code in an isolated Upstash Box.

    A box is a managed cloud Linux environment with a shell and a filesystem. It
    is created on the first tool call, pauses when idle, and resumes automatically
    on the next call. A focused set of code-execution and file tools is enabled by
    default; the lifecycle tools (pause, resume, snapshot) are opt-in via their
    `enable_*` flags, or turn everything on with `all=True`. Every tool has both a
    sync and an async variant, so the toolkit works with `agent.run()` and
    `agent.arun()`.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        box_id: Optional[str] = None,
        runtime: str = DEFAULT_RUNTIME,
        size: Optional[str] = None,
        keep_alive: bool = False,
        env_vars: Optional[Dict[str, str]] = None,
        labels: Optional[List[str]] = None,
        command_timeout: Optional[int] = None,
        persistent: bool = True,
        enable_run_python_code: bool = True,
        enable_run_command: bool = True,
        enable_create_file: bool = True,
        enable_read_file: bool = True,
        enable_list_files: bool = True,
        enable_delete_file: bool = True,
        enable_get_box_info: bool = True,
        enable_list_boxes: bool = True,
        enable_shutdown_box: bool = True,
        enable_shutdown_box_by_id: bool = True,
        enable_get_public_url: bool = True,
        enable_pause_box: bool = False,
        enable_resume_box: bool = False,
        enable_snapshot_box: bool = False,
        all: bool = False,
        instructions: Optional[str] = None,
        add_instructions: bool = False,
        **kwargs: Any,
    ):
        """Initialize the Upstash Box toolkit.

        Args:
            api_key: Upstash Box API key (defaults to the UPSTASH_BOX_API_KEY env var).
            base_url: Override the Box API base URL (defaults to UPSTASH_BOX_BASE_URL or the SDK default).
            box_id: Connect to an existing box instead of creating a new one.
            runtime: Runtime image for created boxes, e.g. "python", "node", or "golang" (default: "python").
            size: Resource size for created boxes: "small", "medium", or "large" (default: the API default).
            keep_alive: Keep created boxes running instead of pausing them when idle (default: False).
            env_vars: Environment variables to set in created boxes.
            labels: Extra labels to tag created boxes with. The "agno" label is always added,
                so list_boxes can find the boxes this toolkit created.
            command_timeout: Per-command timeout in seconds for run_python_code and run_command.
                A command that runs over is stopped with exit code 124 (default: None, no limit).
            persistent: Persist the box id in the session state so the same box is reused
                across runs of the session (default: True). Each session gets its own box.
            enable_run_python_code: Register the run_python_code tool (default: True).
            enable_run_command: Register the run_command tool (default: True).
            enable_create_file: Register the create_file tool (default: True).
            enable_read_file: Register the read_file tool (default: True).
            enable_list_files: Register the list_files tool (default: True).
            enable_delete_file: Register the delete_file tool (default: True).
            enable_get_box_info: Register the get_box_info tool (default: True).
            enable_list_boxes: Register the list_boxes tool (default: True).
            enable_shutdown_box: Register the shutdown_box tool (default: True).
            enable_shutdown_box_by_id: Register the shutdown_box_by_id tool (default: True).
            enable_get_public_url: Register the get_public_url tool (default: True).
            enable_pause_box: Register the pause_box tool (default: False).
            enable_resume_box: Register the resume_box tool (default: False).
            enable_snapshot_box: Register the snapshot_box tool (default: False).
            all: Register every tool, overriding the individual enable_* flags (default: False).
            instructions: Override the default toolkit instructions.
            add_instructions: Whether to add the instructions to the agent's system message.
        """
        self.api_key = api_key or getenv("UPSTASH_BOX_API_KEY")
        if not self.api_key:
            raise ValueError("UPSTASH_BOX_API_KEY not set. Please set the UPSTASH_BOX_API_KEY environment variable.")

        self.base_url = base_url or getenv("UPSTASH_BOX_BASE_URL")
        self.box_id = box_id
        self.runtime = runtime
        self.size = size
        self.keep_alive = keep_alive
        self.env_vars = env_vars
        self.labels = [DEFAULT_LABEL] + [label for label in (labels or []) if label != DEFAULT_LABEL]
        self.command_timeout = command_timeout
        self.persistent = persistent

        # One box per session. Its id is tracked here whether or not it is persisted,
        # so the sync and async tools of a session always share the same box.
        self._active_ids: Dict[str, str] = {}
        # Bumped whenever a session's active box changes, so a lookup that waited on the
        # network can tell whether another call replaced or shut down the box meanwhile.
        self._generations: Dict[str, int] = {}
        # Lazily-created clients. Sync clients are cached per session; async clients
        # per session and event loop, because an AsyncBox's connections belong to the
        # loop that opened them.
        self._boxes: Dict[str, Box] = {}
        self._async_boxes: Dict[Tuple[str, int], Tuple["weakref.ref[asyncio.AbstractEventLoop]", AsyncBox]] = {}
        # Per-session locks so concurrent first calls create a single box. Async
        # locks are also keyed by event loop, since an asyncio.Lock is loop-bound.
        self._locks_guard = threading.Lock()
        self._locks: Dict[str, threading.Lock] = {}
        self._async_locks: Dict[Tuple[str, int], asyncio.Lock] = {}

        self.instructions = instructions or DEFAULT_INSTRUCTIONS

        tools: List[Any] = []
        async_tools: List[Any] = []
        if all or enable_run_python_code:
            tools.append(self.run_python_code)
            async_tools.append((self.arun_python_code, "run_python_code"))
        if all or enable_run_command:
            tools.append(self.run_command)
            async_tools.append((self.arun_command, "run_command"))
        if all or enable_create_file:
            tools.append(self.create_file)
            async_tools.append((self.acreate_file, "create_file"))
        if all or enable_read_file:
            tools.append(self.read_file)
            async_tools.append((self.aread_file, "read_file"))
        if all or enable_list_files:
            tools.append(self.list_files)
            async_tools.append((self.alist_files, "list_files"))
        if all or enable_delete_file:
            tools.append(self.delete_file)
            async_tools.append((self.adelete_file, "delete_file"))
        if all or enable_get_box_info:
            tools.append(self.get_box_info)
            async_tools.append((self.aget_box_info, "get_box_info"))
        if all or enable_list_boxes:
            tools.append(self.list_boxes)
            async_tools.append((self.alist_boxes, "list_boxes"))
        if all or enable_shutdown_box:
            tools.append(self.shutdown_box)
            async_tools.append((self.ashutdown_box, "shutdown_box"))
        if all or enable_shutdown_box_by_id:
            tools.append(self.shutdown_box_by_id)
            async_tools.append((self.ashutdown_box_by_id, "shutdown_box_by_id"))
        if all or enable_get_public_url:
            tools.append(self.get_public_url)
            async_tools.append((self.aget_public_url, "get_public_url"))
        if all or enable_pause_box:
            tools.append(self.pause_box)
            async_tools.append((self.apause_box, "pause_box"))
        if all or enable_resume_box:
            tools.append(self.resume_box)
            async_tools.append((self.aresume_box, "resume_box"))
        if all or enable_snapshot_box:
            tools.append(self.snapshot_box)
            async_tools.append((self.asnapshot_box, "snapshot_box"))

        super().__init__(
            name="upstash_box_tools",
            tools=tools,
            async_tools=async_tools,
            instructions=self.instructions,
            add_instructions=add_instructions,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Box lifecycle helpers
    # ------------------------------------------------------------------
    def _connection_options(self) -> Dict[str, Any]:
        options: Dict[str, Any] = {"api_key": self.api_key}
        if self.base_url:
            options["base_url"] = self.base_url
        return options

    def _create_options(self) -> Dict[str, Any]:
        options = self._connection_options()
        options["name"] = f"agno-{uuid4().hex[:8]}"
        options["runtime"] = self.runtime
        options["labels"] = self.labels
        if self.size:
            options["size"] = self.size
        if self.keep_alive:
            options["keep_alive"] = True
        if self.env_vars:
            options["env"] = self.env_vars
        return options

    @staticmethod
    def _session_key(run_context: Optional[RunContext]) -> str:
        """The session a box belongs to; tools called outside a run share one box."""
        if run_context is not None and run_context.session_id:
            return run_context.session_id
        return ""

    def _thread_lock(self, key: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(key, threading.Lock())

    def _async_lock(self, key: str) -> asyncio.Lock:
        loop_key = (key, id(asyncio.get_running_loop()))
        with self._locks_guard:
            if loop_key not in self._async_locks:
                self._async_locks[loop_key] = asyncio.Lock()
            return self._async_locks[loop_key]

    def _resolve_box_id(self, run_context: Optional[RunContext], key: str) -> Optional[str]:
        """The box to use: the explicit box_id, else the session's active box, else the persisted id."""
        return self._resolve(run_context, key)[0]

    def _resolve(self, run_context: Optional[RunContext], key: str) -> Tuple[Optional[str], int]:
        """The box to use, with the session generation it was read at.

        The explicit box_id wins, then the session's active box, then the run's persisted
        id. The active id wins over a run's session state because that state is a
        snapshot taken when the run started: if another run of the session replaced or
        shut down the box since, the snapshot is stale. The persisted id is used when
        this toolkit has not seen the session yet, e.g. a new agent resuming it.
        """
        with self._locks_guard:
            active = self._active_ids.get(key)
            generation = self._generations.get(key, 0)
        if self.box_id:
            return self.box_id, generation
        if active is not None:
            return active, generation
        if self.persistent and run_context is not None and run_context.session_state:
            stored = run_context.session_state.get(SESSION_STATE_BOX_ID)
            if isinstance(stored, str):
                return stored, generation
        return None, generation

    def _set_active_locked(self, key: str, box_id: Optional[str]) -> None:
        """Change a session's active box. Call with _locks_guard held."""
        if self._active_ids.get(key) == box_id:
            return
        if box_id is None:
            self._active_ids.pop(key, None)
        else:
            self._active_ids[key] = box_id
        self._generations[key] = self._generations.get(key, 0) + 1

    def _store_run_box_id(self, run_context: Optional[RunContext], box_id: str) -> None:
        """Write box_id into this run's session state, which agno persists.

        Done on every lookup, cache hits included: separate runs of one session have
        separate state dictionaries, and each must carry the id.
        """
        if self.persistent and run_context is not None:
            if run_context.session_state is None:
                run_context.session_state = {}
            run_context.session_state[SESSION_STATE_BOX_ID] = box_id

    def _publish(
        self,
        run_context: Optional[RunContext],
        key: str,
        box_id: str,
        generation: int,
        install: Optional[Callable[[], None]] = None,
    ) -> bool:
        """Make box_id the session's box, unless another call changed it since `generation`.

        A lookup reads the session's box, then waits on the network to connect to it. A
        concurrent call (e.g. the other client type recovering from an external delete)
        can replace or shut down that box meanwhile; publishing the stale lookup would
        override the replacement. So the check and the installation of the client run
        atomically under the cache lock. Returns False when superseded; the caller then
        discards its client and resolves again.
        """
        with self._locks_guard:
            current = self._active_ids.get(key)
            if self._generations.get(key, 0) != generation and current != box_id:
                return False
            if install is not None:
                install()
            self._set_active_locked(key, box_id)
        self._store_run_box_id(run_context, box_id)
        return True

    def _claim_new_box(self, key: str, box_id: str) -> Optional[str]:
        """Register a newly created box as the session's box. Returns the id of a box
        another call registered first, in which case the new box is redundant."""
        with self._locks_guard:
            existing = self._active_ids.get(key)
            if existing is not None and existing != box_id:
                return existing
            self._set_active_locked(key, box_id)
            return None

    def _forget_box_id(self, run_context: Optional[RunContext], box_id: str) -> None:
        """Clear every in-memory and per-run reference to a box id."""
        with self._locks_guard:
            for key, active in list(self._active_ids.items()):
                if active == box_id:
                    self._set_active_locked(key, None)
        if run_context is not None and run_context.session_state:
            if run_context.session_state.get(SESSION_STATE_BOX_ID) == box_id:
                run_context.session_state.pop(SESSION_STATE_BOX_ID, None)

    @staticmethod
    def _clear_run_box_id(run_context: Optional[RunContext]) -> None:
        """After a shutdown the session has no box, so this run must not persist one,
        even if its state still carries an older, already-replaced id."""
        if run_context is not None and run_context.session_state:
            run_context.session_state.pop(SESSION_STATE_BOX_ID, None)

    def _cached_box(self, key: str) -> Optional[Box]:
        with self._locks_guard:
            return self._boxes.get(key)

    def _cached_async_box(self, key: str) -> Optional[AsyncBox]:
        """This loop's async client for the session. Clients of closed loops are dropped:
        their connections can be neither used nor cleanly closed from another loop."""
        loop = asyncio.get_running_loop()
        with self._locks_guard:
            for cache_key, (loop_ref, _) in list(self._async_boxes.items()):
                owner = loop_ref()
                if owner is None or owner.is_closed():
                    del self._async_boxes[cache_key]
            entry = self._async_boxes.get((key, id(loop)))
        if entry is not None and entry[0]() is loop:
            return entry[1]
        return None

    def _detach_box(
        self, box_id: str
    ) -> Tuple[List[Box], List[Tuple["weakref.ref[asyncio.AbstractEventLoop]", AsyncBox]]]:
        """Atomically remove every cached client of a box and its active ids.

        Done in one step under the cache lock, so concurrent shutdowns of the same box
        (e.g. sessions sharing an explicit box_id) never see a half-cleared cache.
        Closing the detached clients happens afterwards, outside the lock.
        """
        with self._locks_guard:
            sync_keys = [key for key, box in self._boxes.items() if box.id == box_id]
            sync_clients = [self._boxes.pop(key) for key in sync_keys]
            async_keys = [key for key, (_, box) in self._async_boxes.items() if box.id == box_id]
            async_clients = [self._async_boxes.pop(key) for key in async_keys]
            for key in [key for key, active in self._active_ids.items() if active == box_id]:
                self._set_active_locked(key, None)
        return sync_clients, async_clients

    def _drop_box(self, run_context: Optional[RunContext], box_id: str) -> None:
        """Forget a deleted box: its cached clients and every reference to its id."""
        sync_clients, _ = self._detach_box(box_id)
        for box in sync_clients:
            box.close()
        # Async clients are only dropped: closing one needs its own running loop.
        self._forget_box_id(run_context, box_id)

    async def _adrop_box(self, run_context: Optional[RunContext], box_id: str) -> None:
        """Async variant of _drop_box; also closes this loop's async clients."""
        loop = asyncio.get_running_loop()
        sync_clients, async_clients = self._detach_box(box_id)
        # Clear this run's reference before awaiting cleanup, so it is cleared even if
        # another shutdown detached the clients first or a cleanup fails.
        self._forget_box_id(run_context, box_id)
        for box in sync_clients:
            box.close()
        for loop_ref, async_box in async_clients:
            if loop_ref() is loop:
                await async_box.aclose()

    def _delete_box(self, box_id: str) -> None:
        """Delete a box by id; a box that is already gone counts as deleted.

        Uses its own short-lived client rather than a cached one: a concurrent shutdown
        of the same box (e.g. sessions sharing an explicit box_id) closes every cached
        client of that box, which would break a delete still in flight on one of them.
        A box client is used over the SDK's static bulk delete because its request
        timeout leaves room for a busy box to shut down; the static call has httpx's
        5-second default.
        """
        box: Optional[Box] = None
        try:
            box = Box.get(box_id, **self._connection_options())
            box.delete()
        except BoxError as e:
            if not self._is_not_found(e):
                raise
        finally:
            if box is not None:
                box.close()

    async def _adelete_box(self, box_id: str) -> None:
        """Async variant of _delete_box."""
        box: Optional[AsyncBox] = None
        try:
            box = await AsyncBox.get(box_id, **self._connection_options())
            await box.delete()
        except BoxError as e:
            if not self._is_not_found(e):
                raise
        finally:
            if box is not None:
                await box.aclose()

    @staticmethod
    def _is_not_found(error: Exception) -> bool:
        return isinstance(error, BoxError) and error.status_code == 404

    def _box_is_gone(self, box: Box) -> bool:
        """True if the box itself was deleted, as opposed to e.g. a missing file (both 404)."""
        try:
            box.get_status()
            return False
        except BoxError as e:
            return self._is_not_found(e)

    async def _abox_is_gone(self, box: AsyncBox) -> bool:
        try:
            await box.get_status()
            return False
        except BoxError as e:
            return self._is_not_found(e)

    def _get_box(self, run_context: Optional[RunContext], create: bool = True) -> Box:
        """Get this session's sync box, connecting to or creating one as needed.

        With create=False (pause, resume, snapshot) a missing or deleted box is an error
        instead of being replaced by a new, empty one.
        """
        key = self._session_key(run_context)
        with self._thread_lock(key):
            for _ in range(MAX_LOOKUP_ATTEMPTS):
                box_id, generation = self._resolve(run_context, key)
                cached = self._cached_box(key)
                if cached is not None and (box_id is None or cached.id == box_id):
                    if self._publish(run_context, key, cached.id, generation):
                        return cached
                    continue

                if box_id:
                    log_debug(f"Connecting to Upstash Box: {box_id}")
                    try:
                        box = Box.get(box_id, **self._connection_options())
                        # Looking up a deleted box still succeeds; its status call returns 404.
                        box.get_status()
                    except BoxError as e:
                        # A remembered box may have been deleted outside the agent, so start
                        # a fresh one. An explicitly requested box_id is an error.
                        if self.box_id or not self._is_not_found(e):
                            raise
                        self._forget_box_id(run_context, box_id)
                        if not create:
                            raise BoxError(f"Box {box_id} no longer exists", 404) from e
                        log_info(f"Upstash Box {box_id} no longer exists, creating a new one")
                    else:
                        connected = box
                        if self._publish(
                            run_context, key, box.id, generation, lambda: self._boxes.__setitem__(key, connected)
                        ):
                            return box
                        box.close()  # superseded while connecting; use the current box
                        continue

                if not create:
                    raise BoxError("No active box", 404)
                box = Box.create(**self._create_options())
                existing = self._claim_new_box(key, box.id)
                if existing is not None:
                    # Another call registered this session's box first; use that one.
                    box.delete()
                    box.close()
                    continue
                log_info(f"Created Upstash Box: {box.id}")
                with self._locks_guard:
                    self._boxes[key] = box
                self._store_run_box_id(run_context, box.id)
                return box
            raise BoxError("Could not settle on a box for this session; retry the call")

    async def _aget_box(self, run_context: Optional[RunContext], create: bool = True) -> AsyncBox:
        """Async variant of _get_box."""
        key = self._session_key(run_context)
        async with self._async_lock(key):
            loop = asyncio.get_running_loop()
            for _ in range(MAX_LOOKUP_ATTEMPTS):
                box_id, generation = self._resolve(run_context, key)
                cached = self._cached_async_box(key)
                if cached is not None and (box_id is None or cached.id == box_id):
                    if self._publish(run_context, key, cached.id, generation):
                        return cached
                    continue

                if box_id:
                    log_debug(f"Connecting to Upstash Box: {box_id}")
                    try:
                        async_box = await AsyncBox.get(box_id, **self._connection_options())
                        # Looking up a deleted box still succeeds; its status call returns 404.
                        await async_box.get_status()
                    except BoxError as e:
                        if self.box_id or not self._is_not_found(e):
                            raise
                        self._forget_box_id(run_context, box_id)
                        if not create:
                            raise BoxError(f"Box {box_id} no longer exists", 404) from e
                        log_info(f"Upstash Box {box_id} no longer exists, creating a new one")
                    else:
                        entry = (weakref.ref(loop), async_box)
                        if self._publish(
                            run_context,
                            key,
                            async_box.id,
                            generation,
                            lambda: self._async_boxes.__setitem__((key, id(loop)), entry),
                        ):
                            return async_box
                        await async_box.aclose()  # superseded while connecting; use the current box
                        continue

                if not create:
                    raise BoxError("No active box", 404)
                async_box = await AsyncBox.create(**self._create_options())
                existing = self._claim_new_box(key, async_box.id)
                if existing is not None:
                    # Another call registered this session's box first; use that one.
                    await async_box.delete()
                    await async_box.aclose()
                    continue
                log_info(f"Created Upstash Box: {async_box.id}")
                with self._locks_guard:
                    self._async_boxes[(key, id(loop))] = (weakref.ref(loop), async_box)
                self._store_run_box_id(run_context, async_box.id)
                return async_box
            raise BoxError("Could not settle on a box for this session; retry the call")

    def _with_box(self, run_context: Optional[RunContext], operation: Callable[[Box], T], replace: bool = True) -> T:
        """Run an operation on the session's box, handling a box deleted outside the agent.

        A deleted box is forgotten. With replace=True the operation then runs once on a
        fresh box; otherwise (pause, resume, snapshot) it fails, since acting on a new,
        empty box would not do what was asked.
        """
        box = self._get_box(run_context, create=replace)
        try:
            return operation(box)
        except BoxError as e:
            if not self._is_not_found(e) or not self._box_is_gone(box):
                raise
            self._drop_box(run_context, box.id)
            if self.box_id or not replace:
                raise BoxError(f"Box {box.id} no longer exists", 404) from e
            log_info(f"Upstash Box {box.id} was deleted, creating a new one")
            return operation(self._get_box(run_context))

    async def _awith_box(
        self,
        run_context: Optional[RunContext],
        operation: Callable[[AsyncBox], Awaitable[T]],
        replace: bool = True,
    ) -> T:
        """Async variant of _with_box."""
        box = await self._aget_box(run_context, create=replace)
        try:
            return await operation(box)
        except BoxError as e:
            if not self._is_not_found(e) or not await self._abox_is_gone(box):
                raise
            await self._adrop_box(run_context, box.id)
            if self.box_id or not replace:
                raise BoxError(f"Box {box.id} no longer exists", 404) from e
            log_info(f"Upstash Box {box.id} was deleted, creating a new one")
            return await operation(await self._aget_box(run_context))

    def _current_box_id(self, run_context: Optional[RunContext]) -> Optional[str]:
        """The session's box id, if it has one, without connecting or creating a box."""
        key = self._session_key(run_context)
        cached = self._cached_box(key)
        return self._resolve_box_id(run_context, key) or (cached.id if cached is not None else None)

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _error(message: str, error: Any) -> str:
        return json.dumps({"status": "error", "message": f"{message}: {str(error)}"})

    @staticmethod
    def _format_run(run: Any) -> str:
        parts: List[str] = []
        if run.stdout:
            parts.append(f"STDOUT:\n{run.stdout}")
        if run.stderr:
            parts.append(f"STDERR:\n{run.stderr}")
        parts.append(f"Exit code: {run.exit_code}")
        return "\n".join(parts)

    def _shell_command(self, command: str) -> str:
        """Wrap a command with `timeout` when a per-command timeout is set (exit code 124 on timeout)."""
        if self.command_timeout:
            return f"timeout {int(self.command_timeout)} sh -c {shlex.quote(command)}"
        return command

    def _python_script(self) -> Tuple[str, str]:
        """A temp script path and the shell command that runs it under the per-command timeout."""
        path = f"/tmp/agno_run_{uuid4().hex[:8]}.py"
        return path, self._shell_command(f"python3 {shlex.quote(path)}")

    @staticmethod
    def _format_listing(directory: str, entries: List[Any]) -> str:
        if not entries:
            return f"{directory} is empty."
        lines = [f"Contents of {directory}:"]
        for entry in sorted(entries, key=lambda e: (not e.is_dir, e.name)):
            if entry.is_dir:
                lines.append(f"dir   {entry.name}/")
            else:
                lines.append(f"file  {entry.name} ({entry.size} bytes)")
        return "\n".join(lines)

    @staticmethod
    def _format_boxes(boxes: List[Any]) -> str:
        return json.dumps(
            [{"id": b.id, "name": b.name, "status": b.status, "runtime": b.runtime, "labels": b.labels} for b in boxes]
        )

    @staticmethod
    def _format_info(box: Any, status: Dict[str, Any]) -> str:
        return json.dumps(
            {"id": box.id, "status": status.get("status"), "size": box.size, "keep_alive": box.keep_alive}
        )

    @staticmethod
    def _format_snapshot(snapshot: Any) -> str:
        return json.dumps({"id": snapshot.id, "name": snapshot.name, "status": snapshot.status})

    @staticmethod
    def _public_url(public_url: Any) -> str:
        if not public_url.url:
            raise BoxError("no URL returned")
        return public_url.url

    # ------------------------------------------------------------------
    # Core tools (sync)
    # ------------------------------------------------------------------
    def run_python_code(self, run_context: RunContext, code: str) -> str:
        """Execute Python code in the box and return its output.

        Args:
            code: Python code to execute.

        Returns:
            The output (stdout, stderr, exit code) or an error message.
        """

        def operation(box: Box) -> str:
            if not self.command_timeout:
                return self._format_run(box.exec.code(code=prepare_python_code(code), lang="python"))
            # The code endpoint takes no timeout, so run the code as a script under `timeout`.
            path, command = self._python_script()
            box.files.write(path=path, content=prepare_python_code(code))
            return self._format_run(box.exec.command(command))

        try:
            return self._with_box(run_context, operation)
        except Exception as e:
            return self._error("Error executing code", e)

    def run_command(self, run_context: RunContext, command: str) -> str:
        """Execute a shell command in the box.

        Args:
            command: Shell command to execute.

        Returns:
            The command output (stdout, stderr, exit code) or an error message.
        """
        try:
            return self._with_box(
                run_context, lambda box: self._format_run(box.exec.command(self._shell_command(command)))
            )
        except Exception as e:
            return self._error("Error executing command", e)

    def create_file(self, run_context: RunContext, file_path: str, content: str) -> str:
        """Create or overwrite a file in the box.

        Args:
            file_path: Path to the file, absolute or relative to /workspace/home.
            content: Text content to write.

        Returns:
            A success message or an error message.
        """
        try:
            self._with_box(run_context, lambda box: box.files.write(path=file_path, content=content))
            return f"File written: {file_path}"
        except Exception as e:
            return self._error("Error creating file", e)

    def read_file(self, run_context: RunContext, file_path: str) -> str:
        """Read a file's contents from the box.

        Args:
            file_path: Path to the file, absolute or relative to /workspace/home.

        Returns:
            The file contents as text or an error message.
        """
        try:
            return self._with_box(run_context, lambda box: box.files.read(file_path))
        except Exception as e:
            return self._error("Error reading file", e)

    def list_files(self, run_context: RunContext, directory: str = WORKSPACE) -> str:
        """List the contents of a directory in the box.

        Args:
            directory: Directory to list (default: /workspace/home).

        Returns:
            The directory listing or an error message.
        """
        try:
            return self._with_box(run_context, lambda box: self._format_listing(directory, box.files.list(directory)))
        except Exception as e:
            return self._error("Error listing files", e)

    def delete_file(self, run_context: RunContext, file_path: str) -> str:
        """Delete a file or directory in the box.

        Args:
            file_path: Path to the file or directory, absolute or relative to /workspace/home.

        Returns:
            A success message or an error message.
        """
        try:
            self._with_box(run_context, lambda box: box.files.remove(file_path, recursive=True))
            return f"Deleted: {file_path}"
        except Exception as e:
            return self._error("Error deleting file", e)

    def get_box_info(self, run_context: RunContext) -> str:
        """Get information about the current box.

        Returns:
            JSON with the box id, status, size, and keep-alive setting, or an error message.
        """
        try:
            return self._with_box(run_context, lambda box: self._format_info(box, box.get_status()))
        except Exception as e:
            return self._error("Error getting box info", e)

    def list_boxes(self) -> str:
        """List the boxes this toolkit created (boxes labeled "agno").

        Returns:
            JSON list of boxes (id, name, status, runtime, labels) or an error message.
        """
        try:
            boxes = Box.list(label=DEFAULT_LABEL, **self._connection_options())
            return self._format_boxes(boxes)
        except Exception as e:
            return self._error("Error listing boxes", e)

    def shutdown_box(self, run_context: RunContext) -> str:
        """Delete the current box and release its resources.

        Returns:
            A success message or an error message.
        """
        try:
            # Hold the session lock so a concurrent lookup or recovery cannot swap the
            # session's box between reading its id and deleting it.
            with self._thread_lock(self._session_key(run_context)):
                box_id = self._current_box_id(run_context)
                if box_id is None:
                    return "No active box to shut down."
                self._delete_box(box_id)
                self._drop_box(run_context, box_id)
                self._clear_run_box_id(run_context)
            return f"Box {box_id} shut down."
        except Exception as e:
            return self._error("Error shutting down box", e)

    def shutdown_box_by_id(self, run_context: RunContext, box_id: str) -> str:
        """Delete a specific box by its id, e.g. one returned by list_boxes.

        Args:
            box_id: The id of the box to delete.

        Returns:
            A success message or an error message.
        """
        try:
            self._delete_box(box_id)
            # Drop any cached client and stored id for the deleted box.
            self._drop_box(run_context, box_id)
            return f"Box {box_id} shut down."
        except Exception as e:
            return self._error("Error shutting down box", e)

    def get_public_url(self, run_context: RunContext, port: int) -> str:
        """Get a public URL for a port a process inside the box is listening on.

        A request to the URL resumes the box if it is paused.

        Args:
            port: Port a process inside the box is listening on.

        Returns:
            A public URL routing to that port, or an error message.
        """
        try:
            return self._with_box(run_context, lambda box: self._public_url(box.get_public_url(port)))
        except Exception as e:
            return self._error("Error getting public URL", e)

    # ------------------------------------------------------------------
    # Lifecycle tools (opt-in)
    # ------------------------------------------------------------------
    def pause_box(self, run_context: RunContext) -> str:
        """Pause the current box to release compute. Its files are kept, and the next tool call resumes it.

        Returns:
            A success message or an error message.
        """

        def operation(box: Box) -> str:
            box.pause()
            return f"Box {box.id} paused."

        try:
            return self._with_box(run_context, operation, replace=False)
        except Exception as e:
            return self._error("Error pausing box", e)

    def resume_box(self, run_context: RunContext) -> str:
        """Resume the current paused box.

        Returns:
            A success message or an error message.
        """

        def operation(box: Box) -> str:
            box.resume()
            return f"Box {box.id} resumed."

        try:
            return self._with_box(run_context, operation, replace=False)
        except Exception as e:
            return self._error("Error resuming box", e)

    def snapshot_box(self, run_context: RunContext, name: str) -> str:
        """Save the current box's workspace as a snapshot that new boxes can be created from.

        Args:
            name: A name for the snapshot.

        Returns:
            JSON with the snapshot id, name, and status, or an error message.
        """
        try:
            return self._with_box(
                run_context, lambda box: self._format_snapshot(box.snapshot(name=name)), replace=False
            )
        except Exception as e:
            return self._error("Error creating snapshot", e)

    # ------------------------------------------------------------------
    # Core tools (async)
    # ------------------------------------------------------------------
    async def arun_python_code(self, run_context: RunContext, code: str) -> str:
        """Execute Python code in the box and return its output.

        Args:
            code: Python code to execute.

        Returns:
            The output (stdout, stderr, exit code) or an error message.
        """

        async def operation(box: AsyncBox) -> str:
            if not self.command_timeout:
                return self._format_run(await box.exec.code(code=prepare_python_code(code), lang="python"))
            path, command = self._python_script()
            await box.files.write(path=path, content=prepare_python_code(code))
            return self._format_run(await box.exec.command(command))

        try:
            return await self._awith_box(run_context, operation)
        except Exception as e:
            return self._error("Error executing code", e)

    async def arun_command(self, run_context: RunContext, command: str) -> str:
        """Execute a shell command in the box.

        Args:
            command: Shell command to execute.

        Returns:
            The command output (stdout, stderr, exit code) or an error message.
        """

        async def operation(box: AsyncBox) -> str:
            return self._format_run(await box.exec.command(self._shell_command(command)))

        try:
            return await self._awith_box(run_context, operation)
        except Exception as e:
            return self._error("Error executing command", e)

    async def acreate_file(self, run_context: RunContext, file_path: str, content: str) -> str:
        """Create or overwrite a file in the box.

        Args:
            file_path: Path to the file, absolute or relative to /workspace/home.
            content: Text content to write.

        Returns:
            A success message or an error message.
        """

        async def operation(box: AsyncBox) -> None:
            await box.files.write(path=file_path, content=content)

        try:
            await self._awith_box(run_context, operation)
            return f"File written: {file_path}"
        except Exception as e:
            return self._error("Error creating file", e)

    async def aread_file(self, run_context: RunContext, file_path: str) -> str:
        """Read a file's contents from the box.

        Args:
            file_path: Path to the file, absolute or relative to /workspace/home.

        Returns:
            The file contents as text or an error message.
        """

        async def operation(box: AsyncBox) -> str:
            return await box.files.read(file_path)

        try:
            return await self._awith_box(run_context, operation)
        except Exception as e:
            return self._error("Error reading file", e)

    async def alist_files(self, run_context: RunContext, directory: str = WORKSPACE) -> str:
        """List the contents of a directory in the box.

        Args:
            directory: Directory to list (default: /workspace/home).

        Returns:
            The directory listing or an error message.
        """

        async def operation(box: AsyncBox) -> str:
            return self._format_listing(directory, await box.files.list(directory))

        try:
            return await self._awith_box(run_context, operation)
        except Exception as e:
            return self._error("Error listing files", e)

    async def adelete_file(self, run_context: RunContext, file_path: str) -> str:
        """Delete a file or directory in the box.

        Args:
            file_path: Path to the file or directory, absolute or relative to /workspace/home.

        Returns:
            A success message or an error message.
        """

        async def operation(box: AsyncBox) -> None:
            await box.files.remove(file_path, recursive=True)

        try:
            await self._awith_box(run_context, operation)
            return f"Deleted: {file_path}"
        except Exception as e:
            return self._error("Error deleting file", e)

    async def aget_box_info(self, run_context: RunContext) -> str:
        """Get information about the current box.

        Returns:
            JSON with the box id, status, size, and keep-alive setting, or an error message.
        """

        async def operation(box: AsyncBox) -> str:
            return self._format_info(box, await box.get_status())

        try:
            return await self._awith_box(run_context, operation)
        except Exception as e:
            return self._error("Error getting box info", e)

    async def alist_boxes(self) -> str:
        """List the boxes this toolkit created (boxes labeled "agno").

        Returns:
            JSON list of boxes (id, name, status, runtime, labels) or an error message.
        """
        try:
            boxes = await AsyncBox.list(label=DEFAULT_LABEL, **self._connection_options())
            return self._format_boxes(boxes)
        except Exception as e:
            return self._error("Error listing boxes", e)

    async def ashutdown_box(self, run_context: RunContext) -> str:
        """Delete the current box and release its resources.

        Returns:
            A success message or an error message.
        """
        try:
            async with self._async_lock(self._session_key(run_context)):
                box_id = self._current_box_id(run_context)
                if box_id is None:
                    return "No active box to shut down."
                await self._adelete_box(box_id)
                await self._adrop_box(run_context, box_id)
                self._clear_run_box_id(run_context)
            return f"Box {box_id} shut down."
        except Exception as e:
            return self._error("Error shutting down box", e)

    async def ashutdown_box_by_id(self, run_context: RunContext, box_id: str) -> str:
        """Delete a specific box by its id, e.g. one returned by list_boxes.

        Args:
            box_id: The id of the box to delete.

        Returns:
            A success message or an error message.
        """
        try:
            await self._adelete_box(box_id)
            await self._adrop_box(run_context, box_id)
            return f"Box {box_id} shut down."
        except Exception as e:
            return self._error("Error shutting down box", e)

    async def aget_public_url(self, run_context: RunContext, port: int) -> str:
        """Get a public URL for a port a process inside the box is listening on.

        A request to the URL resumes the box if it is paused.

        Args:
            port: Port a process inside the box is listening on.

        Returns:
            A public URL routing to that port, or an error message.
        """

        async def operation(box: AsyncBox) -> str:
            return self._public_url(await box.get_public_url(port))

        try:
            return await self._awith_box(run_context, operation)
        except Exception as e:
            return self._error("Error getting public URL", e)

    # ------------------------------------------------------------------
    # Lifecycle tools (async, opt-in)
    # ------------------------------------------------------------------
    async def apause_box(self, run_context: RunContext) -> str:
        """Pause the current box to release compute. Its files are kept, and the next tool call resumes it.

        Returns:
            A success message or an error message.
        """

        async def operation(box: AsyncBox) -> str:
            await box.pause()
            return f"Box {box.id} paused."

        try:
            return await self._awith_box(run_context, operation, replace=False)
        except Exception as e:
            return self._error("Error pausing box", e)

    async def aresume_box(self, run_context: RunContext) -> str:
        """Resume the current paused box.

        Returns:
            A success message or an error message.
        """

        async def operation(box: AsyncBox) -> str:
            await box.resume()
            return f"Box {box.id} resumed."

        try:
            return await self._awith_box(run_context, operation, replace=False)
        except Exception as e:
            return self._error("Error resuming box", e)

    async def asnapshot_box(self, run_context: RunContext, name: str) -> str:
        """Save the current box's workspace as a snapshot that new boxes can be created from.

        Args:
            name: A name for the snapshot.

        Returns:
            JSON with the snapshot id, name, and status, or an error message.
        """

        async def operation(box: AsyncBox) -> str:
            return self._format_snapshot(await box.snapshot(name=name))

        try:
            return await self._awith_box(run_context, operation, replace=False)
        except Exception as e:
            return self._error("Error creating snapshot", e)
