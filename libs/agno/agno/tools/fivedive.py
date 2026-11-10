import json
import shutil
import subprocess
from typing import Any, List, Optional, Tuple

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_info, log_warning


class FiveDiveTools(Toolkit):
    def __init__(
        self,
        cli_path: str = "5dive",
        agent_type: str = "claude",
        timeout: int = 120,
        enable_deploy_agent: bool = True,
        enable_fleet_status: bool = True,
        enable_request_approval: bool = True,
        all: bool = False,
        **kwargs,
    ):
        """Initialize FiveDiveTools, a toolkit for running a 5dive agent fleet.

        5dive (https://5dive.ai) hosts and orchestrates autonomous coding agents. This
        toolkit shells out to the local ``5dive`` command line tool, so the user must have
        it installed and authenticated first (see https://5dive.ai). No 5dive Python
        package is required; the toolkit only uses the standard library ``subprocess``.

        Args:
            cli_path: Path or name of the 5dive CLI executable. Defaults to ``"5dive"``.
            agent_type: Default runtime type for newly deployed agents. Defaults to ``"claude"``.
            timeout: Per-command timeout in seconds. Defaults to 120.
            enable_deploy_agent: Register the ``deploy_agent`` tool. Defaults to True.
            enable_fleet_status: Register the ``fleet_status`` tool. Defaults to True.
            enable_request_approval: Register the ``request_approval`` tool. Defaults to True.
            all: Register every tool, ignoring the individual flags. Defaults to False.
            **kwargs: Additional arguments passed to Toolkit.
        """
        self.cli_path = cli_path
        self.agent_type = agent_type
        self.timeout = timeout

        tools: List[Any] = []
        if all or enable_deploy_agent:
            tools.append(self.deploy_agent)
        if all or enable_fleet_status:
            tools.append(self.fleet_status)
        if all or enable_request_approval:
            tools.append(self.request_approval)

        super().__init__(name="fivedive", tools=tools, **kwargs)

    def _run(self, args: List[str]) -> Tuple[bool, str]:
        """Run a ``5dive`` CLI command.

        Centralises handling of the CLI being missing, unauthenticated, timing out, or
        exiting non-zero, so every tool can surface a plain-language error the model can
        relay to the user.

        Returns:
            Tuple[bool, str]: ``(ok, output)`` where ``output`` is stdout on success or a
            human-readable error message on failure.
        """
        if shutil.which(self.cli_path) is None:
            msg = (
                f"The 5dive CLI (`{self.cli_path}`) was not found on PATH. Install it "
                "from https://5dive.ai and run `5dive init` to authenticate before using "
                "this toolkit."
            )
            log_error(msg)
            return False, msg

        cmd = [self.cli_path, *args]
        try:
            log_info(f"Running 5dive command: {cmd}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except FileNotFoundError:
            msg = f"The 5dive CLI (`{self.cli_path}`) could not be executed."
            log_error(msg)
            return False, msg
        except subprocess.TimeoutExpired:
            msg = f"5dive command timed out after {self.timeout}s: {' '.join(cmd)}"
            log_warning(msg)
            return False, msg

        log_debug(f"5dive return code: {result.returncode}")
        if result.returncode != 0:
            stderr = (result.stderr or result.stdout or "").strip()
            hint = ""
            if "auth" in stderr.lower() or "sign in" in stderr.lower():
                hint = " The CLI may not be authenticated; run `5dive init`."
            return False, f"Error: 5dive command failed (exit {result.returncode}): {stderr}{hint}"
        return True, result.stdout.strip()

    @staticmethod
    def _extract_task_id(payload: str) -> Optional[str]:
        """Best-effort parse of a task id from ``5dive task add --json`` output."""
        try:
            data = json.loads(payload)
        except (ValueError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        inner = data.get("data", data)
        candidates = [inner]
        if isinstance(inner, dict) and isinstance(inner.get("task"), dict):
            candidates.append(inner["task"])
        for obj in candidates:
            if isinstance(obj, dict):
                for key in ("display_id", "id", "task_id"):
                    if obj.get(key):
                        return str(obj[key])
        return None

    def deploy_agent(
        self,
        name: str,
        prompt: str,
        agent_type: Optional[str] = None,
        channels: str = "none",
        workdir: Optional[str] = None,
    ) -> str:
        """Provision a new 5dive agent and give it an initial prompt to start on.

        Creates a fresh hosted agent on the user's 5dive account, then sends it the prompt
        as its first instruction so it begins working immediately. Use this to spin up a
        worker or teammate for a task you want run autonomously.

        Args:
            name (str): Unique handle for the new agent (e.g. "researcher"). Lowercase, no spaces.
            prompt (str): The initial instruction or mission for the agent to begin working on.
            agent_type (Optional[str]): Runtime type such as "claude". Defaults to the toolkit's configured type.
            channels (str): Comma-separated channels to attach, e.g. "none", "telegram", "dashboard". Defaults to "none".
            workdir (Optional[str]): Optional working directory for the agent.

        Returns:
            str: A confirmation including the agent name, or a clear error string.
        """
        create_args = [
            "agent",
            "create",
            name,
            f"--type={agent_type or self.agent_type}",
            f"--channels={channels}",
        ]
        if workdir:
            create_args.append(f"--workdir={workdir}")

        created_ok, created_out = self._run(create_args)
        if not created_ok:
            return created_out

        log_debug(f"Agent created: {created_out}")
        sent_ok, sent_out = self._run(["agent", "send", name, prompt])
        if not sent_ok:
            return f"Agent '{name}' was created, but the initial prompt could not be delivered: {sent_out}"
        return f"Deployed 5dive agent '{name}' and delivered its initial prompt."

    def fleet_status(self) -> str:
        """Return the current status of every agent in the user's 5dive fleet.

        Lists each managed agent with its state (running, stopped, ...), type, and channel.
        Use this to see what is deployed before acting.

        Returns:
            str: The fleet listing as a JSON string, or a clear error string.
        """
        ok, out = self._run(["agent", "list", "--json"])
        return out

    def request_approval(
        self,
        question: str,
        options: Optional[str] = None,
        recommend: Optional[str] = None,
        tier: int = 2,
    ) -> str:
        """Ask a human to approve an action, over 5dive's Telegram-gated human-in-the-loop.

        Files an approval request that pushes an interactive prompt to the account owner on
        Telegram. Use this before doing something that needs explicit human sign-off, such as
        spending money, publishing, or making a destructive change. The call returns right
        away with the request's id and its current (blocked, awaiting-human) state; it does
        not wait for the human to answer.

        Args:
            question (str): The approval question to put to the human.
            options (Optional[str]): Pipe-separated choices, e.g. "Approve|Reject". Optional.
            recommend (Optional[str]): Your recommended choice; it leads the alert and is starred.
            tier (int): Risk tier 0-2. 2 (default) is a hard human gate; 1 auto-applies the
                recommendation after 48h if unanswered; 0 applies it immediately.

        Returns:
            str: The approval request state as a JSON string, or a clear error string.
        """
        add_ok, add_out = self._run(["task", "add", question, "--json"])
        if not add_ok:
            return f"Error: could not create the approval task: {add_out}"

        task_id = self._extract_task_id(add_out)
        if task_id is None:
            return f"Error: created a task but could not parse its id from: {add_out}"

        need_args = [
            "task",
            "need",
            task_id,
            "--type=approval",
            f"--ask={question}",
            f"--tier={tier}",
            "--json",
        ]
        if options:
            need_args.append(f"--options={options}")
        if recommend:
            need_args.append(f"--recommend={recommend}")

        need_ok, need_out = self._run(need_args)
        if not need_ok:
            return f"Error: task {task_id} was created but the approval gate could not be filed: {need_out}"
        return need_out
