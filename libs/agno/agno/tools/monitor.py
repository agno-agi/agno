"""MonitorTools -- give agents the ability to create and manage background monitors.

Wraps the MonitorManager to expose monitor CRUD as agent-callable tools.
Requires a database backend that implements the monitor DB methods and
the AgentOS server + MonitorPoller to actually run the monitors.

Example:
    from agno.tools.monitor import MonitorTools

    agent = Agent(
        model=OpenAIResponses(id="gpt-5.5"),
        tools=[
            MonitorTools(
                db=monitor_db,
                default_endpoint="/agents/my-agent/runs",
            )
        ],
    )
"""

import json
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple, Union

from agno.monitor.manager import MonitorManager
from agno.monitor.watch import WatchCommand
from agno.run import RunContext
from agno.tools.toolkit import Toolkit
from agno.utils.log import log_debug, logger


def _describe_watches(watches: Optional[Dict[str, str]]) -> str:
    """Render the declared watches for the tool instructions.

    Takes the normalised ``{name: description}`` mapping, never the constructor
    argument: a WatchCommand stringifies to its whole repr, command included, and
    this text goes straight into the model's instructions.
    """
    if not watches:
        return "No watches are declared on this deployment."
    lines = [f"{name} ({desc})" if desc else name for name, desc in sorted(watches.items())]
    return "Declared watches: " + "; ".join(lines) + "."


