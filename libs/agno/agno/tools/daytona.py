import json
from os import getenv
from pathlib import Path
from textwrap import dedent
from typing import Dict, Optional, Union

from agno.agent import Agent
from agno.team import Team
from agno.tools import Toolkit
from agno.utils.code_execution import prepare_python_code
from agno.utils.log import log_debug, log_error, log_info, log_warning

try:
    from daytona import (
        CodeLanguage,
        CreateSandboxFromSnapshotParams,
        Daytona,
        DaytonaConfig,
        Sandbox,
    )
except ImportError:
    raise ImportError("`daytona` not installed. Please install using `pip install daytona`")

DEFAULT_INSTRUCTIONS = dedent(
    """\
    You have access to a persistent Daytona sandbox for code execution. The sandbox maintains state across interactions.
    
    Available tools:
    - `run_code`: Execute code in the sandbox
    - `run_shell_command`: Execute shell commands (bash)
    - `create_file`: Create or update files
    - `read_file`: Read file contents
    - `list_files`: List directory contents
    - `delete_file`: Delete files or directories
    - `change_directory`: Change the working directory
    
    MANDATORY: When users ask for code (Python, JavaScript, TypeScript, etc.), you MUST:
    1. Write the code
    2. Execute it using run_code tool
    3. Show the actual output/results
    4. Never just provide code without executing it
    
    CRITICAL WORKFLOW:
    1. Before running Python scripts, check if required packages are installed
    2. Install missing packages with: run_shell_command("pip install package1 package2")
    3. When running scripts, capture both output AND errors
    4. If a script produces no output, check for errors or add print statements
    
    IMPORTANT: Always use single quotes for the content parameter when creating files
    
    Remember: Your job is to provide working, executed code examples, not just code snippets!
    """
)


class DaytonaTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        sandbox_id: Optional[str] = None,
        sandbox_language: Optional[CodeLanguage] = None,
        sandbox_target: Optional[str] = None,
        sandbox_os: Optional[str] = None,
        auto_stop_interval: Optional[int] = 60,  # Stop after 1 hour
        sandbox_os_user: Optional[str] = None,
        sandbox_env_vars: Optional[Dict[str, str]] = None,
        sandbox_labels: Optional[Dict[str, str]] = None,
        sandbox_public: Optional[bool] = None,
        organization_id: Optional[str] = None,
        timeout: int = 300,
        auto_create_sandbox: bool = True,
        verify_ssl: Optional[bool] = False,
        persistent: bool = True,
        instructions: Optional[str] = None,
        add_instructions: bool = False,
        **kwargs,
    ):
        self.api_key = api_key or getenv("DAYTONA_API_KEY")
        if not self.api_key:
            raise ValueError("DAYTONA_API_KEY not set. Please set the DAYTONA_API_KEY environment variable.")

        self.api_url = api_url or getenv("DAYTONA_API_URL")
        self.sandbox_id = sandbox_id
        self.sandbox_target = sandbox_target
        self.organization_id = organization_id
        self.sandbox_language = sandbox_language or CodeLanguage.PYTHON
        self.sandbox_os = sandbox_os
        self.auto_stop_interval = auto_stop_interval
        self.sandbox_os_user = sandbox_os_user
        self.sandbox_env_vars = sandbox_env_vars
        self.sandbox_labels = sandbox_labels or {}
        self.sandbox_public = sandbox_public
        self.timeout = timeout
        self.auto_create_sandbox = auto_create_sandbox
        self.persistent = persistent
        self.verify_ssl = verify_ssl

        # Set instructions - use default if none provided
        self.instructions = instructions or DEFAULT_INSTRUCTIONS

        if not self.verify_ssl:
            self._disable_ssl_verification()

        self.config = DaytonaConfig(
            api_key=self.api_key,
            api_url=self.api_url,
            target=self.sandbox_target,
            organization_id=self.organization_id,
        )

        self.daytona = Daytona(self.config)

        super().__init__(
            name="daytona_tools",
            tools=[
                self.run_code,
                self.run_shell_command,
                self.create_file,
                self.read_file,
                self.list_files,
                self.delete_file,
                self.change_directory,
            ],
            instructions=self.instructions,
            add_instructions=add_instructions,
            **kwargs,
        )

    def _disable_ssl_verification(self) -> None:
        try:
            from daytona_api_client import Configuration

            original_init = Configuration.__init__

            # Create a wrapper that sets verify_ssl = False
            def patched_init(self, *args, **kwargs):
                original_init(self, *args, **kwargs)
                self.verify_ssl = False

            setattr(Configuration, "__init__", patched_init)
            import urllib3

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            log_debug(
                "SSL certificate verification is disabled",
            )
        except ImportError:
            log_warning("Could not import daytona_api_client.Configuration for SSL patching")

    def _get_working_directory(self, agent: Union[Agent, Team]) -> str:
        """Get the current working directory from agent session state."""
        if agent and hasattr(agent, "session_state"):
            if agent.session_state is None:
                agent.session_state = {}
            return agent.session_state.get("working_directory", "/home/daytona")
        return "/home/daytona"

    def _set_working_directory(self, agent: Union[Agent, Team], directory: str) -> None:
        """Set the working directory in agent session state."""
        if agent and hasattr(agent, "session_state"):
            if agent.session_state is None:
                agent.session_state = {}
            agent.session_state["working_directory"] = directory
            log_info(f"Updated working directory to: {directory}")

    def _get_or_create_sandbox(self, agent: Union[Agent, Team]) -> Sandbox:
        """Get existing sandbox or create new one"""
        try:
            sandbox = None

            # Use explicit sandbox
            if self.sandbox_id:
                try:
                    sandbox = self.daytona.get(self.sandbox_id)
                    log_debug(f"Using explicit sandbox: {self.sandbox_id}")
                except Exception as e:
                    log_debug(f"Failed to get sandbox {self.sandbox_id}: {e}")
                    sandbox = None

            # Use persistent sandbox
            elif self.persistent and hasattr(agent, "session_state"):
                if agent.session_state is None:
                    agent.session_state = {}

                sandbox_id = agent.session_state.get("sandbox_id")
                if sandbox_id:
                    try:
                        sandbox = self.daytona.get(sandbox_id)
                        log_debug(f"Using persistent sandbox: {sandbox_id}")
                    except Exception as e:
                        log_debug(f"Failed to get sandbox {sandbox_id}: {e}")
                        sandbox = None

            # Create new sandbox if none found
            if sandbox is None:
                sandbox = self._create_new_sandbox(agent)
                # Store sandbox ID for persistent sandboxes
                if self.persistent and hasattr(agent, "session_state"):
                    if agent.session_state is None:
                        agent.session_state = {}
                    agent.session_state["sandbox_id"] = sandbox.id

            # Ensure sandbox is started
            if sandbox.state != "started":
                log_info(f"Starting sandbox {sandbox.id}")
                self.daytona.start(sandbox, timeout=self.timeout)

            return sandbox
        except Exception as e:
            if self.auto_create_sandbox:
                log_warning(f"Error in sandbox management: {e}. Creating new sandbox.")
                return self._create_new_sandbox(agent)
            else:
                raise e

    def _create_new_sandbox(self, agent: Optional[Union[Agent, Team]] = None) -> Sandbox:
        """Create a new sandbox with the configured parameters."""
        try:
            labels = self.sandbox_labels.copy()
            labels.setdefault("created_by", "agno_daytona_toolkit")
            labels.setdefault("language", str(self.sandbox_language))

            if self.persistent:
                labels.setdefault("persistent", "true")

            params = CreateSandboxFromSnapshotParams(
                language=self.sandbox_language,
                os_user=self.sandbox_os_user,
                env_vars=self.sandbox_env_vars,
                auto_stop_interval=self.auto_stop_interval,
                labels=labels,
                public=self.sandbox_public,
            )
            sandbox = self.daytona.create(params, timeout=self.timeout)

            # Add the sandbox_id to the Agent state
            if self.persistent and agent and hasattr(agent, "session_state"):
                if agent.session_state is None:
                    agent.session_state = {}
                agent.session_state["sandbox_id"] = sandbox.id

            log_info(f"Created new Daytona sandbox: {sandbox.id}")
            return sandbox
        except Exception as e:
            log_error(f"Error creating Daytona sandbox: {e}")
            raise e

    # Tools
    def run_code(self, agent: Union[Agent, Team], code: str) -> str:
        """Execute Python code in the Daytona sandbox.

        Args:
            code: Code to execute

        Returns:
            Execution output as a string
        """
        try:
            current_sandbox = self._get_or_create_sandbox(agent)

            if self.sandbox_language == CodeLanguage.PYTHON:
                code = prepare_python_code(code)

            response = current_sandbox.process.code_run(code)

            self.result = response.result
            return self.result
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error executing code: {str(e)}"})

    def run_shell_command(self, agent: Union[Agent, Team], command: str) -> str:
        """Execute a shell command in the sandbox.

        Args:
            command: Shell command to execute

        Returns:
            Command output as a string
        """
        try:
            current_sandbox = self._get_or_create_sandbox(agent)

            # Use persistent working directory if not specified
            cwd = self._get_working_directory(agent)

            # Handle cd commands specially to update working directory
            if command.strip().startswith("cd "):
                new_dir = command.strip()[3:].strip()
                # Convert to Path
                new_path = Path(new_dir)

                # Resolve relative paths
                if not new_path.is_absolute():
                    # Get current absolute path first
                    result = current_sandbox.process.exec(f"cd {cwd} && pwd", cwd="/")
                    current_abs_path = Path(result.result.strip())
                    new_path = current_abs_path / new_path

                # Normalize the path
                new_path_str = str(new_path.resolve())

                # Test if directory exists
                test_result = current_sandbox.process.exec(
                    f"test -d {new_path_str} && echo 'exists' || echo 'not found'", cwd="/"
                )
                if "exists" in test_result.result:
                    self._set_working_directory(agent, new_path_str)
                    return f"Changed directory to: {new_path_str}"
                else:
                    return f"Error: Directory {new_path_str} not found"

            # Execute the command
            response = current_sandbox.process.exec(command, cwd=cwd)
            return response.result
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error executing command: {str(e)}"})

    def create_file(self, agent: Union[Agent, Team], file_path: str, content: str) -> str:
        """Create or update a file in the sandbox.

        Args:
            file_path: Path to the file (relative to current directory or absolute)
            content: Content to write to the file

        Returns:
            Success message or error
        """
        try:
            current_sandbox = self._get_or_create_sandbox(agent)

            # Convert to Path object
            path = Path(file_path)

            # Handle relative paths
            if not path.is_absolute():
                path = Path(self._get_working_directory(agent)) / path

            # Ensure the path is normalized
            path_str = str(path)

            # Create directory if needed
            parent_dir = str(path.parent)
            if parent_dir and parent_dir != "/":
                result = current_sandbox.process.exec(f"mkdir -p {parent_dir}")
                if result.exit_code != 0:
                    return json.dumps({"status": "error", "message": f"Failed to create directory: {result.result}"})

            # Write the file using shell command
            # Use cat with heredoc for better handling of special characters
            escaped_content = content.replace("'", "'\"'\"'")
            command = f"cat > '{path_str}' << 'EOF'\n{escaped_content}\nEOF"
            result = current_sandbox.process.exec(command)

            if result.exit_code != 0:
                return json.dumps({"status": "error", "message": f"Failed to create file: {result.result}"})

            return f"File created/updated: {path_str}"
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error creating file: {str(e)}"})

    def read_file(self, agent: Union[Agent, Team], file_path: str) -> str:
        """Read a file from the sandbox.

        Args:
            file_path: Path to the file (relative to current directory or absolute)

        Returns:
            File content or error message
        """
        try:
            current_sandbox = self._get_or_create_sandbox(agent)

            # Convert to Path object
            path = Path(file_path)

            # Handle relative paths
            if not path.is_absolute():
                path = Path(self._get_working_directory(agent)) / path

            path_str = str(path)

            # Read file using cat
            result = current_sandbox.process.exec(f"cat '{path_str}'")

            if result.exit_code != 0:
                return json.dumps({"status": "error", "message": f"Error reading file: {result.result}"})

            return result.result
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error reading file: {str(e)}"})

    def list_files(self, agent: Union[Agent, Team], directory: Optional[str] = None) -> str:
        """List files in a directory.

        Args:
            directory: Directory to list (defaults to current working directory)

        Returns:
            List of files and directories as formatted string
        """
        try:
            current_sandbox = self._get_or_create_sandbox(agent)

            # Use current directory if not specified
            if directory is None:
                dir_path = Path(self._get_working_directory(agent))
            else:
                dir_path = Path(directory)
                # Handle relative paths
                if not dir_path.is_absolute():
                    dir_path = Path(self._get_working_directory(agent)) / dir_path

            path_str = str(dir_path)

            # List files using ls -la for detailed info
            result = current_sandbox.process.exec(f"ls -la '{path_str}'")

            if result.exit_code != 0:
                return json.dumps({"status": "error", "message": f"Error listing directory: {result.result}"})

            return f"Contents of {path_str}:\n{result.result}"
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error listing files: {str(e)}"})

    def delete_file(self, agent: Union[Agent, Team], file_path: str) -> str:
        """Delete a file or directory from the sandbox.

        Args:
            file_path: Path to the file or directory (relative to current directory or absolute)

        Returns:
            Success message or error
        """
        try:
            current_sandbox = self._get_or_create_sandbox(agent)

            # Convert to Path object
            path = Path(file_path)

            # Handle relative paths
            if not path.is_absolute():
                path = Path(self._get_working_directory(agent)) / path

            path_str = str(path)

            # Check if it's a directory or file
            check_result = current_sandbox.process.exec(f"test -d '{path_str}' && echo 'directory' || echo 'file'")

            if "directory" in check_result.result:
                # Remove directory recursively
                result = current_sandbox.process.exec(f"rm -rf '{path_str}'")
            else:
                # Remove file
                result = current_sandbox.process.exec(f"rm -f '{path_str}'")

            if result.exit_code != 0:
                return json.dumps({"status": "error", "message": f"Failed to delete: {result.result}"})

            return f"Deleted: {path_str}"
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error deleting file: {str(e)}"})

    def change_directory(self, agent: Union[Agent, Team], directory: str) -> str:
        """Change the current working directory.

        Args:
            directory: Directory to change to (relative to current directory or absolute)

        Returns:
            Success message or error
        """
        try:
            result = self.run_shell_command(agent, f"cd {directory}")
            self._set_working_directory(agent, directory)
            return result
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error changing directory: {str(e)}"})
