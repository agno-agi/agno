"""
AgentBay Tools for Agno.

Unified toolkit providing AgentBay cloud computing capabilities.
"""

import asyncio
import json
import subprocess
import sys
from os import getenv
from textwrap import dedent
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.team import Team
from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_info, log_warning

try:
    from agentbay import (
        ActOptions,
        BrowserOption,
        BrowserViewport,
        ExtractOptions,
        MouseButton,
        ObserveOptions,
    )
except ImportError:
    raise ImportError("`agentbay` not installed. Please install using `pip install wuying-agentbay-sdk`")

try:
    from agentbay.api.models import GetAndLoadInternalContextRequest
except ImportError:
    GetAndLoadInternalContextRequest = None  # type: ignore[misc, assignment]

from .session_manager import AgentBaySessionManager

DEFAULT_INSTRUCTIONS = dedent(
    """\
    You have access to AgentBay cloud computing platform for remote operations.
    
    ## Code Execution:
    - `run_code`: Execute Python or JavaScript code. ONLY supported on code_latest (code space) image; on other images use run_shell_command.
    - `run_shell_command`: Execute shell/bash commands. Use for shell commands and for running scripts on non-code images (linux_latest, etc.).
    
    ## File Operations:
    - `create_file`: Create or update files
    - `read_file`: Read file contents
    - `list_directory`: List directory contents
    - `delete_file`: Delete files or directories
    
    ## Browser Automation (if enabled):
    - `navigate_to_url`: Navigate to webpage (use https://www.baidu.com, NOT google.com)
    - `take_screenshot`: Capture webpage screenshots (must navigate first)
    - `observe_elements`: Find and identify page elements using natural language (must navigate first)
    - `act`: Perform any action on page elements (click, type, select, hover, scroll, etc.) using natural language (must navigate first)
    - `extract_page_content`: Extract text content using AI (must navigate first)
    - `browser_agent_execute_task`: Execute complex browser automation tasks using natural language (AI automatically plans and executes multi-step workflows)
    
    ## Desktop UI Automation (if enabled):
    - `take_desktop_screenshot`: Capture desktop screenshots
    - `click_coordinates`: Click at screen coordinates
    - `type_text`: Type text input
    - `get_installed_apps`: List installed applications
    - `launch_application`: Start applications
    - `stop_application`: Stop applications
    - `computer_agent_execute_task`: Execute complex desktop automation tasks using natural language (AI automatically plans and executes multi-step workflows)
    
    ## Mobile Automation (if enabled):
    - `mobile_tap`: Tap on mobile screen
    - `mobile_swipe`: Swipe gesture
    - `mobile_screenshot`: Take mobile screenshot
    - `get_mobile_apps`: List mobile apps
    - `start_mobile_app`: Start mobile app
    - `stop_mobile_app`: Stop mobile app
    - `mobile_agent_execute_task`: Execute complex mobile automation tasks using natural language (AI automatically plans and executes multi-step workflows)
    
    ## System Operations (if enabled):
    - `get_system_info`: Get system information
    - `manage_processes`: List or kill processes
    
    ## Sandbox lifecycle (required for code + file workflows):
    - `create_sandbox`: Call first when running code or uploading files. Returns sandbox_id. You MUST pass this sandbox_id to run_code, run_shell_command, and upload_file_to_context_and_get_url.
    - `connect_sandbox`: Bind an existing sandbox_id to an environment for this agent.
    - `delete_sandbox`: Delete a sandbox and release resources.
    
    ## Context File URL:
    - `upload_file_to_context_and_get_url`: Upload a file from the session and get a shareable URL. Requires sandbox_id — use the SAME sandbox_id you passed to run_code that created the file (from create_sandbox).
    
    IMPORTANT GUIDELINES:
    - run_code is only available on the code_latest (code space) image. Other images (linux_latest, browser_latest, windows_latest, mobile_latest) cannot use run_code — use run_shell_command to execute commands or scripts on those images.
    - run_code, run_shell_command, and upload_file_to_context_and_get_url all require sandbox_id. Call create_sandbox(environment="code_latest") first, then pass the returned sandbox_id to run_code and to upload_file_to_context_and_get_url so they use the same session and the upload can find the file.
    - Always execute code rather than just providing snippets
    - For browser operations, navigate_to_url MUST be called before other browser tools
    - If a website fails to load, try alternative URLs immediately instead of retrying
    - For search tasks: navigate → observe_elements (optional, to find search box) → act (type text and/or click button)
    - Use observe_elements to find elements before interacting with them, or use act directly with natural language
    - Agent tools (browser_agent_execute_task, computer_agent_execute_task, mobile_agent_execute_task) use AI to automatically plan and execute complex multi-step tasks
    - Use agent tools for complex workflows, use manual tools for simple, precise operations
    """
)