class MonitorTools(Toolkit):
    """Toolkit that lets an agent create and manage background monitors.

    The agent can start one of the watches the operator declared -- each line it
    prints becomes an event -- watch a file or directory for changes, or follow a
    run that is already executing. It can then check what condition the watch is
    in and read the events it produced. When an endpoint is set, each event pings
    that endpoint via the existing AgentOS monitor infrastructure.

    The agent selects a watch by name from the declared set. It never supplies a
    shell command, so holding this toolkit is not equivalent to holding a shell.
    A path is the one target it does name freely -- a path is data, not code --
    and ``base_dir`` is what bounds it.

    Args:
        db: A database adapter that implements the monitor DB methods.
        default_endpoint: The default endpoint events are delivered to
            (e.g. ``/agents/<agent_id>/runs``). The agent can override this
            per-monitor, but having a default simplifies the common case.
        default_method: HTTP method for the endpoint (default: ``POST``).
        default_payload: Default payload sent with each event delivery when a
            monitor does not specify its own. A per-monitor payload replaces it.
        user_id: Fixed owner for every monitor operation. When unset, the owner
            is taken from the run's ``user_id`` (injected via ``run_context``),
            so each user's agent only sees and edits that user's monitors.
        watches: The watches declared on AgentOS via ``watch_commands``. Three
            forms: the AgentOS mapping itself when its values are WatchCommands
            (each one's ``description`` is used, so there is no second mapping to
            keep in step), a ``{name: what it watches}`` mapping, or a bare list
            of names. A mapping of plain strings is read as descriptions, not
            commands -- so do not hand this the bare-string form of the AgentOS
            mapping, or the model is shown the shell strings this toolkit exists
            to keep away from it.

            Prefer whichever form carries descriptions: a bare list tells the
            model what it may start but nothing about what each one does, and a
            model asked to watch something with no matching watch will pick the
            closest-sounding name and report success. The descriptions are what
            let it answer "none of these fit" instead. A name outside the set is
            refused before it reaches the database, so a prompt injection cannot
            turn this toolkit into shell access.
        allowed_endpoints: Extra destinations the model may deliver to, beyond
            ``default_endpoint``. Anything outside the set is refused the same
            way an undeclared watch name is. Leave it unset and the default
            endpoint is the only destination -- which is the safe reading of
            "the agent picks what to watch, the operator picks where it lands".
            Choosing a destination is a real grant: events are delivered with
            the internal service token, so a freely chosen endpoint means the
            model can start a run on any agent, team or workflow in the
            deployment. The HTTP route gates that on the caller's scopes; a
            toolkit has no caller scopes, so the operator names them here.
        max_monitors_per_user: How many unfinished monitors one owner may have
            through this toolkit (default: 20, matching AgentOS; 0 lifts it).
            The HTTP route enforces its own ceiling, and this is the same
            ceiling on the door a model can walk through.
        base_dir: The root ``watch_files`` may watch inside. Paths are given
            relative to it and anything resolving outside is refused before it
            reaches the database, the way an undeclared watch name is -- each
            path separately when the model names several, so a list is not a way
            past it. None means the process working directory. The model chooses
            the path here, so this is what stands between "watch a file" and a
            watch on the operator's secrets directory naming every file in it in
            its events.
    """

    def __init__(
        self,
        db: Any,
        default_endpoint: Optional[str] = None,
        default_method: str = "POST",
        default_payload: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        watches: Optional[Union[List[str], Mapping[str, Union[str, WatchCommand]]]] = None,
        allowed_endpoints: Optional[List[str]] = None,
        max_monitors_per_user: int = 20,
        base_dir: Optional[str] = None,
        **kwargs: Any,
    ):
        # Toolkit.add_instructions defaults to False; opt in so the guardrails
        # below (filter output, when to use persistent) actually reach the model.
        kwargs.setdefault("add_instructions", True)
        # Capped by default, unlike a bare MonitorManager: the caller here is a
        # model, so an unbounded create loop is one bad turn away rather than a
        # deliberate act. 0 lifts it. The root goes to the manager rather than
        # being checked here, so the containment is decided in one place for
        # every door into creation rather than once per caller.
        self.manager = MonitorManager(db=db, max_per_user=max_monitors_per_user, base_dir=base_dir)
        self.default_endpoint = default_endpoint
        self.default_method = default_method
        self.default_payload = default_payload
        self.user_id = user_id
        # Destinations the model may choose between. The default endpoint is
        # always one of them; without this the default is the ONLY one, because
        # an unrestricted endpoint is a bigger grant than it looks: the executor
        # delivers with the internal service token, so an endpoint the model
        # picked freely means it can start a run on any agent, team or workflow
        # in the deployment. The HTTP route gates that same choice on the
        # caller's scopes -- a toolkit has no caller scopes to gate on, so the
        # operator names the destinations instead, the way they name the watches.
        self.allowed_endpoints = list(allowed_endpoints) if allowed_endpoints is not None else None
        # Normalised to {name: description}. A WatchCommand carries its own
        # description, so handing this the same mapping AgentOS was given needs
        # no second parallel dict; a bare list becomes empty descriptions.
        if watches is None:
            self.watches: Optional[Dict[str, str]] = None
        elif isinstance(watches, Mapping):
            self.watches = {
                name: (declared.description if isinstance(declared, WatchCommand) else declared or "")
                for name, declared in watches.items()
            }
        else:
            self.watches = {name: "" for name in watches}

        # These are named *_watch, not *_monitor, and must stay that way. Tool
        # names are a flat namespace across every toolkit on an agent, and
        # ParallelTools already registers create_monitor, get_monitor,
        # get_monitor_events and list_monitors. An agent holding both toolkits
        # would silently get whichever registered last -- there is no duplicate
        # detection -- and the symptom is an unrelated error from the other
        # service, not anything pointing here. The <verb>_<noun> convention the
        # rest of the toolkits follow is the trap; do not "fix" these back.
        tools: List[Callable] = [
            self.start_watch,
            self.watch_run,
            self.watch_files,
            self.list_watches,
            self.get_watch,
            self.get_watch_events,
            self.stop_watch,
            self.restart_watch,
            self.delete_watch,
        ]

        async_tools: List[tuple[Callable[..., Any], str]] = [
            (self.astart_watch, "start_watch"),
            (self.awatch_run, "watch_run"),
            (self.awatch_files, "watch_files"),
            (self.alist_watches, "list_watches"),
            (self.aget_watch, "get_watch"),
            (self.aget_watch_events, "get_watch_events"),
            (self.astop_watch, "stop_watch"),
            (self.arestart_watch, "restart_watch"),
            (self.adelete_watch, "delete_watch"),
        ]

        super().__init__(
            name="monitor",
            tools=tools,
            async_tools=async_tools,
            instructions=(
                "Use these tools to watch long-running things in the background. "
                "To watch a run that is already executing (a background run you or someone else started), "
                "use watch_run with its run_id -- it emits one event when that run finishes. "
                "To watch a file or directory, use watch_files with its path -- it emits one event "
                "each time something there changes, naming what changed. Give it a list of paths to "
                "watch several at once as one watch, and use exclude to name glob patterns you do not "
                "want events for, such as build output or a log you already read elsewhere. Ordinary "
                "noise -- .git, .venv, __pycache__, node_modules, compiled Python, editor swap files -- "
                "is already left out; set use_default_filter=False only when you are watching something "
                "on that list and nothing is arriving. The path is relative to the "
                "directory this deployment allows watching in; anything outside it is refused. "
                "To watch anything else, use start_watch and pick one of the declared watches. "
                f"{_describe_watches(self.watches)} "
                "You choose from that list; you cannot define a new watch. "
                "If none of them watches what you were asked about, say so plainly and start nothing -- "
                "never substitute a different watch and report it as done. "
                "Each line the watch prints becomes an event, and a watch that ends stops the monitor: "
                "exit code 0 means completed, non-zero means failed. "
                "Only set an endpoint when events should be delivered to an agent, team, or workflow; "
                "otherwise omit it and read the events yourself with get_watch_events. "
                "Use get_watch to check what condition a watch is in and get_watch_events to read "
                "what it produced. Set persistent=True for watches that should run until stopped."
            ),
            **kwargs,
        )

    def _owner(self, run_context: Optional[RunContext]) -> Optional[str]:
        """Resolve the acting owner: a fixed toolkit user_id wins, else the run's user."""
        if self.user_id is not None:
            return self.user_id
        return run_context.user_id if run_context is not None else None

    def _declared_description(self, watch: str, description: Optional[str]) -> Optional[str]:
        """Fall back to the declaration's own description when the model gave none.

        A monitor started from a declared watch otherwise carries nothing but the
        watch's name, and a name is not a description -- whoever reads the row
        back is left with the same guess the model would have made. The
        operator's description is already here, normalised alongside the name.

        The command string stays out of this, as it does everywhere else: it is
        operator-authored, can hold whatever was to hand, and keeping it away
        from the model is the whole point of naming watches. The description is
        the operator's own publishable sentence about the same command.
        """
        if description is not None and description.strip():
            return description
        return (self.watches or {}).get(watch) or description

    @staticmethod
    def _monitor_summary(monitor: Any) -> Dict[str, Any]:
        """Build the JSON summary returned for a monitor."""
        return {
            "id": monitor.id,
            "name": monitor.name,
            "watch_path": monitor.watch_path,
            "watch_command": monitor.watch_command,
            "watch_run_id": monitor.watch_run_id,
            "status": monitor.status,
            "endpoint": monitor.endpoint,
            "persistent": monitor.persistent,
            "event_count": monitor.event_count,
            "description": monitor.description,
        }

    # ------------------------------------------------------------------
    # Sync tools
    # ------------------------------------------------------------------

    def _resolve_endpoint(self, endpoint: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        """Where this monitor may deliver, or a refusal to hand back to the model.

        Returns ``(endpoint, None)`` when the destination is permitted and
        ``(None, refusal)`` when it is not. Asking for nothing is always fine:
        it means the operator's default, which is what most monitors want.
        """
        # An empty string is how a model says "nothing here", so it means the same
        # as omitting the argument. Treating it as a destination instead refuses
        # the one call that was already correct, and the model then hunts for a
        # sentinel it will accept -- "_DEFAULT", "-", "/dev/null", "__OMIT__" --
        # burning a call on each guess.
        if endpoint is None or not endpoint.strip():
            return self.default_endpoint, None

        permitted = {e for e in [*(self.allowed_endpoints or []), self.default_endpoint] if e}
        if endpoint in permitted:
            return endpoint, None
        # When nothing is permitted, "use the default" is not advice the model can
        # act on -- there is no default to fall back to. Say the thing that works.
        remedy = (
            f"Permitted: {sorted(permitted)}. Leave endpoint unset to use the default."
            if permitted
            else "This deployment delivers to no endpoint at all. Omit endpoint entirely; "
            "the watch will record its events for someone to read."
        )
        return None, json.dumps({"error": f"Endpoint {endpoint!r} is not one this deployment delivers to. {remedy}"})

    def start_watch(
        self,
        name: str,
        watch: str,
        description: Optional[str] = None,
        endpoint: Optional[str] = None,
        payload: Optional[str] = None,
        timeout_seconds: int = 300,
        persistent: bool = False,
        max_events: int = 100,
        run_context: Optional[RunContext] = None,
    ) -> str:
        """Start one of the watches this deployment declares. Each line it prints becomes an event.

        Args:
            name (str): A unique name for this watch instance (e.g. "watch-error-log").
            watch (str): Which declared watch to start. Must be one of the names listed above.
            description (str): A human-readable description of what is being watched.
            endpoint (str): The API endpoint events are delivered to. Uses the default if not provided.
            payload (str): JSON string of extra fields merged into each event delivery.
            timeout_seconds (int): Stop the watch after this many seconds. Defaults to 300.
            persistent (bool): If True, run until stopped with no timeout. Defaults to False.
            max_events (int): Auto-stop after this many events. Defaults to 100. 0 means
                unlimited, which is only allowed when no endpoint is set -- a persistent
                watch that delivers must have a cap, because every event it delivers
                starts a real run.

        Returns:
            str: JSON string with the created monitor details.
        """
        if self.watches is not None and watch not in self.watches:
            return json.dumps(
                {
                    "error": f"Unknown watch {watch!r}. Declared: {sorted(self.watches)}. "
                    "If none of these watches what you were asked about, say so instead of picking one."
                }
            )

        resolved_endpoint, refusal = self._resolve_endpoint(endpoint)
        if refusal is not None:
            return refusal

        resolved_payload = self.default_payload
        if payload:
            try:
                resolved_payload = json.loads(payload)
            except json.JSONDecodeError:
                return json.dumps({"error": "Invalid JSON in payload parameter"})

        try:
            monitor = self.manager.create(
                name=name,
                watch_command=watch,
                endpoint=resolved_endpoint,
                method=self.default_method,
                description=self._declared_description(watch, description),
                payload=resolved_payload,
                timeout_seconds=timeout_seconds,
                persistent=persistent,
                max_events=max_events,
                user_id=self._owner(run_context),
            )
            log_debug(f"Monitor created: {monitor.name} ({monitor.id})")
            return json.dumps(self._monitor_summary(monitor))
        except ValueError as e:
            # A refusal this toolkit authored -- an undeclared watch, the quota,
            # the event budget -- is an expected answer to hand the model, not a
            # fault to dump a traceback for.
            log_debug(f"Monitor create refused: {e}")
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.exception("Failed to create monitor")
            return json.dumps({"error": str(e)})

    def watch_run(
        self,
        name: str,
        run_id: str,
        description: Optional[str] = None,
        endpoint: Optional[str] = None,
        payload: Optional[str] = None,
        timeout_seconds: int = 3600,
        run_context: Optional[RunContext] = None,
    ) -> str:
        """Watch a run that is already executing and get one event when it finishes.

        Args:
            name (str): A unique name for the watch (e.g. "watch-research-run").
            run_id (str): The ID of the run to follow, as returned when it was started.
            description (str): A human-readable description of what is being watched.
            endpoint (str): The API endpoint the finish event is delivered to. Uses the default if not provided.
            payload (str): JSON string of extra fields merged into the event delivery.
            timeout_seconds (int): Give up if the run has not finished after this many seconds. Defaults to 3600.

        Returns:
            str: JSON string with the created monitor details.
        """
        resolved_endpoint, refusal = self._resolve_endpoint(endpoint)
        if refusal is not None:
            return refusal

        resolved_payload = self.default_payload
        if payload:
            try:
                resolved_payload = json.loads(payload)
            except json.JSONDecodeError:
                return json.dumps({"error": "Invalid JSON in payload parameter"})

        try:
            monitor = self.manager.create(
                name=name,
                watch_run_id=run_id,
                endpoint=resolved_endpoint,
                method=self.default_method,
                description=description,
                payload=resolved_payload,
                timeout_seconds=timeout_seconds,
                # A run watch emits exactly one event, so there is nothing for a
                # persistent watch or a higher event cap to keep producing.
                max_events=1,
                user_id=self._owner(run_context),
            )
            log_debug(f"Run watch created: {monitor.name} ({monitor.id}) for run {run_id}")
            return json.dumps(self._monitor_summary(monitor))
        except ValueError as e:
            # Same contract as start_watch: a refusal this toolkit authored -- the
            # quota, a duplicate name, an unusable owner -- is an expected answer
            # to hand the model, not a fault to dump a traceback for.
            log_debug(f"Run watch refused: {e}")
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.exception("Failed to create run watch")
            return json.dumps({"error": str(e)})

    def watch_files(
        self,
        name: str,
        path: Union[str, List[str]],
        description: Optional[str] = None,
        exclude: Optional[List[str]] = None,
        use_default_filter: bool = True,
        endpoint: Optional[str] = None,
        payload: Optional[str] = None,
        timeout_seconds: int = 300,
        persistent: bool = True,
        max_events: int = 100,
        run_context: Optional[RunContext] = None,
    ) -> str:
        """Watch files or directories and get an event each time something there changes.

        Args:
            name (str): A unique name for this watch (e.g. "watch-inbox").
            path (str): The file or directory to watch, relative to the directory this
                deployment allows watching in. A path outside it is refused. Pass a list
                to watch several at once as one watch.
            description (str): A human-readable description of what is being watched.
            exclude (list): Glob patterns to ignore, e.g. ["*.tmp", "dist/*"]. Nothing
                matching them produces an event.
            use_default_filter (bool): Keep the built-in exclusions (.git, .venv,
                __pycache__, node_modules, compiled Python, editor swap files). Defaults
                to True; set False only when watching something on that list.
            endpoint (str): The API endpoint events are delivered to. Uses the default if not provided.
            payload (str): JSON string of extra fields merged into each event delivery.
            timeout_seconds (int): Stop the watch after this many seconds. Ignored when persistent.
                Defaults to 300.
            persistent (bool): If True, watch until stopped with no timeout. Defaults to True.
            max_events (int): Auto-stop after this many events. Defaults to 100. 0 means
                unlimited, which is only allowed when no endpoint is set -- a persistent
                watch that delivers must have a cap, because every event it delivers
                starts a real run.

        Returns:
            str: JSON string with the created monitor details.
        """
        resolved_endpoint, refusal = self._resolve_endpoint(endpoint)
        if refusal is not None:
            return refusal

        resolved_payload = self.default_payload
        if payload:
            try:
                resolved_payload = json.loads(payload)
            except json.JSONDecodeError:
                return json.dumps({"error": "Invalid JSON in payload parameter"})

        try:
            monitor = self.manager.create(
                name=name,
                watch_path=path,
                exclude=exclude,
                use_default_filter=use_default_filter,
                endpoint=resolved_endpoint,
                method=self.default_method,
                description=description,
                payload=resolved_payload,
                timeout_seconds=timeout_seconds,
                persistent=persistent,
                max_events=max_events,
                user_id=self._owner(run_context),
            )
            log_debug(f"Path watch created: {monitor.name} ({monitor.id}) for {path}")
            return json.dumps(self._monitor_summary(monitor))
        except ValueError as e:
            # Same contract as start_watch: a refusal this toolkit authored -- a
            # path outside the allowed root, the quota, the event budget -- is an
            # expected answer to hand the model, not a fault to dump a traceback
            # for. Raising here would surface to the model as a tool crash, which
            # tells it nothing about how to ask for something permitted.
            log_debug(f"Path watch refused: {e}")
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.exception("Failed to create path watch")
            return json.dumps({"error": str(e)})

    def list_watches(self, status: Optional[str] = None, run_context: Optional[RunContext] = None) -> str:
        """List all existing monitors.

        Args:
            status (str): Optionally filter by status (pending, running, stopping, completed, failed, timeout, stopped).

        Returns:
            str: JSON string with the list of monitors.
        """
        try:
            monitors = self.manager.list(status=status or None, user_id=self._owner(run_context))
            result = [self._monitor_summary(m) for m in monitors]
            return json.dumps({"monitors": result, "count": len(result)})
        except Exception as e:
            logger.exception("Failed to list monitors")
            return json.dumps({"error": str(e)})

    def get_watch(self, watch_id: str, run_context: Optional[RunContext] = None) -> str:
        """Get the current condition of a monitor by its ID.

        Args:
            watch_id (str): The ID of the watch to retrieve.

        Returns:
            str: JSON string with the monitor details, including status, exit code, and error.
        """
        try:
            monitor = self.manager.get(watch_id, user_id=self._owner(run_context))
            if monitor is None:
                return json.dumps({"error": f"Watch not found: {watch_id}"})
            return json.dumps(
                {
                    **self._monitor_summary(monitor),
                    "exit_code": monitor.exit_code,
                    "error": monitor.error,
                    "started_at": monitor.started_at,
                    "finished_at": monitor.finished_at,
                    "timeout_seconds": monitor.timeout_seconds,
                    "max_events": monitor.max_events,
                }
            )
        except Exception as e:
            logger.exception("Failed to get monitor")
            return json.dumps({"error": str(e)})

    def get_watch_events(self, watch_id: str, limit: int = 10, run_context: Optional[RunContext] = None) -> str:
        """Get the most recent events emitted by a monitor.

        Args:
            watch_id (str): The ID of the watch to get events for.
            limit (int): Maximum number of events to return. Defaults to 10.

        Returns:
            str: JSON string with the list of events.
        """
        try:
            events = self.manager.get_events(watch_id, limit=limit, user_id=self._owner(run_context))
            result = [
                {
                    "seq": e.seq,
                    "content": e.content,
                    "delivery_status": e.delivery_status,
                    "run_id": e.run_id,
                    "created_at": e.created_at,
                }
                for e in events
            ]
            return json.dumps({"events": result, "count": len(result)})
        except Exception as e:
            logger.exception("Failed to get monitor events")
            return json.dumps({"error": str(e)})

    def stop_watch(self, watch_id: str, run_context: Optional[RunContext] = None) -> str:
        """Stop a pending or running monitor.

        Args:
            watch_id (str): The ID of the watch to stop.

        Returns:
            str: JSON string with the updated monitor status.
        """
        try:
            monitor = self.manager.stop(watch_id, user_id=self._owner(run_context))
            if monitor is None:
                return json.dumps({"error": f"Watch not found: {watch_id}"})
            return json.dumps({"status": monitor.status, "id": monitor.id, "name": monitor.name})
        except Exception as e:
            logger.exception("Failed to stop monitor")
            return json.dumps({"error": str(e)})

    def restart_watch(self, watch_id: str, run_context: Optional[RunContext] = None) -> str:
        """Restart a finished monitor so it is picked up and run again.

        Args:
            watch_id (str): The ID of the watch to restart.

        Returns:
            str: JSON string with the updated monitor status.
        """
        try:
            monitor = self.manager.restart(watch_id, user_id=self._owner(run_context))
            if monitor is None:
                return json.dumps({"error": f"Watch not found: {watch_id}"})
            return json.dumps({"status": monitor.status, "id": monitor.id, "name": monitor.name})
        except Exception as e:
            logger.exception("Failed to restart monitor")
            return json.dumps({"error": str(e)})

    def delete_watch(self, watch_id: str, run_context: Optional[RunContext] = None) -> str:
        """Delete a monitor and its events. A running monitor is killed first.

        Args:
            watch_id (str): The ID of the watch to delete.

        Returns:
            str: JSON string confirming deletion.
        """
        try:
            deleted = self.manager.delete(watch_id, user_id=self._owner(run_context))
            if deleted:
                return json.dumps({"status": "deleted", "id": watch_id})
            return json.dumps({"error": f"Watch not found or could not be deleted: {watch_id}"})
        except Exception as e:
            logger.exception("Failed to delete monitor")
            return json.dumps({"error": str(e)})

    # ------------------------------------------------------------------
    # Async tools
    # ------------------------------------------------------------------

    async def astart_watch(
        self,
        name: str,
        watch: str,
        description: Optional[str] = None,
        endpoint: Optional[str] = None,
        payload: Optional[str] = None,
        timeout_seconds: int = 300,
        persistent: bool = False,
        max_events: int = 100,
        run_context: Optional[RunContext] = None,
    ) -> str:
        """Start one of the watches this deployment declares. Each line it prints becomes an event.

        Args:
            name (str): A unique name for this watch instance (e.g. "watch-error-log").
            watch (str): Which declared watch to start. Must be one of the names listed above.
            description (str): A human-readable description of what is being watched.
            endpoint (str): The API endpoint events are delivered to. Uses the default if not provided.
            payload (str): JSON string of extra fields merged into each event delivery.
            timeout_seconds (int): Stop the watch after this many seconds. Defaults to 300.
            persistent (bool): If True, run until stopped with no timeout. Defaults to False.
            max_events (int): Auto-stop after this many events. Defaults to 100. 0 means
                unlimited, which is only allowed when no endpoint is set -- a persistent
                watch that delivers must have a cap, because every event it delivers
                starts a real run.

        Returns:
            str: JSON string with the created monitor details.
        """
        if self.watches is not None and watch not in self.watches:
            return json.dumps(
                {
                    "error": f"Unknown watch {watch!r}. Declared: {sorted(self.watches)}. "
                    "If none of these watches what you were asked about, say so instead of picking one."
                }
            )

        resolved_endpoint, refusal = self._resolve_endpoint(endpoint)
        if refusal is not None:
            return refusal

        resolved_payload = self.default_payload
        if payload:
            try:
                resolved_payload = json.loads(payload)
            except json.JSONDecodeError:
                return json.dumps({"error": "Invalid JSON in payload parameter"})

        try:
            monitor = await self.manager.acreate(
                name=name,
                watch_command=watch,
                endpoint=resolved_endpoint,
                method=self.default_method,
                description=self._declared_description(watch, description),
                payload=resolved_payload,
                timeout_seconds=timeout_seconds,
                persistent=persistent,
                max_events=max_events,
                user_id=self._owner(run_context),
            )
            log_debug(f"Monitor created: {monitor.name} ({monitor.id})")
            return json.dumps(self._monitor_summary(monitor))
        except ValueError as e:
            # A refusal this toolkit authored -- an undeclared watch, the quota,
            # the event budget -- is an expected answer to hand the model, not a
            # fault to dump a traceback for.
            log_debug(f"Monitor create refused: {e}")
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.exception("Failed to create monitor")
            return json.dumps({"error": str(e)})

    async def awatch_run(
        self,
        name: str,
        run_id: str,
        description: Optional[str] = None,
        endpoint: Optional[str] = None,
        payload: Optional[str] = None,
        timeout_seconds: int = 3600,
        run_context: Optional[RunContext] = None,
    ) -> str:
        """Watch a run that is already executing and get one event when it finishes.

        Args:
            name (str): A unique name for the watch (e.g. "watch-research-run").
            run_id (str): The ID of the run to follow, as returned when it was started.
            description (str): A human-readable description of what is being watched.
            endpoint (str): The API endpoint the finish event is delivered to. Uses the default if not provided.
            payload (str): JSON string of extra fields merged into the event delivery.
            timeout_seconds (int): Give up if the run has not finished after this many seconds. Defaults to 3600.

        Returns:
            str: JSON string with the created monitor details.
        """
        resolved_endpoint, refusal = self._resolve_endpoint(endpoint)
        if refusal is not None:
            return refusal

        resolved_payload = self.default_payload
        if payload:
            try:
                resolved_payload = json.loads(payload)
            except json.JSONDecodeError:
                return json.dumps({"error": "Invalid JSON in payload parameter"})

        try:
            monitor = await self.manager.acreate(
                name=name,
                watch_run_id=run_id,
                endpoint=resolved_endpoint,
                method=self.default_method,
                description=description,
                payload=resolved_payload,
                timeout_seconds=timeout_seconds,
                # A run watch emits exactly one event, so there is nothing for a
                # persistent watch or a higher event cap to keep producing.
                max_events=1,
                user_id=self._owner(run_context),
            )
            log_debug(f"Run watch created: {monitor.name} ({monitor.id}) for run {run_id}")
            return json.dumps(self._monitor_summary(monitor))
        except ValueError as e:
            # Same contract as start_watch: a refusal this toolkit authored -- the
            # quota, a duplicate name, an unusable owner -- is an expected answer
            # to hand the model, not a fault to dump a traceback for.
            log_debug(f"Run watch refused: {e}")
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.exception("Failed to create run watch")
            return json.dumps({"error": str(e)})

    async def awatch_files(
        self,
        name: str,
        path: Union[str, List[str]],
        description: Optional[str] = None,
        exclude: Optional[List[str]] = None,
        use_default_filter: bool = True,
        endpoint: Optional[str] = None,
        payload: Optional[str] = None,
        timeout_seconds: int = 300,
        persistent: bool = True,
        max_events: int = 100,
        run_context: Optional[RunContext] = None,
    ) -> str:
        """Watch files or directories and get an event each time something there changes.

        Args:
            name (str): A unique name for this watch (e.g. "watch-inbox").
            path (str): The file or directory to watch, relative to the directory this
                deployment allows watching in. A path outside it is refused. Pass a list
                to watch several at once as one watch.
            description (str): A human-readable description of what is being watched.
            exclude (list): Glob patterns to ignore, e.g. ["*.tmp", "dist/*"]. Nothing
                matching them produces an event.
            use_default_filter (bool): Keep the built-in exclusions (.git, .venv,
                __pycache__, node_modules, compiled Python, editor swap files). Defaults
                to True; set False only when watching something on that list.
            endpoint (str): The API endpoint events are delivered to. Uses the default if not provided.
            payload (str): JSON string of extra fields merged into each event delivery.
            timeout_seconds (int): Stop the watch after this many seconds. Ignored when persistent.
                Defaults to 300.
            persistent (bool): If True, watch until stopped with no timeout. Defaults to True.
            max_events (int): Auto-stop after this many events. Defaults to 100. 0 means
                unlimited, which is only allowed when no endpoint is set -- a persistent
                watch that delivers must have a cap, because every event it delivers
                starts a real run.

        Returns:
            str: JSON string with the created monitor details.
        """
        resolved_endpoint, refusal = self._resolve_endpoint(endpoint)
        if refusal is not None:
            return refusal

        resolved_payload = self.default_payload
        if payload:
            try:
                resolved_payload = json.loads(payload)
            except json.JSONDecodeError:
                return json.dumps({"error": "Invalid JSON in payload parameter"})

        try:
            monitor = await self.manager.acreate(
                name=name,
                watch_path=path,
                exclude=exclude,
                use_default_filter=use_default_filter,
                endpoint=resolved_endpoint,
                method=self.default_method,
                description=description,
                payload=resolved_payload,
                timeout_seconds=timeout_seconds,
                persistent=persistent,
                max_events=max_events,
                user_id=self._owner(run_context),
            )
            log_debug(f"Path watch created: {monitor.name} ({monitor.id}) for {path}")
            return json.dumps(self._monitor_summary(monitor))
        except ValueError as e:
            # Same contract as start_watch: a refusal this toolkit authored -- a
            # path outside the allowed root, the quota, the event budget -- is an
            # expected answer to hand the model, not a fault to dump a traceback
            # for. Raising here would surface to the model as a tool crash, which
            # tells it nothing about how to ask for something permitted.
            log_debug(f"Path watch refused: {e}")
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.exception("Failed to create path watch")
            return json.dumps({"error": str(e)})

    async def alist_watches(self, status: Optional[str] = None, run_context: Optional[RunContext] = None) -> str:
        """List all existing monitors.

        Args:
            status (str): Optionally filter by status (pending, running, stopping, completed, failed, timeout, stopped).

        Returns:
            str: JSON string with the list of monitors.
        """
        try:
            monitors = await self.manager.alist(status=status or None, user_id=self._owner(run_context))
            result = [self._monitor_summary(m) for m in monitors]
            return json.dumps({"monitors": result, "count": len(result)})
        except Exception as e:
            logger.exception("Failed to list monitors")
            return json.dumps({"error": str(e)})

    async def aget_watch(self, watch_id: str, run_context: Optional[RunContext] = None) -> str:
        """Get the current condition of a monitor by its ID.

        Args:
            watch_id (str): The ID of the watch to retrieve.

        Returns:
            str: JSON string with the monitor details, including status, exit code, and error.
        """
        try:
            monitor = await self.manager.aget(watch_id, user_id=self._owner(run_context))
            if monitor is None:
                return json.dumps({"error": f"Watch not found: {watch_id}"})
            return json.dumps(
                {
                    **self._monitor_summary(monitor),
                    "exit_code": monitor.exit_code,
                    "error": monitor.error,
                    "started_at": monitor.started_at,
                    "finished_at": monitor.finished_at,
                    "timeout_seconds": monitor.timeout_seconds,
                    "max_events": monitor.max_events,
                }
            )
        except Exception as e:
            logger.exception("Failed to get monitor")
            return json.dumps({"error": str(e)})

    async def aget_watch_events(self, watch_id: str, limit: int = 10, run_context: Optional[RunContext] = None) -> str:
        """Get the most recent events emitted by a monitor.

        Args:
            watch_id (str): The ID of the watch to get events for.
            limit (int): Maximum number of events to return. Defaults to 10.

        Returns:
            str: JSON string with the list of events.
        """
        try:
            events = await self.manager.aget_events(watch_id, limit=limit, user_id=self._owner(run_context))
            result = [
                {
                    "seq": e.seq,
                    "content": e.content,
                    "delivery_status": e.delivery_status,
                    "run_id": e.run_id,
                    "created_at": e.created_at,
                }
                for e in events
            ]
            return json.dumps({"events": result, "count": len(result)})
        except Exception as e:
            logger.exception("Failed to get monitor events")
            return json.dumps({"error": str(e)})

    async def astop_watch(self, watch_id: str, run_context: Optional[RunContext] = None) -> str:
        """Stop a pending or running monitor.

        Args:
            watch_id (str): The ID of the watch to stop.

        Returns:
            str: JSON string with the updated monitor status.
        """
        try:
            monitor = await self.manager.astop(watch_id, user_id=self._owner(run_context))
            if monitor is None:
                return json.dumps({"error": f"Watch not found: {watch_id}"})
            return json.dumps({"status": monitor.status, "id": monitor.id, "name": monitor.name})
        except Exception as e:
            logger.exception("Failed to stop monitor")
            return json.dumps({"error": str(e)})

    async def arestart_watch(self, watch_id: str, run_context: Optional[RunContext] = None) -> str:
        """Restart a finished monitor so it is picked up and run again.

        Args:
            watch_id (str): The ID of the watch to restart.

        Returns:
            str: JSON string with the updated monitor status.
        """
        try:
            monitor = await self.manager.arestart(watch_id, user_id=self._owner(run_context))
            if monitor is None:
                return json.dumps({"error": f"Watch not found: {watch_id}"})
            return json.dumps({"status": monitor.status, "id": monitor.id, "name": monitor.name})
        except Exception as e:
            logger.exception("Failed to restart monitor")
            return json.dumps({"error": str(e)})

    async def adelete_watch(self, watch_id: str, run_context: Optional[RunContext] = None) -> str:
        """Delete a monitor and its events. A running monitor is killed first.

        Args:
            watch_id (str): The ID of the watch to delete.

        Returns:
            str: JSON string confirming deletion.
        """
        try:
            deleted = await self.manager.adelete(watch_id, user_id=self._owner(run_context))
            if deleted:
                return json.dumps({"status": "deleted", "id": watch_id})
            return json.dumps({"error": f"Watch not found or could not be deleted: {watch_id}"})
        except Exception as e:
            logger.exception("Failed to delete monitor")
            return json.dumps({"error": str(e)})