class AgentBayTools(Toolkit):
    """AgentBay cloud computing toolkit; unified entry point for all AgentBay tools."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        agbsession_id: Optional[str] = None,
        default_environment: str = "linux_latest",
        enable_code_execution: bool = False,
        enable_file_operations: bool = True,
        enable_browser_automation: bool = False,
        enable_ui_automation: bool = False,
        enable_mobile_automation: bool = False,
        enable_system_operations: bool = True,
        # Configuration parameters
        timeout: int = 300,
        persistent: bool = True,
        auto_create_agbsession: bool = True,
        agbsession_labels: Optional[Dict[str, Any]] = None,
        instructions: Optional[str] = None,
        **kwargs,
    ):
        """Initialize AgentBay tools with configurable features.

        Args:
            api_key: AgentBay API key (defaults to AGENTBAY_API_KEY env var)
            agbsession_id: Explicit agbsession ID to use
            default_environment: Default environment for sessions
            enable_code_execution: Enable code execution tools
            enable_file_operations: Enable file operation tools
            enable_browser_automation: Enable browser automation tools (includes browser agent)
            enable_ui_automation: Enable UI automation tools (includes computer agent)
            enable_mobile_automation: Enable mobile automation tools (includes mobile agent)
            enable_system_operations: Enable system operation tools
            timeout: Default timeout for operations
            persistent: If True, agbsession persists across interactions
            auto_create_agbsession: Automatically create agbsession if needed
            agbsession_labels: Optional labels for agbsession
            instructions: Custom instructions for tools (defaults to DEFAULT_INSTRUCTIONS if not provided)
        """
        self.api_key = api_key or getenv("AGENTBAY_API_KEY")
        if not self.api_key:
            raise ValueError("AGENTBAY_API_KEY not set. Please set the AGENTBAY_API_KEY environment variable.")

        self.agbsession_id = agbsession_id
        self.default_environment = default_environment
        self.timeout = timeout
        self.persistent = persistent
        self.auto_create_agbsession = auto_create_agbsession
        self.agbsession_labels = agbsession_labels or {}

        # Initialize SessionManager (singleton)
        self.session_manager = AgentBaySessionManager(api_key=self.api_key)

        # Keep agent_bay for backward compatibility and direct access
        self.agent_bay = None  # Will be initialized lazily via session_manager

        tools: List[Any] = []

        if enable_code_execution:
            tools.extend(
                [
                    self.run_code,
                ]
            )
        # run_shell_command is always enabled (all agents can run shell commands on their sandbox)
        tools.extend(
            [
                self.run_shell_command,
            ]
        )
        if enable_file_operations:
            tools.extend(
                [
                    self.create_file,
                    self.read_file,
                    self.list_directory,
                    self.delete_file,
                ]
            )

        if enable_browser_automation:
            tools.extend(
                [
                    self.navigate_to_url,
                    self.take_screenshot,
                    self.observe_elements,
                    self.act,
                    self.extract_page_content,
                    self.browser_agent_execute_task,
                ]
            )

        if enable_ui_automation:
            tools.extend(
                [
                    self.take_desktop_screenshot,
                    self.click_coordinates,
                    self.type_text,
                    self.get_installed_apps,
                    self.launch_application,
                    self.stop_application,
                    self.computer_agent_execute_task,
                ]
            )

        if enable_mobile_automation:
            tools.extend(
                [
                    self.mobile_tap,
                    self.mobile_swipe,
                    self.mobile_input_text,
                    self.mobile_send_key,
                    self.mobile_screenshot,
                    self.get_mobile_apps,
                    self.start_mobile_app,
                    self.stop_mobile_app,
                    self.get_ui_elements,
                    self.mobile_agent_execute_task,
                ]
            )

        if enable_system_operations:
            tools.extend(
                [
                    self.get_system_info,
                    self.manage_processes,
                ]
            )

        # Sandbox lifecycle (stack-style: create/connect/delete sandbox, sandbox_id persisted in session_state)
        tools.extend(
            [
                self.create_sandbox,
                self.connect_sandbox,
                self.delete_sandbox,
            ]
        )
        # Always include session management tools
        tools.extend(
            [
                self.list_sessions,
                self.cleanup_sessions,
                self.get_session_link,
            ]
        )

        # Always include context file URL tool (upload to context and get shareable URL)
        tools.extend(
            [
                self.upload_file_to_context_and_get_url,
            ]
        )

        super().__init__(
            name="agentbay_tools", tools=tools, instructions=instructions or DEFAULT_INSTRUCTIONS, **kwargs
        )

    async def __aenter__(self):
        """Async context manager entry."""
        await self.session_manager.start()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        """Async context manager exit - automatically cleanup."""
        await self.session_manager.cleanup()

    def __enter__(self):
        """Sync context manager entry (for compatibility)."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                log_warning("Event loop is already running. Use async context manager instead.")
            else:
                loop.run_until_complete(self.session_manager.start())
        except RuntimeError:
            asyncio.run(self.session_manager.start())
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Sync context manager exit - automatically cleanup."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.session_manager.cleanup())
            else:
                loop.run_until_complete(self.session_manager.cleanup())
        except RuntimeError:
            asyncio.run(self.session_manager.cleanup())

    async def _ensure_agent_bay(self):
        """Ensure agent_bay is initialized."""
        if self.agent_bay is None:
            await self.session_manager.start()
            self.agent_bay = self.session_manager.agent_bay

    # Session state key for stack-style sandbox_id persistence (env -> session_id)
    AGBSESSION_IDS_KEY = "agbsession_ids"

    async def _get_or_create_agbsession(
        self,
        agent: Union[Agent, Team],
        environment: Optional[str] = None,
        sandbox_id: Optional[str] = None,
        context_id: Optional[str] = None,
        mount_path: Optional[str] = None,
    ):
        """
        Get existing agbsession or create new one (stack-style: prefer sandbox_id / session_state).

        Resolution order:
        1. If toolkit was constructed with agbsession_id, use that.
        2. If sandbox_id is provided, get session by id and return.
        3. If agent.session_state["agbsession_ids"][env] exists and is valid, use that session.
        4. Else get_or_create_session(env) and store session_id in session_state["agbsession_ids"][env].

        Args:
            agent: Agno agent instance
            environment: Target environment (defaults to self.default_environment)
            sandbox_id: Optional explicit session id (when provided, use this session)
            context_id: Optional context ID to mount
            mount_path: Optional mount path for context

        Returns:
            AgentBay agbsession object
        """
        try:
            env = environment or self.default_environment

            if context_id and not mount_path:
                raise ValueError("mount_path is required when context_id is provided")

            await self.session_manager.start()
            if self.agent_bay is None:
                self.agent_bay = self.session_manager.agent_bay

            # 1) Explicit toolkit-level agbsession_id
            if self.agbsession_id:
                agbsession = await self.session_manager.get_session(self.agbsession_id)
                if agbsession:
                    log_debug(f"Using explicit agbsession: {self.agbsession_id}")
                    if context_id:
                        log_debug(f"Recreating session with context {context_id}")
                        await self.session_manager.delete_session(self.agbsession_id)
                        agbsession = None
                else:
                    agbsession = None
                if agbsession is not None:
                    return agbsession

            # 2) Explicit sandbox_id (stack-style: caller passes session id)
            if sandbox_id:
                agbsession = await self.session_manager.get_session(sandbox_id)
                if agbsession:
                    return agbsession
                log_warning(f"Sandbox {sandbox_id} not found or invalid, falling back to environment lookup")

            # 3) Prefer session from agent.session_state["agbsession_ids"][env] (stack-style persistence)
            if hasattr(agent, "session_state") and agent.session_state is not None:
                ids = agent.session_state.get(self.AGBSESSION_IDS_KEY)
                if isinstance(ids, dict) and env in ids:
                    stored_id = ids.get(env)
                    if stored_id:
                        agbsession = await self.session_manager.get_session(stored_id)
                        if agbsession:
                            log_debug(f"Using stored sandbox_id for {env}: {stored_id}")
                            return agbsession
                        try:
                            del ids[env]
                        except (KeyError, TypeError):
                            pass

            # 4) Get or create by environment and persist for next time
            agbsession = await self.session_manager.get_or_create_session(
                environment=env,
                context_id=context_id,
                mount_path=mount_path,
                labels=self.agbsession_labels,
            )
            if hasattr(agent, "session_state"):
                if agent.session_state is None:
                    agent.session_state = {}
                agent.session_state.setdefault(self.AGBSESSION_IDS_KEY, {})[env] = agbsession.session_id
                session_key = self.session_manager._build_session_key(env, context_id, mount_path)
                agent.session_state[session_key] = agbsession.session_id

            return agbsession

        except Exception as e:
            if self.auto_create_agbsession:
                log_warning(f"Error in agbsession management: {e}. Creating new agbsession.")
                env = environment or self.default_environment
                return await self._create_new_agbsession(agent, env, context_id, mount_path)
            else:
                raise e

    async def _create_new_agbsession(
        self,
        agent: Optional[Union[Agent, Team]] = None,
        environment: Optional[str] = None,
        context_id: Optional[str] = None,
        mount_path: Optional[str] = None,
    ):
        """
        Create a new agbsession with the configured parameters using SessionManager.

        If context_id is provided, creates a session with context_syncs configured.
        Otherwise, creates a regular session without context.

        Args:
            agent: Optional agent instance
            environment: Environment to create
            context_id: Optional context ID to mount
            mount_path: Optional mount path for context (required if context_id is provided)

        Returns:
            AgentBay agbsession object
        """
        try:
            env = environment or self.default_environment

            # Ensure session_manager is started
            await self.session_manager.start()

            # Get agent_bay for backward compatibility
            if self.agent_bay is None:
                self.agent_bay = self.session_manager.agent_bay

            # Prepare labels
            labels = self.agbsession_labels.copy()
            labels.setdefault("created_by", "agno_agentbay_toolkit")
            labels.setdefault("environment", env)

            if self.persistent:
                labels.setdefault("persistent", "true")

            # Create session using SessionManager
            agbsession = await self.session_manager.create_session(
                environment=env, context_id=context_id, mount_path=mount_path, labels=labels
            )

            # Store in agent state for backward compatibility
            if agent and hasattr(agent, "session_state"):
                if agent.session_state is None:
                    agent.session_state = {}
                session_key = self.session_manager._build_session_key(env, context_id, mount_path)
                agent.session_state[session_key] = agbsession.session_id

            # Auto-open resource URL for browser and mobile sessions
            if env in ("browser_latest", "mobile_latest"):
                try:
                    if hasattr(agbsession, "resource_url") and agbsession.resource_url:
                        log_info(f"{env} agbsession URL: {agbsession.resource_url}")
                        self._open_resource_url(agbsession.resource_url)
                except Exception as e:
                    log_debug(f"Could not open resource URL: {e}")

            return agbsession

        except Exception as e:
            log_error(f"Error creating AgentBay agbsession: {e}")
            raise e

    def _open_resource_url(self, url: str) -> None:
        """
        Open resource URL in default browser.

        Args:
            url: The resource URL to open
        """
        try:
            if sys.platform == "darwin":  # macOS
                subprocess.run(["open", url], check=False)
            elif sys.platform == "win32":  # Windows
                subprocess.run(["start", url], shell=True, check=False)
            else:  # Linux and others
                subprocess.run(["xdg-open", url], check=False)
            log_info(f"Opened resource URL in browser: {url}")
        except Exception as e:
            log_warning(f"Failed to open resource URL: {e}")

    def _handle_error(self, error: Exception, operation: str) -> str:
        """Standard error handling."""
        error_msg = f"Error {operation}: {str(error)}"
        log_error(error_msg)
        return json.dumps({"status": "error", "message": error_msg})

    def _require_sandbox_id(self, sandbox_id: Optional[str], create_hint: str) -> Tuple[Optional[str], Optional[str]]:
        """Validate sandbox_id is non-empty. Returns (strip(sandbox_id), None) or (None, error_json)."""
        if sandbox_id and str(sandbox_id).strip():
            return sandbox_id.strip(), None
        return None, json.dumps({"status": "error", "message": f"sandbox_id is required. {create_hint}"})

    # === Code Execution Tools ===
    async def run_code(
        self,
        agent: Union[Agent, Team],
        code: str,
        sandbox_id: str,
        language: str = "python",
        environment: Optional[str] = None,
    ) -> str:
        """
        Execute Python or JavaScript code in the AgentBay cloud code environment.

        Only the code_latest image supports run_code. On other images use run_shell_command.

        Use this tool when you need to:
        - Run Python or JavaScript for calculations, data processing, or scripts
        - Execute code that produces output or files (use same sandbox_id for upload_file_to_context_and_get_url)

        Prerequisite: sandbox_id from create_sandbox(environment="code_latest"). Pass the same
        sandbox_id to run_code and upload_file_to_context_and_get_url so uploads see the same files.

        Args:
            code: Python or JavaScript code to execute.
            sandbox_id: Required. Session ID from create_sandbox(environment="code_latest").
            language: One of: python, py, javascript, js, node. Default: python.
            environment: Must be code_latest; other images use run_shell_command.

        Returns:
            Execution output (stdout, return values, errors).
        """
        try:
            sid, err = self._require_sandbox_id(
                sandbox_id,
                "Call create_sandbox(environment='code_latest') first and pass the returned sandbox_id to run_code.",
            )
            if err is not None:
                return err
            env = (environment or "code_latest").strip().lower()
            if env != "code_latest":
                return json.dumps(
                    {
                        "status": "error",
                        "message": f"run_code is only supported on the code_latest (code space) image, not '{env}'. "
                        "To execute commands or scripts on other images, use run_shell_command instead.",
                    }
                )
            # Normalize language
            language_map = {
                "python": "python",
                "py": "python",
                "javascript": "javascript",
                "js": "javascript",
                "node": "javascript",
            }

            normalized_language = language_map.get(language.lower())
            if not normalized_language:
                return json.dumps(
                    {"status": "error", "message": f"Unsupported language: {language}. Supported: python, javascript"}
                )

            agbsession = await self._get_or_create_agbsession(agent, "code_latest", sandbox_id=sid)
            result = await agbsession.code.run_code(code, normalized_language)

            if result.success:
                return f"✅ {normalized_language.capitalize()} execution successful:\n{result.result}"
            else:
                return self._handle_error(
                    Exception(getattr(result, "error_message", "Execution failed")),
                    f"executing {normalized_language} code",
                )
        except Exception as e:
            return self._handle_error(e, f"executing {language} code")

    async def run_shell_command(
        self,
        agent: Union[Agent, Team],
        command: str,
        sandbox_id: str,
        environment: Optional[str] = None,
    ) -> str:
        """
        Execute shell/bash commands in the AgentBay cloud environment.

        Use this tool when you need to:
        - Run system commands (ls, cd, mkdir, cat, grep, etc.)
        - Check system info (uname, df, free, ps) or manage files (cp, mv, rm)
        - Install packages (apt-get, pip, npm) or run scripts on non-code images

        Prerequisite: sandbox_id from create_sandbox (e.g. environment="linux_latest").

        Args:
            command: Shell command to execute (e.g. "ls -la", "echo hello").
            sandbox_id: Required. Session ID from create_sandbox(environment="linux_latest").
            environment: Optional environment override; default: linux_latest.

        Returns:
            Command stdout or error message.
        """
        try:
            sid, err = self._require_sandbox_id(
                sandbox_id,
                "Call create_sandbox(environment='linux_latest') first and pass the returned sandbox_id to run_shell_command.",
            )
            if err is not None:
                return err
            agbsession = await self._get_or_create_agbsession(agent, environment or "linux_latest", sandbox_id=sid)
            result = await agbsession.command.execute_command(command)

            if result.success:
                return f"✅ Command executed successfully:\n{result.output}"
            else:
                return self._handle_error(Exception(result.error_message), "executing shell command")
        except Exception as e:
            return self._handle_error(e, "executing command")

    # === File Operations Tools ===
    async def create_file(
        self,
        agent: Union[Agent, Team],
        file_path: str,
        content: str,
        environment: Optional[str] = None,
    ) -> str:
        """
        Create or overwrite a file in the AgentBay cloud environment.

        Use this tool when you need to:
        - Create or update files with given content (overwrites if exists)
        - Save code, configs, or text data to the session filesystem

        Args:
            file_path: File path (relative or absolute).
            content: Content to write (overwrites existing file).
            environment: Optional environment override.

        Returns:
            Success message with file path or error message.
        """
        try:
            agbsession = await self._get_or_create_agbsession(agent, environment)
            result = await agbsession.file_system.write_file(file_path, content, mode="overwrite")

            if result.success:
                return f"✅ File created successfully: {file_path}"
            else:
                return self._handle_error(Exception(result.error_message), "creating file")
        except Exception as e:
            return self._handle_error(e, "creating file")

    async def read_file(
        self,
        agent: Union[Agent, Team],
        file_path: str,
        environment: Optional[str] = None,
    ) -> str:
        """
        Read file contents from the AgentBay cloud environment.

        Use this tool when you need to:
        - Read text files, scripts, logs, or configs from the session
        - Verify file contents or use them in subsequent steps

        Args:
            file_path: Path to the file (relative or absolute).
            environment: Optional environment override.

        Returns:
            File content as string, or error if file does not exist.
        """
        try:
            agbsession = await self._get_or_create_agbsession(agent, environment)
            result = await agbsession.file_system.read_file(file_path)

            if result.success:
                return result.content
            else:
                return self._handle_error(Exception(result.error_message), "reading file")
        except Exception as e:
            return self._handle_error(e, "reading file")

    async def list_directory(
        self,
        agent: Union[Agent, Team],
        directory_path: str = ".",
        environment: Optional[str] = None,
    ) -> str:
        """
        List directory contents in the AgentBay cloud environment.

        Use this tool when you need to:
        - List files and subdirectories in a path
        - Verify files were created or explore the session filesystem

        Args:
            directory_path: Directory path; default "." (current directory).
            environment: Optional environment override.

        Returns:
            Formatted list of entries with names and types.
        """
        try:
            agbsession = await self._get_or_create_agbsession(agent, environment)
            result = await agbsession.file_system.list_directory(directory_path)

            if result.success:
                files_info = []
                for entry in result.entries:
                    # Handle both dict and DirectoryEntry object
                    if isinstance(entry, dict):
                        entry_name = entry.get("name", "Unknown")
                        entry_type = entry.get("type", "Unknown")
                    else:
                        entry_name = getattr(entry, "name", "Unknown")
                        entry_type = getattr(entry, "type", "Unknown")
                    files_info.append(f"- {entry_name} ({entry_type})")
                return f"Contents of {directory_path}:\n" + "\n".join(files_info)
            else:
                return self._handle_error(Exception(result.error_message), "listing directory")
        except Exception as e:
            return self._handle_error(e, "listing directory")

    async def delete_file(
        self,
        agent: Union[Agent, Team],
        file_path: str,
        environment: Optional[str] = None,
    ) -> str:
        """
        Delete a file or directory in the AgentBay cloud environment.

        Use this tool when you need to:
        - Remove files or directories
        - Clean up temporary or unwanted paths

        Args:
            file_path: Path to file or directory to delete.
            environment: Optional environment override.

        Returns:
            Success message or error if path does not exist.
        """
        try:
            agbsession = await self._get_or_create_agbsession(agent, environment)
            result = await agbsession.file_system.delete_file(file_path)

            if result.success:
                return f"✅ File deleted successfully: {file_path}"
            else:
                return self._handle_error(Exception(result.error_message), "deleting file")
        except Exception as e:
            return self._handle_error(e, "deleting file")

    # === Browser Automation Tools ===
    async def navigate_to_url(
        self,
        agent: Union[Agent, Team],
        url: str,
        wait_time: int = 3,
        use_stealth: bool = False,
        viewport_width: int = 1920,
        viewport_height: int = 1080,
    ) -> str:
        """
        Navigate to a URL in AgentBay browser environment.

        USE THIS TOOL when you need to:
        - Visit a specific website
        - Load a web page before taking screenshots or extracting content
        - Access web applications

        IMPORTANT NOTES:
        - Always provide full URL with protocol (https:// or http://)
        - Google.com may NOT be accessible in cloud environment
        - For web searches, use https://www.baidu.com instead
        - If navigation fails, try alternative URLs immediately instead of retrying

        Examples:
        - Navigate to Baidu: navigate_to_url(url="https://www.baidu.com")
        - Navigate to Aliyun: navigate_to_url(url="https://www.aliyun.com")
        - Navigate to GitHub: navigate_to_url(url="https://github.com")

        Args:
            url: Full URL including protocol (e.g., https://www.baidu.com)
            wait_time: Seconds to wait after navigation for page load (default: 3)
            use_stealth: Enable stealth mode to avoid bot detection
            viewport_width: Browser window width in pixels
            viewport_height: Browser window height in pixels

        Returns:
            Success message with URL or error if navigation failed
        """
        try:
            agbsession = await self._get_or_create_agbsession(agent, "browser_latest")

            # Initialize browser if not already initialized
            if not agbsession.browser.is_initialized():
                if BrowserOption is None or BrowserViewport is None:
                    return self._handle_error(
                        Exception("BrowserOption not available. Please install AgentBay SDK."), "initializing browser"
                    )
                browser_option = BrowserOption(
                    use_stealth=use_stealth, viewport=BrowserViewport(width=viewport_width, height=viewport_height)
                )
                init_success = await agbsession.browser.initialize(browser_option)
                if not init_success:
                    return self._handle_error(Exception("Failed to initialize browser"), "initializing browser")

                # Print and open agbsession resource URL for public access
                try:
                    if hasattr(agbsession, "resource_url") and agbsession.resource_url:
                        log_info(f"Browser agbsession URL: {agbsession.resource_url}")
                        self._open_resource_url(agbsession.resource_url)
                except Exception:
                    pass

            # Navigate to URL using async method
            result = await agbsession.browser.agent.navigate(url)

            if isinstance(result, str) and "Navigation failed" in result:
                return self._handle_error(Exception(result), "navigating to URL")

            return f"✅ Successfully navigated to: {url}"
        except Exception as e:
            return self._handle_error(e, "navigating to URL")

    async def take_screenshot(self, agent: Union[Agent, Team], full_page: bool = True, quality: int = 80) -> str:
        """
        Take screenshot of current web page in AgentBay browser environment.

        USE THIS TOOL when you need to:
        - Capture what's currently displayed on a web page
        - Save visual state of a web page
        - Verify page rendering

        PREREQUISITE: Must navigate_to_url first before taking screenshot.

        Examples:
        - Full page screenshot: take_screenshot(full_page=True)
        - Viewport only: take_screenshot(full_page=False)
        - Low quality for smaller size: take_screenshot(quality=50)

        Args:
            full_page: Capture entire page including scrolled content (default: True)
            quality: Image quality 1-100, higher = better quality (default: 80)

        Returns:
            Success message with screenshot data (base64 encoded)
        """
        try:
            agbsession = await self._get_or_create_agbsession(agent, "browser_latest")

            # Initialize browser if not already initialized
            if not agbsession.browser.is_initialized():
                if BrowserOption is None:
                    return self._handle_error(
                        Exception("BrowserOption not available. Please install AgentBay SDK."), "initializing browser"
                    )
                init_success = await agbsession.browser.initialize(BrowserOption())
                if not init_success:
                    return self._handle_error(Exception("Failed to initialize browser"), "initializing browser")

            # Take screenshot using async method
            screenshot_data = await agbsession.browser.agent.screenshot(full_page=full_page, quality=quality)

            if isinstance(screenshot_data, str) and "Screenshot failed" in screenshot_data:
                return self._handle_error(Exception(screenshot_data), "taking screenshot")

            return f"✅ Screenshot captured successfully (base64 data: {len(screenshot_data)} characters)"
        except Exception as e:
            return self._handle_error(e, "taking screenshot")

    async def observe_elements(
        self, agent: Union[Agent, Team], instruction: str, use_vision: bool = True, timeout_ms: int = 5000
    ) -> str:
        """
        Find and identify page elements using natural language instructions.

        USE THIS TOOL when you need to:
        - Find search boxes, input fields, buttons, or links on a page
        - Locate specific UI elements before interacting with them
        - Understand what interactive elements are available on a page

        PREREQUISITE: Must navigate_to_url first.

        HOW IT WORKS:
        - Uses AI to interpret your natural language instruction
        - Searches the page for matching elements
        - Returns element information including selectors and suggested actions

        Examples:
        - Find search box: observe_elements(instruction="Find the search input field")
        - Find login button: observe_elements(instruction="Find the login button")
        - Find all links: observe_elements(instruction="Find all clickable links")
        - Find submit button: observe_elements(instruction="Find the submit or search button")

        Args:
            instruction: Natural language description of elements to find
            use_vision: Use visual understanding for better accuracy (default: True)
            timeout_ms: Maximum time to wait for DOM to settle in milliseconds (default: 5000)

        Returns:
            JSON list of found elements with selectors, descriptions, and suggested actions
        """
        try:
            agbsession = await self._get_or_create_agbsession(agent, "browser_latest")

            # Initialize browser if not already initialized
            if not agbsession.browser.is_initialized():
                if BrowserOption is None:
                    return self._handle_error(
                        Exception("BrowserOption not available. Please install AgentBay SDK."), "initializing browser"
                    )
                init_success = agbsession.browser.initialize(BrowserOption())
                if not init_success:
                    return self._handle_error(Exception("Failed to initialize browser"), "initializing browser")

            # Use AgentBay's observe method
            if ObserveOptions is None:
                return self._handle_error(
                    Exception("ObserveOptions not available. Please install AgentBay SDK."), "observing elements"
                )

            observe_options = ObserveOptions(
                instruction=instruction,
                use_vision=use_vision,
                timeout=timeout_ms // 1000 if timeout_ms else None,  # Convert milliseconds to seconds
            )

            success, results = agbsession.browser.agent.observe(observe_options)

            if success and results:
                elements_info = []
                for result in results:
                    elements_info.append(
                        {
                            "selector": result.selector,
                            "description": result.description,
                            "method": result.method,
                            "arguments": result.arguments,
                        }
                    )

                return f"✅ Found {len(elements_info)} element(s):\n{json.dumps(elements_info, indent=2, ensure_ascii=False)}"
            else:
                return f"⚠️ No elements found matching: {instruction}\nTry being more specific or check if the page has loaded completely."
        except Exception as e:
            return self._handle_error(e, "observing elements")

    async def act(
        self, agent: Union[Agent, Team], action: str, timeout_ms: int = 30000, use_vision: bool = True
    ) -> str:
        """
        Perform an action on a web page element using natural language.

        USE THIS TOOL when you need to:
        - Click buttons, links, or interactive elements
        - Type text into input fields, search boxes, or forms
        - Select options from dropdowns
        - Hover over elements
        - Scroll the page
        - Perform any interactive action on the page

        PREREQUISITE: Must navigate_to_url first.

        HOW IT WORKS:
        - Uses AI vision to understand the page and locate elements
        - Supports natural language descriptions of any action
        - Automatically determines the action type (click, type, select, etc.)
        - Based on AgentBay's unified act method from browser_agent.py

        Examples:
        - Click button: act(action="Click the search button")
        - Type text: act(action="Type 'agentbay sdk' into the search box")
        - Select option: act(action="Select 'Option 1' from the dropdown")
        - Fill form: act(action="Type 'username' into the username field")
        - Submit form: act(action="Click the submit button")
        - Search: act(action="Type 'python tutorial' into the search box and click the search button")

        Args:
            action: Natural language description of the action to perform
            timeout_ms: Maximum time to wait for element in milliseconds (default: 30000)
            use_vision: Use visual understanding for better accuracy (default: True)

        Returns:
            Success message with action result or error if action failed
        """
        try:
            agbsession = await self._get_or_create_agbsession(agent, "browser_latest")

            # Initialize browser if not already initialized
            if not agbsession.browser.is_initialized():
                if BrowserOption is None:
                    return self._handle_error(
                        Exception("BrowserOption not available. Please install AgentBay SDK."), "initializing browser"
                    )
                init_success = await agbsession.browser.initialize(BrowserOption())
                if not init_success:
                    return self._handle_error(Exception("Failed to initialize browser"), "initializing browser")

            # Use AgentBay's unified act method (same as browser_agent.py)
            if ActOptions is None:
                return self._handle_error(
                    Exception("ActOptions not available. Please install AgentBay SDK."), "performing action"
                )

            act_options = ActOptions(action=action, timeout=timeout_ms, use_vision=use_vision)

            result = await agbsession.browser.agent.act(act_options)

            if result.success:
                return f"✅ Successfully performed action: {action}\nResult: {result.message}"
            else:
                return self._handle_error(Exception(result.message), "performing action")
        except Exception as e:
            return self._handle_error(e, "performing action")

    async def extract_page_content(self, agent: Union[Agent, Team], instruction: str, use_vision: bool = True) -> str:
        """
        Extract specific content from current web page using AI-powered extraction.

        USE THIS TOOL when you need to:
        - Get text content from a web page (headlines, articles, product info, etc.)
        - Extract structured data without parsing HTML
        - Read page content in natural language

        PREREQUISITE: Must navigate_to_url first.

        HOW IT WORKS:
        - Uses AI to understand page structure and content
        - Extracts information based on your natural language instruction
        - Returns clean text without HTML tags

        Examples:
        - Get headlines: extract_page_content(instruction="Extract all headlines and article titles")
        - Get product info: extract_page_content(instruction="Extract product names and prices")
        - Get main content: extract_page_content(instruction="Extract the main article text")

        Args:
            instruction: Natural language instruction describing what to extract
            use_vision: Use visual understanding (default: True, recommended)

        Returns:
            Extracted content as formatted text or error message
        """
        try:
            if BaseModel is None or Field is None or ExtractOptions is None:
                return self._handle_error(
                    Exception("Required modules not available. Please install AgentBay SDK and pydantic."),
                    "extracting page content",
                )

            # Define a simple schema for text extraction
            class PageContent(BaseModel):
                """Schema for extracted page content."""

                content: str = Field(..., description="The extracted page content as text")

            agbsession = await self._get_or_create_agbsession(agent, "browser_latest")

            # Initialize browser if not already initialized
            if not agbsession.browser.is_initialized():
                if BrowserOption is None:
                    return self._handle_error(
                        Exception("BrowserOption not available. Please install AgentBay SDK."), "initializing browser"
                    )
                init_success = await agbsession.browser.initialize(BrowserOption())
                if not init_success:
                    return self._handle_error(Exception("Failed to initialize browser"), "initializing browser")

            # Use AgentBay's extract method for content extraction (async)
            extract_options = ExtractOptions(
                instruction=instruction,
                schema=PageContent,
                use_text_extract=True,
                use_vision=use_vision,
                timeout=300,  # Timeout in seconds (default: 300)
            )

            success, extracted_data = await agbsession.browser.agent.extract(extract_options)

            if success and extracted_data:
                return f"✅ Successfully extracted content:\n{extracted_data.content}"
            elif success and not extracted_data:
                error_msg = (
                    "Extraction succeeded but returned no data. Possible reasons:\n"
                    "- Page content doesn't match the instruction\n"
                    "- Page hasn't fully loaded yet (try navigating again or wait a moment)\n"
                    "- Instruction is too vague or unclear\n"
                    "- Page requires authentication or has blocking elements (popups, cookies, etc.)"
                )
                return self._handle_error(Exception(error_msg), "extracting page content")
            else:
                error_msg = (
                    "Extraction failed. Possible reasons:\n"
                    "- Page content doesn't match the instruction\n"
                    "- Page hasn't fully loaded yet (try navigating again or wait a moment)\n"
                    "- Instruction is too vague or unclear\n"
                    "- Page requires authentication or has blocking elements\n"
                    "- Extraction timed out (took longer than 300 seconds)"
                )
                return self._handle_error(Exception(error_msg), "extracting page content")
        except Exception as e:
            return self._handle_error(e, "extracting page content")

    # === Desktop UI Automation Tools ===
    async def take_desktop_screenshot(self, agent: Union[Agent, Team]) -> str:
        """
        Capture screenshot of the desktop in AgentBay desktop environment.

        USE THIS TOOL when you need to:
        - See the current state of the desktop UI
        - Verify application windows and their content
        - Debug desktop automation workflows

        This captures the entire desktop screen, not just a single application.

        Returns:
            Success message with screenshot file path or error message
        """
        try:
            agbsession = await self._get_or_create_agbsession(agent, "windows_latest")

            # Take desktop screenshot using computer module
            result = await agbsession.computer.screenshot()

            if result.success:
                return f"✅ Desktop screenshot captured successfully\nPath: {result.data}"
            else:
                return self._handle_error(Exception(result.error_message), "taking desktop screenshot")
        except Exception as e:
            return self._handle_error(e, "taking desktop screenshot")

    async def click_coordinates(self, agent: Union[Agent, Team], x: int, y: int, button: str = "left") -> str:
        """
        Click at specific screen coordinates in AgentBay desktop environment.

        USE THIS TOOL when you need to:
        - Click on UI elements at known positions
        - Automate desktop application interactions
        - Click on specific screen locations

        TIP: Take a screenshot first to determine coordinates.

        Examples:
        - Left click: click_coordinates(x=100, y=200, button="left")
        - Right click for context menu: click_coordinates(x=500, y=300, button="right")
        - Double click: click_coordinates(x=150, y=250, button="double_left")

        Args:
            x: X coordinate on screen (pixels from left)
            y: Y coordinate on screen (pixels from top)
            button: Mouse button - "left", "right", "middle", or "double_left"

        Returns:
            Success message or error
        """
        try:
            agbsession = await self._get_or_create_agbsession(agent, "windows_latest")

            # Click at coordinates using computer module
            if MouseButton is None:
                return self._handle_error(
                    Exception("MouseButton not available. Please install AgentBay SDK."), "clicking coordinates"
                )
            mouse_button = MouseButton.LEFT
            if button.lower() == "right":
                mouse_button = MouseButton.RIGHT
            elif button.lower() == "middle":
                mouse_button = MouseButton.MIDDLE
            elif button.lower() == "double_left":
                mouse_button = MouseButton.DOUBLE_LEFT

            result = await agbsession.computer.click_mouse(x, y, mouse_button)

            if result.success:
                return f"✅ Successfully clicked at coordinates ({x}, {y}) with {button} button"
            else:
                return self._handle_error(Exception(result.error_message), "clicking coordinates")
        except Exception as e:
            return self._handle_error(e, "clicking coordinates")

    async def type_text(self, agent: Union[Agent, Team], text: str) -> str:
        """
        Type text input in the currently focused window in AgentBay desktop environment.

        USE THIS TOOL when you need to:
        - Enter text into applications
        - Fill in forms or input fields
        - Type commands or data

        PREREQUISITE: Ensure the target input field is focused (click on it first).

        Examples:
        - Type in text editor: type_text(text="Hello World")
        - Enter file name: type_text(text="document.txt")

        Args:
            text: Text to type

        Returns:
            Success message or error
        """
        try:
            agbsession = await self._get_or_create_agbsession(agent, "windows_latest")

            # Type text using computer module
            result = await agbsession.computer.input_text(text)

            if result.success:
                return f"✅ Successfully typed text: {text}"
            else:
                return self._handle_error(Exception(result.error_message), "typing text")
        except Exception as e:
            return self._handle_error(e, "typing text")

    async def get_installed_apps(self, agent: Union[Agent, Team], include_system: bool = False) -> str:
        """
        Get list of installed applications in AgentBay desktop environment.

        USE THIS TOOL when you need to:
        - Find what applications are available
        - Check if a specific app is installed
        - Get application paths for launching

        Examples:
        - List user apps: get_installed_apps(include_system=False)
        - List all apps including system: get_installed_apps(include_system=True)

        Args:
            include_system: Include system applications (default: False, only user apps)

        Returns:
            JSON list of applications with name, path, and executable
        """
        try:
            agbsession = await self._get_or_create_agbsession(agent, "windows_latest")

            # Get installed apps using computer module
            result = agbsession.computer.get_installed_apps(
                start_menu=True, desktop=False, ignore_system_apps=not include_system
            )

            if result.success and result.data:
                apps_info = []
                for app in result.data:
                    apps_info.append(
                        {
                            "name": getattr(app, "name", "Unknown"),
                            "path": getattr(app, "path", "Unknown"),
                            "executable": getattr(app, "executable", "Unknown"),
                        }
                    )

                return f"✅ Found {len(apps_info)} installed applications:\n{json.dumps(apps_info, indent=2, ensure_ascii=False)}"
            else:
                return self._handle_error(
                    Exception(result.error_message if hasattr(result, "error_message") else "Failed to get apps"),
                    "getting installed apps",
                )
        except Exception as e:
            return self._handle_error(e, "getting installed apps")

    async def launch_application(
        self, agent: Union[Agent, Team], app_command: str, work_dir: Optional[str] = None
    ) -> str:
        """
        Launch a desktop application.

        USE THIS TOOL when you need to:
        - Start a desktop application
        - Open programs before automating them

        TIP: Use get_installed_apps first to find application paths and commands.

        Examples:
        - Launch notepad: launch_application(app_command="notepad.exe")
        - Launch with path: launch_application(app_command="/usr/bin/firefox")

        Args:
            app_command: Application command or executable path
            work_dir: Optional working directory for the application

        Returns:
            Success message with process information or error
        """
        try:
            agbsession = await self._get_or_create_agbsession(agent, "windows_latest")

            # Start app using computer module
            result = await agbsession.computer.start_app(start_cmd=app_command, work_directory=work_dir or "")

            if result.success and result.data:
                processes_info = []
                for process in result.data:
                    processes_info.append(
                        {
                            "pid": getattr(process, "pid", "Unknown"),
                            "name": getattr(process, "name", "Unknown"),
                            "command": getattr(process, "command", "Unknown"),
                        }
                    )

                return f"✅ Successfully launched application: {app_command}\nProcesses: {json.dumps(processes_info, indent=2, ensure_ascii=False)}"
            else:
                return self._handle_error(
                    Exception(result.error_message if hasattr(result, "error_message") else "Failed to start app"),
                    "launching application",
                )
        except Exception as e:
            return self._handle_error(e, "launching application")

    async def stop_application(self, agent: Union[Agent, Team], identifier: str, method: str = "name") -> str:
        """
        Stop a running desktop application.

        USE THIS TOOL when you need to:
        - Close desktop applications
        - Force stop applications
        - Clean up after automation

        Examples:
        - Stop by name: stop_application(identifier="notepad", method="name")
        - Stop by PID: stop_application(identifier="1234", method="pid")
        - Stop by command: stop_application(identifier="notepad.exe", method="cmd")

        Args:
            identifier: Application identifier (name, PID, or command)
            method: Identification method - "name", "pid", or "cmd" (default: "name")

        Returns:
            Success message or error if application not found
        """
        try:
            agbsession = await self._get_or_create_agbsession(agent, "windows_latest")

            # Stop app using computer module
            if method == "pid":
                result = await agbsession.computer.stop_app_by_pid(int(identifier))
            elif method == "name":
                result = await agbsession.computer.stop_app_by_pname(identifier)
            elif method == "cmd":
                result = await agbsession.computer.stop_app_by_cmd(identifier)
            else:
                return self._handle_error(
                    ValueError(f"Invalid method: {method}. Use 'pid', 'name', or 'cmd'"), "stopping application"
                )

            if result.success:
                return f"✅ Successfully stopped application using {method}: {identifier}"
            else:
                return self._handle_error(Exception(result.error_message), "stopping application")
        except Exception as e:
            return self._handle_error(e, "stopping application")

    # === System Operations Tools ===
    async def get_system_info(self, agent: Union[Agent, Team], environment: Optional[str] = None) -> str:
        """
        Get system information from AgentBay cloud environment.

        USE THIS TOOL when you need to:
        - Check operating system details
        - Get CPU and memory information
        - Verify environment specifications

        Returns:
            Formatted system information including OS, CPU, and memory
        """
        try:
            agbsession = await self._get_or_create_agbsession(agent, environment)

            # Get system info based on environment type
            if environment == "windows_latest":
                commands = [
                    'systeminfo | findstr /B /C:"OS Name"',
                    "wmic cpu get name",
                    "wmic computersystem get TotalPhysicalMemory",
                ]
            else:
                commands = ["uname -a", "cat /proc/cpuinfo | grep 'model name' | head -1", "free -h"]

            results = []
            for cmd in commands:
                result = await agbsession.command.execute_command(cmd)
                if result.success:
                    results.append(result.output)

            return "System Information:\n" + "\n".join(results)
        except Exception as e:
            return self._handle_error(e, "getting system info")

    async def manage_processes(
        self,
        agent: Union[Agent, Team],
        action: str,
        process_name: Optional[str] = None,
        environment: Optional[str] = None,
    ) -> str:
        """
        Manage processes in AgentBay cloud environment.

        USE THIS TOOL when you need to:
        - List running processes
        - Kill/terminate specific processes
        - Monitor system processes

        Examples:
        - List all processes: manage_processes(action="list")
        - Kill process by name: manage_processes(action="kill", process_name="firefox")

        Args:
            action: Action to perform - "list" or "kill"
            process_name: Process name (required for "kill" action)
            environment: Optional environment override

        Returns:
            Process list or kill confirmation, or error message
        """
        try:
            agbsession = await self._get_or_create_agbsession(agent, environment)

            if action == "list":
                if environment == "windows_latest":
                    command = "tasklist"
                else:
                    command = "ps aux"
            elif action == "kill" and process_name:
                if environment == "windows_latest":
                    command = f"taskkill /F /IM {process_name}"
                else:
                    command = f"pkill {process_name}"
            else:
                return self._handle_error(
                    ValueError("Invalid process action or missing process_name"), "managing processes"
                )

            result = await agbsession.command.execute_command(command)
            if result.success:
                return f"✅ Process {action} successful:\n{result.output}"
            else:
                return self._handle_error(Exception(result.error_message), "managing processes")
        except Exception as e:
            return self._handle_error(e, "managing processes")

    # === Context File URL ===
    async def _get_file_transfer_context_id(
        self,
        agent: Union[Agent, Team],
        environment: str,
        sandbox_id: Optional[str] = None,
    ) -> Tuple[str, str]:
        """
        Get the session's file_transfer context_id and context_path via GetAndLoadInternalContext.
        No user-provided context_id needed; the backend assigns one per session.
        """
        if GetAndLoadInternalContextRequest is None:
            raise RuntimeError("GetAndLoadInternalContextRequest not available; ensure agentbay package is installed")
        await self._ensure_agent_bay()
        ab = self.session_manager.agent_bay
        if ab is None:
            raise RuntimeError("AgentBay client not initialized")
        agbsession = await self._get_or_create_agbsession(agent, environment, sandbox_id=sandbox_id)
        session_id = agbsession._get_session_id()
        api_key = getattr(ab, "api_key", "") or ""
        request = GetAndLoadInternalContextRequest(
            authorization=f"Bearer {api_key}",
            session_id=session_id,
            context_types=["file_transfer"],
        )
        client = ab.client
        response = await client.get_and_load_internal_context_async(request)
        response_map = response.to_map()
        body = response_map.get("body", {}) or {}
        if not body.get("Success", True) and body.get("Code"):
            raise RuntimeError(body.get("Message", "GetAndLoadInternalContext failed"))
        data = body.get("Data") or []
        if not isinstance(data, list) or len(data) == 0:
            raise RuntimeError("GetAndLoadInternalContext returned no data")
        for item in data:
            if not isinstance(item, dict):
                continue
            context_id = item.get("ContextId") or item.get("context_id") or ""
            context_path = item.get("ContextPath") or item.get("context_path") or ""
            if context_id and context_path:
                return context_id, context_path
        raise RuntimeError("GetAndLoadInternalContext did not return context_id and context_path")

    async def upload_file_to_context_and_get_url(
        self,
        agent: Union[Agent, Team],
        file_path_in_context: str,
        session_file_path: str,
        sandbox_id: str,
        environment: Optional[str] = None,
    ) -> str:
        """
        Upload a file from the session to context and return a shareable download URL.

        Use this tool when you need to return a URL for a file produced in the session (e.g. chart,
        image, report). The file must already exist at session_file_path (e.g. created by run_code).

        Prerequisite: sandbox_id must be the same as in run_code that created the file. Use the
        sandbox_id from create_sandbox(environment="code_latest") for both run_code and this tool.

        Args:
            file_path_in_context: Path in context (e.g. /images/figure.png).
            session_file_path: Path inside the session (e.g. /tmp/figure.png).
            sandbox_id: Required. Same session ID as used in run_code (from create_sandbox).
            environment: Optional; default from toolkit (e.g. code_latest).

        Returns:
            Shareable download URL (use in markdown as ![desc](url)) or error message.
        """
        try:
            sid, err = self._require_sandbox_id(
                sandbox_id,
                "Use the same sandbox_id from create_sandbox that you passed to run_code.",
            )
            if err is not None:
                return err
            await self._ensure_agent_bay()
            ab = self.session_manager.agent_bay
            if ab is None:
                raise RuntimeError("AgentBay client not initialized")
            env = environment or self.default_environment
            # Resolve session's file_transfer context (same session as run_code via sandbox_id)
            context_id, _ = await self._get_file_transfer_context_id(agent, env, sandbox_id=sid)
            # 1) Get presigned upload URL
            upload_result = await ab.context.get_file_upload_url(
                context_id=context_id,
                file_path=file_path_in_context,
            )
            if not upload_result.success or not upload_result.url:
                return self._handle_error(
                    Exception(upload_result.error_message or "Failed to get upload URL"),
                    "upload_file_to_context_and_get_url (get upload URL)",
                )
            # 2) Upload file from session to OSS via curl (same session as context)
            agbsession = await self._get_or_create_agbsession(agent, env, sandbox_id=sid)
            curl_cmd = f'curl -s -S -X PUT -T "{session_file_path}" "{upload_result.url}"'
            cmd_result = await agbsession.command.execute_command(curl_cmd)
            if not cmd_result.success:
                return self._handle_error(
                    Exception(cmd_result.error_message or cmd_result.output or "curl upload failed"),
                    "upload_file_to_context_and_get_url (upload from session)",
                )
            # 3) Get presigned download URL
            download_result = await ab.context.get_file_download_url(
                context_id=context_id,
                file_path=file_path_in_context,
            )
            if not download_result.success or not download_result.url:
                return self._handle_error(
                    Exception(download_result.error_message or "Failed to get download URL after upload"),
                    "upload_file_to_context_and_get_url (get download URL)",
                )
            expire = f" (expires in {download_result.expire_time}s)" if download_result.expire_time else ""
            return f"✅ Download URL{expire}:\n{download_result.url}\n\nUse in markdown: ![description]({download_result.url})"
        except Exception as e:
            return self._handle_error(e, "upload_file_to_context_and_get_url")

    async def get_context_file_upload_url(
        self,
        agent: Union[Agent, Team],
        context_id: str,
        file_path: str,
    ) -> str:
        """
        Get a presigned upload URL for a file in a context.

        Use this tool when you need a URL to PUT file content; then use
        get_context_file_download_url for a shareable link. Prefer
        upload_file_to_context_and_get_url for a one-step flow.

        Args:
            context_id: Context ID (from application or user).
            file_path: Path within the context (e.g. /images/figure.png).

        Returns:
            Presigned upload URL and expire_time, or error message.
        """
        try:
            await self._ensure_agent_bay()
            ab = self.session_manager.agent_bay
            if ab is None:
                raise RuntimeError("AgentBay client not initialized")
            result = await ab.context.get_file_upload_url(
                context_id=context_id,
                file_path=file_path,
            )
            if result.success and result.url:
                expire = f", expires in {result.expire_time}s" if result.expire_time else ""
                return f'✅ Upload URL:\n{result.url}\n\nUse in session: curl -s -X PUT -T <local_path> "{result.url}"{expire}'
            return self._handle_error(
                Exception(result.error_message or "Failed to get upload URL"),
                "getting context file upload URL",
            )
        except Exception as e:
            return self._handle_error(e, "getting context file upload URL")

    async def get_context_file_download_url(
        self,
        agent: Union[Agent, Team],
        context_id: str,
        file_path: str,
    ) -> str:
        """
        Get a presigned download URL for a file in a context.

        Use this tool to get a shareable link after uploading via
        get_context_file_upload_url (e.g. for images, reports).

        Args:
            context_id: Context ID (from application or user).
            file_path: Path within the context (e.g. /images/figure.png).

        Returns:
            Presigned download URL (use in markdown as ![desc](url)) or error.
        """
        try:
            await self._ensure_agent_bay()
            ab = self.session_manager.agent_bay
            if ab is None:
                raise RuntimeError("AgentBay client not initialized")
            result = await ab.context.get_file_download_url(
                context_id=context_id,
                file_path=file_path,
            )
            if result.success and result.url:
                expire = f" (expires in {result.expire_time}s)" if result.expire_time else ""
                return f"✅ Download URL{expire}:\n{result.url}\n\nUse in markdown: ![description]({result.url})"
            return self._handle_error(
                Exception(result.error_message or "Failed to get download URL"),
                "getting context file download URL",
            )
        except Exception as e:
            return self._handle_error(e, "getting context file download URL")

    # === Sandbox lifecycle (stack-style: explicit sandbox_id + session_state persistence) ===
    async def create_sandbox(
        self,
        agent: Union[Agent, Team],
        environment: Optional[str] = None,
    ) -> str:
        """
        Create a sandbox (AgentBay session) for the given environment.

        Call this first when you need to run code or upload files. run_code, run_shell_command,
        and upload_file_to_context_and_get_url all require sandbox_id; pass the same sandbox_id
        so they share one session (e.g. upload can read files created by run_code).

        Args:
            environment: Environment type (e.g. code_latest, linux_latest). Default: default_environment.

        Returns:
            sandbox_id to pass to run_code, run_shell_command, upload_file_to_context_and_get_url.
        """
        try:
            await self._ensure_agent_bay()
            env = environment or self.default_environment
            if hasattr(agent, "session_state") and agent.session_state is not None:
                ids = agent.session_state.get(self.AGBSESSION_IDS_KEY)
                if isinstance(ids, dict) and env in ids:
                    stored_id = ids[env]
                    agbsession = await self.session_manager.get_session(stored_id)
                    if agbsession:
                        return (
                            f"✅ Using existing sandbox for environment '{env}':\n"
                            f"sandbox_id: {stored_id}\n\n"
                            f"IMPORTANT: Pass this sandbox_id to ALL subsequent tool calls: run_code, run_shell_command, "
                            f"upload_file_to_context_and_get_url (use the same sandbox_id so run_code and upload use the same session)."
                        )
            agbsession = await self._get_or_create_agbsession(agent, environment=env)
            sid = agbsession.session_id
            return (
                f"✅ Sandbox created for environment '{env}':\n"
                f"sandbox_id: {sid}\n\n"
                f"IMPORTANT: Use this exact sandbox_id in ALL subsequent tool calls: run_code(sandbox_id='{sid}', ...), "
                f"run_shell_command(sandbox_id='{sid}', ...), upload_file_to_context_and_get_url(sandbox_id='{sid}', ...). "
                f"Using the same sandbox_id ensures files created by run_code can be uploaded with upload_file_to_context_and_get_url."
            )
        except Exception as e:
            return self._handle_error(e, "create_sandbox")

    async def connect_sandbox(
        self,
        agent: Union[Agent, Team],
        sandbox_id: str,
        environment: Optional[str] = None,
    ) -> str:
        """
        Connect to an existing sandbox and bind it to an environment for this agent.

        Use this tool when you have an existing sandbox_id (e.g. from list_sessions or a previous
        create_sandbox) and want later tool calls for that environment to use this session.

        Args:
            sandbox_id: Existing AgentBay session ID (e.g. s-xxxxx).
            environment: Environment to bind (e.g. code_latest). Default: default_environment.

        Returns:
            Success message or error if sandbox_id is invalid or expired.
        """
        try:
            await self._ensure_agent_bay()
            agbsession = await self.session_manager.get_session(sandbox_id)
            if not agbsession:
                return self._handle_error(
                    Exception(f"Sandbox {sandbox_id} not found or expired. Create a new one with create_sandbox."),
                    "connect_sandbox",
                )
            env = environment or self.default_environment
            if hasattr(agent, "session_state"):
                if agent.session_state is None:
                    agent.session_state = {}
                agent.session_state.setdefault(self.AGBSESSION_IDS_KEY, {})[env] = sandbox_id
            return (
                f"✅ Connected to sandbox {sandbox_id} and bound to environment '{env}'. "
                f"Pass this sandbox_id to run_code, run_shell_command, upload_file_to_context_and_get_url."
            )
        except Exception as e:
            return self._handle_error(e, "connect_sandbox")

    async def delete_sandbox(
        self,
        agent: Union[Agent, Team],
        sandbox_id: str,
    ) -> str:
        """
        Delete a sandbox (AgentBay session) and remove it from this agent's stored sandbox_ids.

        Use this tool when you want to release a cloud session (e.g. after finishing a task).

        Args:
            sandbox_id: Session ID to delete (e.g. s-xxxxx).

        Returns:
            Success or error message.
        """
        try:
            await self._ensure_agent_bay()
            ok = await self.session_manager.delete_session(sandbox_id)
            if hasattr(agent, "session_state") and agent.session_state is not None:
                ids = agent.session_state.get(self.AGBSESSION_IDS_KEY)
                if isinstance(ids, dict):
                    for k, v in list(ids.items()):
                        if v == sandbox_id:
                            del ids[k]
                            break
            if ok:
                return f"✅ Sandbox {sandbox_id} deleted."
            return self._handle_error(Exception("Delete failed or session already gone"), "delete_sandbox")
        except Exception as e:
            return self._handle_error(e, "delete_sandbox")

    # === Session Management Tools ===
    async def list_sessions(self, agent: Union[Agent, Team]) -> str:
        """
        List all active AgentBay sessions (agbsessions).

        Use this tool when you need to see active sessions or pick one for connect_sandbox.

        Returns:
            List of active session IDs or a message if none found.
        """
        try:
            await self.session_manager.start()
            session_ids = await self.session_manager.list_sessions()

            if session_ids:
                sessions_str = "\n".join([f"- {sid}" for sid in session_ids])
                return f"✅ Active AgentBay agbsessions:\n{sessions_str}"
            else:
                return "No active agbsessions found"
        except Exception as e:
            return self._handle_error(e, "listing agbsessions")

    async def cleanup_sessions(self, agent: Union[Agent, Team]) -> str:
        """
        Clean up all AgentBay sessions (agbsessions).

        Use this tool when you need to free cloud resources or reset after completing tasks.
        Deletes all sessions managed by SessionManager and clears agent session_state.

        Returns:
            Count of sessions cleaned up.
        """
        try:
            await self.session_manager.start()

            # Get cached sessions count before cleanup
            cached_sessions = self.session_manager.get_cached_sessions()
            total_sessions = sum(len(sessions) for sessions in cached_sessions.values())

            # Cleanup all sessions via SessionManager
            await self.session_manager.cleanup()

            # Also clean up agent.session_state for backward compatibility
            if hasattr(agent, "session_state") and agent.session_state:
                session_keys = [key for key in agent.session_state.keys() if key.startswith("agbsession_")]
                for session_key in session_keys:
                    del agent.session_state[session_key]

            return f"✅ Cleaned up {total_sessions} AgentBay agbsessions"
        except Exception as e:
            return self._handle_error(e, "cleaning up agbsessions")

    async def get_session_link(
        self,
        agent: Union[Agent, Team],
        protocol_type: Optional[str] = None,
        port: Optional[int] = None,
        environment: Optional[str] = None,
    ) -> str:
        """
        Get the current session access URL (port-forwarding URL).

        Use this tool when you need to:
        - Get port forwarding URL to access HTTP servers running in session
        - Access files or web applications via port forwarding
        - Share access to services running in your session

        Prerequisite (when using port forwarding):
        - If you specify a port, start an HTTP server in the session first via run_shell_command.
        - Wait 1-2 seconds for the server to start, then call this tool.

        Important:
        - When sharing the link with the user, return ONLY the base URL as returned by this tool.
        - Do not append subpaths (e.g. /battle_city/index.html); many gateways accept only the base URL.
        - The user should open the base URL in the browser.

        Examples:
        - Get port forwarding link: get_session_link(port=30100, protocol_type="https")
          (Make sure HTTP server is running on port 30100 first!)
        - When replying to the user: use the Access URL as-is; do not add /path/to/file.html to it.

        Args:
            protocol_type: Protocol (required if port specified). One of: wss, https, adb.
            port: Port in range [30100, 30199] (required for port forwarding).
            environment: Environment for the link (default: current session).

        Returns:
            Port-forwarding URL and usage instructions.
        """
        try:
            # 获取或创建 session（使用指定的环境或默认环境）
            env = environment or self.default_environment
            agbsession = await self._get_or_create_agbsession(agent, env)

            # 调用 get_link 方法（异步）
            link_result = await agbsession.get_link(protocol_type=protocol_type, port=port, options=None)

            if link_result.success:
                url = link_result.data if isinstance(link_result.data, str) else str(link_result.data)

                # 如果指定了端口，返回简洁的 URL
                if port is not None:
                    return f"""✅ Port forwarding link retrieved successfully!

                        Access URL: {url}

                        Session ID: {agbsession.session_id}
                        Port: {port}

                        Note: Make sure HTTP server is running on port {port} in your session before accessing.
                        When sharing with the user, return ONLY this Access URL—do not append paths ."""
                else:
                    return f"""✅ Session link retrieved successfully!

                        Access URL: {url}

                        Session ID: {agbsession.session_id}
                        Environment: {env}"""
            else:
                error_msg = link_result.error_message if hasattr(link_result, "error_message") else "Unknown error"
                return f"❌ Failed to get session link: {error_msg}"

        except Exception as e:
            return self._handle_error(e, "getting session link")

    # === Mobile Device Automation Tools ===
    async def mobile_tap(self, agent: Union[Agent, Team], x: int, y: int) -> str:
        """
        Tap on mobile screen at specified coordinates.

        USE THIS TOOL when you need to:
        - Touch specific locations on mobile screen
        - Tap buttons, icons, or UI elements
        - Interact with mobile applications

        TIP: Use mobile_screenshot first to determine coordinates.

        Args:
            x: X coordinate (pixels from left edge)
            y: Y coordinate (pixels from top edge)

        Returns:
            Success message or error
        """
        try:
            agbsession = await self._get_or_create_agbsession(agent, "mobile_latest")

            # Tap using mobile module
            result = await agbsession.mobile.tap(x, y)

            if result.success:
                return f"✅ Successfully tapped at coordinates ({x}, {y})"
            else:
                return self._handle_error(Exception(result.error_message), "tapping on screen")
        except Exception as e:
            return self._handle_error(e, "tapping on screen")

    async def mobile_swipe(
        self, agent: Union[Agent, Team], start_x: int, start_y: int, end_x: int, end_y: int, duration_ms: int = 300
    ) -> str:
        """
        Perform swipe gesture on mobile screen.

        USE THIS TOOL when you need to:
        - Scroll through content (swipe up/down)
        - Navigate between screens (swipe left/right)
        - Perform drag gestures

        Examples:
        - Scroll down: mobile_swipe(start_x=500, start_y=1000, end_x=500, end_y=300)
        - Scroll up: mobile_swipe(start_x=500, start_y=300, end_x=500, end_y=1000)
        - Swipe left: mobile_swipe(start_x=800, start_y=500, end_x=200, end_y=500)

        Args:
            start_x: Starting X coordinate
            start_y: Starting Y coordinate
            end_x: Ending X coordinate
            end_y: Ending Y coordinate
            duration_ms: Swipe duration in milliseconds (default: 300)

        Returns:
            Success message or error
        """
        try:
            agbsession = await self._get_or_create_agbsession(agent, "mobile_latest")

            # Swipe using mobile module
            result = await agbsession.mobile.swipe(start_x, start_y, end_x, end_y, duration_ms)

            if result.success:
                return f"✅ Successfully swiped from ({start_x}, {start_y}) to ({end_x}, {end_y})"
            else:
                return self._handle_error(Exception(result.error_message), "performing swipe")
        except Exception as e:
            return self._handle_error(e, "performing swipe")

    async def mobile_input_text(self, agent: Union[Agent, Team], text: str) -> str:
        """
        Input text in the currently focused input field on mobile device.

        USE THIS TOOL when you need to:
        - Type text into mobile app input fields
        - Fill in forms or search boxes
        - Enter data in mobile applications

        PREREQUISITE: Tap on the input field first to focus it.

        Args:
            text: Text to input

        Returns:
            Success message or error
        """
        try:
            agbsession = await self._get_or_create_agbsession(agent, "mobile_latest")

            # Input text using mobile module
            result = await agbsession.mobile.input_text(text)

            if result.success:
                return f"✅ Successfully input text: {text}"
            else:
                return self._handle_error(Exception(result.error_message), "inputting text")
        except Exception as e:
            return self._handle_error(e, "inputting text")

    async def mobile_send_key(self, agent: Union[Agent, Team], key_code: int) -> str:
        """
        Send hardware key press on mobile device (Home, Back, Menu, etc.).

        USE THIS TOOL when you need to:
        - Press Android hardware buttons
        - Navigate using system keys
        - Control device functions

        Common key codes:
        - 3: HOME button
        - 4: BACK button
        - 82: MENU button
        - 24: VOLUME_UP
        - 25: VOLUME_DOWN
        - 26: POWER button

        Examples:
        - Press Home: mobile_send_key(key_code=3)
        - Press Back: mobile_send_key(key_code=4)

        Args:
            key_code: Android key code integer

        Returns:
            Success message with key name or error
        """
        try:
            agbsession = await self._get_or_create_agbsession(agent, "mobile_latest")

            # Send key using mobile module
            result = await agbsession.mobile.send_key(key_code)

            key_names = {3: "HOME", 4: "BACK", 24: "VOLUME_UP", 25: "VOLUME_DOWN", 26: "POWER", 82: "MENU"}
            key_name = key_names.get(key_code, f"KEY_{key_code}")

            if result.success:
                return f"✅ Successfully sent key: {key_name} ({key_code})"
            else:
                return self._handle_error(Exception(result.error_message), "sending key")
        except Exception as e:
            return self._handle_error(e, "sending key")

    async def mobile_screenshot(self, agent: Union[Agent, Team]) -> str:
        """
        Capture screenshot of mobile device screen.

        USE THIS TOOL when you need to:
        - See the current state of mobile UI
        - Verify app screens and content
        - Get coordinates for tapping elements

        Returns:
            Success message with screenshot file path or error
        """
        try:
            agbsession = await self._get_or_create_agbsession(agent, "mobile_latest")

            # Take screenshot using mobile module
            result = await agbsession.mobile.screenshot()

            if result.success:
                return f"✅ Mobile screenshot captured successfully\nPath: {result.data}"
            else:
                return self._handle_error(Exception(result.error_message), "taking mobile screenshot")
        except Exception as e:
            return self._handle_error(e, "taking mobile screenshot")

    async def get_mobile_apps(self, agent: Union[Agent, Team], include_system: bool = False) -> str:
        """
        Get list of installed mobile applications.

        USE THIS TOOL when you need to:
        - Find what mobile apps are available
        - Check if a specific app is installed
        - Get app package names for launching

        Examples:
        - List user apps: get_mobile_apps(include_system=False)
        - List all apps: get_mobile_apps(include_system=True)

        Args:
            include_system: Include system applications (default: False)

        Returns:
            JSON list of apps with name, package name, and path, or message if no apps found
        """
        try:
            agbsession = await self._get_or_create_agbsession(agent, "mobile_latest")

            # Get installed apps using mobile module
            result = await agbsession.mobile.get_installed_apps(
                start_menu=True, desktop=False, ignore_system_apps=not include_system
            )

            if result.success:
                if result.data:
                    apps_info = []
                    for app in result.data:
                        apps_info.append(
                            {
                                "name": getattr(app, "name", "Unknown"),
                                "package": getattr(app, "package_name", "Unknown"),
                                "path": getattr(app, "path", "Unknown"),
                            }
                        )

                    return f"✅ Found {len(apps_info)} mobile applications:\n{json.dumps(apps_info, indent=2, ensure_ascii=False)}"
                else:
                    return "✅ No mobile applications installed"
            else:
                return self._handle_error(
                    Exception(
                        result.error_message if hasattr(result, "error_message") else "Failed to get mobile apps"
                    ),
                    "getting mobile apps",
                )
        except Exception as e:
            return self._handle_error(e, "getting mobile apps")

    async def start_mobile_app(
        self, agent: Union[Agent, Team], package_name: str, activity: Optional[str] = None
    ) -> str:
        """
        Start a mobile application by package name.

        USE THIS TOOL when you need to:
        - Launch a specific mobile app
        - Start an app before automating it

        TIP: Use get_mobile_apps first to find available package names.

        Examples:
        - Start app: start_mobile_app(package_name="com.example.app")
        - Start with activity: start_mobile_app(package_name="com.app", activity=".MainActivity")

        Args:
            package_name: App package name (e.g., "com.android.browser")
            activity: Optional specific activity to launch

        Returns:
            Success message with process information or error
        """
        try:
            agbsession = await self._get_or_create_agbsession(agent, "mobile_latest")

            # Start app using mobile module
            result = await agbsession.mobile.start_app(start_cmd=package_name, activity=activity or "")

            if result.success and result.data:
                processes_info = []
                for process in result.data:
                    processes_info.append(
                        {
                            "pid": getattr(process, "pid", "Unknown"),
                            "name": getattr(process, "name", "Unknown"),
                            "package": getattr(process, "package_name", "Unknown"),
                        }
                    )

                return f"✅ Successfully started mobile app: {package_name}\nProcesses: {json.dumps(processes_info, indent=2, ensure_ascii=False)}"
            else:
                return self._handle_error(
                    Exception(
                        result.error_message if hasattr(result, "error_message") else "Failed to start mobile app"
                    ),
                    "starting mobile app",
                )
        except Exception as e:
            return self._handle_error(e, "starting mobile app")

    async def stop_mobile_app(self, agent: Union[Agent, Team], package_name: str) -> str:
        """
        Stop a running mobile application by package name.

        USE THIS TOOL when you need to:
        - Close a mobile app
        - Force stop an application
        - Clean up after testing

        Args:
            package_name: App package name to stop (e.g., "com.example.app")

        Returns:
            Success message or error if app not running
        """
        try:
            agbsession = await self._get_or_create_agbsession(agent, "mobile_latest")

            # Stop app using mobile module
            result = await agbsession.mobile.stop_app_by_cmd(package_name)

            if result.success:
                return f"✅ Successfully stopped mobile app: {package_name}"
            else:
                return self._handle_error(Exception(result.error_message), "stopping mobile app")
        except Exception as e:
            return self._handle_error(e, "stopping mobile app")

    async def get_ui_elements(
        self, agent: Union[Agent, Team], clickable_only: bool = True, timeout_ms: int = 2000
    ) -> str:
        """
        Get UI elements from current mobile screen with their properties and coordinates.

        USE THIS TOOL when you need to:
        - Find tappable elements on screen
        - Get element coordinates for tapping
        - Understand the UI structure

        TIP: Use this before mobile_tap to find exact coordinates.

        Examples:
        - Get clickable elements: get_ui_elements(clickable_only=True)
        - Get all elements: get_ui_elements(clickable_only=False)

        Args:
            clickable_only: Return only clickable elements (default: True)
            timeout_ms: Maximum wait time in milliseconds (default: 2000)

        Returns:
            JSON list of UI elements with bounds, className, text, and resourceId
        """
        try:
            agbsession = await self._get_or_create_agbsession(agent, "mobile_latest")

            # Get UI elements using mobile module
            if clickable_only:
                result = await agbsession.mobile.get_clickable_ui_elements(timeout_ms)
            else:
                result = await agbsession.mobile.get_all_ui_elements(timeout_ms)

            if result.success and result.elements:
                elements_info = []
                for element in result.elements:
                    element_info = {
                        "bounds": element.get("bounds", ""),
                        "className": element.get("className", ""),
                        "text": element.get("text", ""),
                        "resourceId": element.get("resourceId", ""),
                        "index": element.get("index", -1),
                    }
                    elements_info.append(element_info)

                element_type = "clickable" if clickable_only else "all"
                return f"✅ Found {len(elements_info)} {element_type} UI elements:\n{json.dumps(elements_info, indent=2, ensure_ascii=False)}"
            else:
                return self._handle_error(
                    Exception(result.error_message if hasattr(result, "error_message") else "No UI elements found"),
                    "getting UI elements",
                )
        except Exception as e:
            return self._handle_error(e, "getting UI elements")

    # === Agent Task Execution Tools ===
    async def browser_agent_execute_task(
        self, agent: Union[Agent, Team], task: str, timeout: int = 300, environment: Optional[str] = None
    ) -> str:
        """
        Execute a browser automation task using natural language description.

        USE THIS TOOL when you need to:
        - Execute complex multi-step browser workflows
        - Let AI automatically plan and execute browser tasks
        - Handle tasks where page structure may be uncertain
        - Complete complex workflows without manual step-by-step control

        DIFFERENCE FROM MANUAL TOOLS:
        - Manual tools (navigate_to_url, act, etc.): Require explicit step-by-step calls
        - This agent tool: Automatically plans and executes multiple steps from a single task description

        WHEN TO USE:
        - Complex tasks: "Open Baidu, search for 'AgentBay SDK', extract all result titles and links"
        - Multi-step workflows: "Login to website, fill form, submit, and take screenshot"
        - Uncertain page structure: Let AI figure out how to navigate and interact

        WHEN TO USE MANUAL TOOLS INSTEAD:
        - Simple, single operations: Just navigate, just click, just extract
        - Need precise control: Control exact timing, quality, or parameters
        - Debugging: Need to see each step's result

        PREREQUISITE: Requires browser_latest environment (automatically handled).

        HOW IT WORKS:
        - Uses AI to understand the task and plan execution steps
        - Automatically navigates, interacts, and extracts as needed
        - Handles errors and retries automatically
        - Returns final result when task completes or times out

        Examples:
        - Search and extract: browser_agent_execute_task(task="Open Baidu, search 'Python tutorial', extract all result titles")
        - Complex workflow: browser_agent_execute_task(task="Login to example.com with username 'test' and password 'pass', navigate to dashboard, take screenshot")
        - Data extraction: browser_agent_execute_task(task="Go to news site, find all article headlines from today, save them to a list")

        Args:
            task: Natural language description of the complete task to execute
            timeout: Maximum time to wait for task completion in seconds (default: 300, max: 3600)
            environment: Optional environment override (default: browser_latest)

        Returns:
            Task execution result including task_id, status, and result content, or error message
        """
        try:
            env = environment or "browser_latest"
            agbsession = await self._get_or_create_agbsession(agent, env)

            # Execute task using browser agent (async version)
            result = await agbsession.agent.browser.execute_task_and_wait(task, timeout)

            if result.success:
                response = {
                    "status": "success",
                    "task_id": result.task_id,
                    "task_status": result.task_status,
                    "task_result": getattr(result, "task_result", "Task completed successfully"),
                }
                return f"✅ Browser agent task completed successfully:\n{json.dumps(response, indent=2, ensure_ascii=False)}"
            else:
                error_msg = result.error_message or "Task execution failed"
                return self._handle_error(
                    Exception(f"Browser agent task failed: {error_msg}"), "executing browser agent task"
                )
        except Exception as e:
            return self._handle_error(e, "executing browser agent task")

    async def computer_agent_execute_task(
        self, agent: Union[Agent, Team], task: str, timeout: int = 300, environment: Optional[str] = None
    ) -> str:
        """
        Execute a desktop automation task using natural language description.

        USE THIS TOOL when you need to:
        - Execute complex multi-step desktop application workflows
        - Let AI automatically plan and execute desktop tasks
        - Handle tasks involving multiple applications or complex UI interactions
        - Complete workflows without knowing exact coordinates or UI structure

        DIFFERENCE FROM MANUAL TOOLS:
        - Manual tools (click_coordinates, type_text, etc.): Require exact coordinates and explicit steps
        - This agent tool: Automatically finds UI elements and executes multi-step workflows

        WHEN TO USE:
        - Complex workflows: "Open Notepad, type 'Hello World', save as hello.txt"
        - Multi-app tasks: "Open Chrome, navigate to website, take screenshot, close browser"
        - UI automation: "Find and click the 'Settings' button, change theme to dark mode"

        WHEN TO USE MANUAL TOOLS INSTEAD:
        - Simple operations: Just take screenshot, just click at known coordinates
        - Need precise control: Control exact coordinates, timing, or application state
        - Debugging: Need to see each step's result

        PREREQUISITE: Requires windows_latest environment (automatically handled).

        HOW IT WORKS:
        - Uses AI vision to understand desktop UI and locate elements
        - Automatically plans and executes multiple steps
        - Handles application launching, interaction, and cleanup
        - Returns final result when task completes or times out

        Examples:
        - File operations: computer_agent_execute_task(task="Open Notepad, write 'Hello World', save as hello.txt in Documents folder")
        - App workflow: computer_agent_execute_task(task="Open Calculator app, calculate 123 * 456, take screenshot of result")
        - Complex task: computer_agent_execute_task(task="Open File Explorer, navigate to Downloads, find all .pdf files, list their names")

        Args:
            task: Natural language description of the complete task to execute
            timeout: Maximum time to wait for task completion in seconds (default: 300, max: 3600)
            environment: Optional environment override (default: windows_latest)

        Returns:
            Task execution result including task_id, status, and result content, or error message
        """
        try:
            env = environment or "windows_latest"
            agbsession = await self._get_or_create_agbsession(agent, env)

            # Execute task using computer agent (async version)
            result = await agbsession.agent.computer.execute_task_and_wait(task, timeout)

            if result.success:
                response = {
                    "status": "success",
                    "task_id": result.task_id,
                    "task_status": result.task_status,
                    "task_result": getattr(result, "task_result", "Task completed successfully"),
                }
                return f"✅ Computer agent task completed successfully:\n{json.dumps(response, indent=2, ensure_ascii=False)}"
            else:
                error_msg = result.error_message or "Task execution failed"
                return self._handle_error(
                    Exception(f"Computer agent task failed: {error_msg}"), "executing computer agent task"
                )
        except Exception as e:
            return self._handle_error(e, "executing computer agent task")

    async def mobile_agent_execute_task(
        self,
        agent: Union[Agent, Team],
        task: str,
        timeout: int = 300,
        max_steps: int = 50,
        environment: Optional[str] = None,
    ) -> str:
        """
        Execute a mobile automation task using natural language description.

        USE THIS TOOL when you need to:
        - Execute complex multi-step mobile app workflows
        - Let AI automatically plan and execute mobile tasks
        - Handle tasks involving app navigation, form filling, or complex interactions
        - Complete workflows without knowing exact coordinates or UI element details

        DIFFERENCE FROM MANUAL TOOLS:
        - Manual tools (mobile_tap, mobile_swipe, etc.): Require exact coordinates and explicit steps
        - This agent tool: Automatically finds UI elements and executes multi-step workflows

        WHEN TO USE:
        - Complex app workflows: "Open WeChat, find contact 'John', send message 'Hello'"
        - Multi-step tasks: "Open Settings app, navigate to Display, change brightness to 50%"
        - Form filling: "Open app, fill login form with username 'test' and password 'pass', submit"

        WHEN TO USE MANUAL TOOLS INSTEAD:
        - Simple operations: Just tap at known coordinates, just swipe, just take screenshot
        - Need precise control: Control exact coordinates, timing, or app state
        - Debugging: Need to see each step's result

        PREREQUISITE: Requires mobile_latest environment (automatically handled).

        HOW IT WORKS:
        - Uses AI vision to understand mobile UI and locate elements
        - Automatically plans and executes multiple steps (taps, swipes, inputs)
        - Handles app launching, navigation, interaction, and cleanup
        - Limits execution to max_steps to prevent infinite loops
        - Returns final result when task completes or times out

        Examples:
        - App workflow: mobile_agent_execute_task(task="Open Calculator app, calculate 123 + 456, take screenshot")
        - Messaging: mobile_agent_execute_task(task="Open messaging app, find contact 'Alice', send message 'Hello from AgentBay'")
        - Settings: mobile_agent_execute_task(task="Open Settings, go to Wi-Fi settings, turn on Wi-Fi if off")

        Args:
            task: Natural language description of the complete task to execute
            timeout: Maximum time to wait for task completion in seconds (default: 300, max: 3600)
            max_steps: Maximum number of steps (taps/swipes/etc.) allowed (default: 50, max: 200)
                      Prevents infinite loops or excessive resource consumption
            environment: Optional environment override (default: mobile_latest)

        Returns:
            Task execution result including task_id, status, and result content, or error message
        """
        try:
            env = environment or "mobile_latest"
            agbsession = await self._get_or_create_agbsession(agent, env)

            # Execute task using mobile agent (async version)
            result = await agbsession.agent.mobile.execute_task_and_wait(task, timeout, max_steps)

            if result.success:
                response = {
                    "status": "success",
                    "task_id": result.task_id,
                    "task_status": result.task_status,
                    "task_result": getattr(result, "task_result", "Task completed successfully"),
                }
                return f"✅ Mobile agent task completed successfully:\n{json.dumps(response, indent=2, ensure_ascii=False)}"
            else:
                error_msg = result.error_message or "Task execution failed"
                return self._handle_error(
                    Exception(f"Mobile agent task failed: {error_msg}"), "executing mobile agent task"
                )
        except Exception as e:
            return self._handle_error(e, "executing mobile agent task")
