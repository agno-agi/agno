import base64
import json
import tempfile
import time
from os import fdopen, getenv
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union
from uuid import uuid4

from agno.agent import Agent
from agno.media import ImageArtifact
from agno.team.team import Team
from agno.tools import Toolkit
from agno.utils.code_execution import prepare_python_code
from agno.utils.log import logger

try:
    from e2b_code_interpreter import Sandbox
except ImportError:
    raise ImportError("`e2b_code_interpreter` not installed. Please install using `pip install e2b_code_interpreter`")


class E2BTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        run_code: bool = True,
        upload_file: bool = True,
        download_result: bool = True,
        filesystem: bool = False,
        internet_access: bool = False,
        sandbox_management: bool = False,
        timeout: int = 300,  # 5 minutes default timeout
        sandbox_options: Optional[Dict[str, Any]] = None,
        command_execution: bool = False,
        **kwargs,
    ):
        """Initialize E2B toolkit for code interpretation and running Python code in a sandbox.

        Args:
            api_key: E2B API key (defaults to E2B_API_KEY environment variable)
            run_code: Whether to register the run_code function
            upload_file: Whether to register the upload_file function
            download_result: Whether to register the download_result function
            filesystem: Whether to register filesystem operations
            internet_access: Whether to register internet access functions
            sandbox_management: Whether to register sandbox management functions
            timeout: Timeout in seconds for the sandbox (default: 5 minutes)
            sandbox_options: Additional options to pass to the Sandbox constructor
        """

        self.api_key = api_key or getenv("E2B_API_KEY")
        if not self.api_key:
            raise ValueError("E2B_API_KEY not set. Please set the E2B_API_KEY environment variable.")

        # Create the sandbox once and reuse it
        self.sandbox_options = sandbox_options or {}

        # According to official docs, the parameter is 'timeout' (in seconds), not 'timeout_ms'
        try:
            self.sandbox = Sandbox(api_key=self.api_key, timeout=timeout, **self.sandbox_options)
        except Exception as e:
            logger.error(f"Warning: Could not create sandbox: {e}")
            raise e

        # Last execution result for reference
        self.last_execution = None
        self.downloaded_files: Dict[int, str] = {}

        tools: List[Any] = []

        if run_code:
            tools.append(self.run_python_code)
        if upload_file:
            tools.append(self.upload_file)
        if download_result:
            tools.extend([self.download_png_result, self.download_chart_data, self.download_file_from_sandbox])
        if filesystem:
            tools.extend([self.list_files, self.read_file_content, self.write_file_content, self.watch_directory])
        if internet_access:
            tools.extend([self.get_public_url, self.run_server])
        if sandbox_management:
            tools.extend(
                [self.set_sandbox_timeout, self.get_sandbox_status, self.shutdown_sandbox, self.list_running_sandboxes]
            )
        if command_execution:
            tools.extend(
                [self.run_command, self.stream_command, self.run_background_command, self.kill_background_command]
            )

        super().__init__(name="e2b_tools", tools=tools, **kwargs)

    # Code Execution Functions
    def run_python_code(self, code: str) -> str:
        """
        Run Python code in an isolated E2B sandbox environment.

        Args:
            code (str): Python code to execute

        Returns:
            str: Execution results or error message
        """
        try:
            executable_code = prepare_python_code(code)

            execution = self.sandbox.run_code(executable_code)
            self.last_execution = execution

            # Check for errors
            if execution.error:
                return f"Error: {execution.error.name}\n{execution.error.value}\n{execution.error.traceback}"

            # Process results
            results = []

            # Add logs if available
            if hasattr(execution, "logs") and execution.logs:
                results.append(f"Logs:\n{execution.logs}")

            # Process individual results
            for i, result in enumerate(execution.results):
                if hasattr(result, "text") and result.text:
                    results.append(f"Result {i + 1}: {result.text}")
                elif hasattr(result, "png") and result.png:
                    results.append(f"Result {i + 1}: Generated PNG image (use download_png_result to save)")
                elif hasattr(result, "chart") and result.chart:
                    chart_type = result.chart.get("type", "unknown")
                    results.append(
                        f"Result {i + 1}: Generated interactive {chart_type} chart (use download_chart_data to save)"
                    )
                else:
                    results.append(f"Result {i + 1}: Output available")

            return json.dumps(results) if results else "Code executed successfully with no output."

        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error executing code: {str(e)}"})

    #  File Upload/Download Functions
    def upload_file(self, file_path: str, sandbox_path: Optional[str] = None) -> str:
        """
        Upload a file to the E2B sandbox.

        Args:
            file_path (str): Path to the file on the local system
            sandbox_path (str, optional): Destination path in the sandbox. Defaults to the same filename.

        Returns:
            str: Path to the file in the sandbox or error message
        """
        try:
            # Determine the sandbox path if not provided
            if not sandbox_path:
                sandbox_path = Path(file_path).name

            # Upload the file
            with open(file_path, "rb") as f:
                file_in_sandbox = self.sandbox.files.write(sandbox_path, f)

            return file_in_sandbox.path
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error uploading file: {str(e)}"})

    def download_png_result(
        self, agent: Union[Agent, Team], result_index: int = 0, output_path: Optional[str] = None
    ) -> str:
        """
        Add a PNG image result from the last code execution as an ImageArtifact to the agent.

        Args:
            agent: The agent to add the image artifact to
            result_index (int): Index of the result to use (default: 0, the first result)
            output_path (str, optional): Optional path to also save the PNG file. If not provided, image is only added as artifact.

        Returns:
            str: Success message or error message
        """
        if not self.last_execution:
            return "No code has been executed yet"

        try:
            # Check if the result exists
            if result_index >= len(self.last_execution.results):
                return f"Result index {result_index} is out of range. Only {len(self.last_execution.results)} results available."

            result = self.last_execution.results[result_index]

            # Check if the result has a PNG
            if not result.png:
                return f"Result at index {result_index} is not a PNG image"

            # Decode PNG data from base64
            png_data = base64.b64decode(result.png)

            # Optionally save to file if output_path is provided
            if output_path:
                with open(output_path, "wb") as f:
                    f.write(png_data)
                self.downloaded_files[result_index] = output_path

            # Create a temporary file to store the image for URL access

            # Create a temp file with .png extension
            fd, temp_path = tempfile.mkstemp(suffix=".png")
            with fdopen(fd, "wb") as tmp:
                tmp.write(png_data)

            # Generate a file:// URL for the temp file
            file_url = f"file://{temp_path}"

            # Add image artifact to the agent
            image_id = str(uuid4())
            agent.add_image(
                ImageArtifact(
                    id=image_id, url=file_url, original_prompt=f"Generated from code execution result {result_index}"
                )
            )

            if output_path:
                return f"Image added as artifact with ID {image_id} and saved to {output_path}"
            else:
                return f"Image added as artifact with ID {image_id}"

        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error processing PNG: {str(e)}"})

    def download_chart_data(
        self, agent: Agent, result_index: int = 0, output_path: Optional[str] = None, add_as_artifact: bool = True
    ) -> str:
        """
        Extract chart data from an interactive chart in the execution results.
        Optionally add the chart as an image artifact to the agent.

        Args:
            agent: The agent to add the chart artifact to
            result_index (int): Index of the result to extract data from (default: 0)
            output_path (str, optional): Path to save the JSON data. Defaults to 'chart-data-{result_index}.json'
            add_as_artifact (bool): Whether to add the chart as an image artifact (default: True)

        Returns:
            str: Information about the extracted chart data or error message
        """
        if not self.last_execution:
            return "No code has been executed yet"

        try:
            # Check if the result exists
            if result_index >= len(self.last_execution.results):
                return f"Result index {result_index} is out of range. Only {len(self.last_execution.results)} results available."

            result = self.last_execution.results[result_index]

            # Check if the result has chart data
            if not result.chart:
                return f"Result at index {result_index} does not contain interactive chart data"

            # Format chart data
            chart_data = result.chart
            chart_type = chart_data.get("type", "unknown")

            # Determine output path
            if not output_path:
                output_path = f"chart-data-{result_index}.json"

            # Save chart data as JSON
            with open(output_path, "w") as f:
                json.dump(chart_data, f, indent=2)

            # Create a summary
            summary = f"Interactive {chart_type} chart data saved to {output_path}\n"
            if "title" in chart_data:
                summary += f"Title: {chart_data['title']}\n"
            if "x_label" in chart_data:
                summary += f"X-axis: {chart_data['x_label']}\n"
            if "y_label" in chart_data:
                summary += f"Y-axis: {chart_data['y_label']}\n"

            # Add as an image artifact if requested
            if add_as_artifact and result.png:
                # Decode PNG data from base64
                png_data = base64.b64decode(result.png)

                # Create a temporary file to store the image for URL access
                import os
                import tempfile

                # Create a temp file with .png extension
                fd, temp_path = tempfile.mkstemp(suffix=".png")
                with os.fdopen(fd, "wb") as tmp:
                    tmp.write(png_data)

                # Generate a file:// URL for the temp file
                file_url = f"file://{temp_path}"

                # Add image artifact to the agent
                image_id = str(uuid4())
                agent.add_image(
                    ImageArtifact(
                        id=image_id, url=file_url, original_prompt=f"Interactive {chart_type} chart from code execution"
                    )
                )

                summary += f"\nChart image added as artifact with ID {image_id}"

            return summary

        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error extracting chart data: {str(e)}"})

    def download_file_from_sandbox(self, sandbox_path: str, local_path: Optional[str] = None) -> str:
        """
        Download a file from the E2B sandbox to the local system.

        Args:
            sandbox_path (str): Path to the file in the sandbox
            local_path (str, optional): Destination path on the local system. Defaults to the same filename.

        Returns:
            str: Path to the downloaded file or error message
        """
        try:
            # Determine local path if not provided
            if not local_path:
                local_path = Path(sandbox_path).name

            # Download the file
            content = self.sandbox.files.read(sandbox_path)

            with open(local_path, "wb") as f:
                f.write(content)

            return local_path
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error downloading file: {str(e)}"})

    # Command Execution Functions
    def run_command(
        self,
        command: str,
        on_stdout: Optional[Callable] = None,
        on_stderr: Optional[Callable] = None,
        background: bool = False,
    ) -> str:
        """
        Run a shell command in the sandbox environment.

        Args:
            command (str): Shell command to execute
            on_stdout (callable, optional): Callback function for streaming stdout
            on_stderr (callable, optional): Callback function for streaming stderr
            background (bool): Whether to run the command in background

        Returns:
            str: Command results or error message, or the command object for background execution
        """
        try:
            # Prepare streaming callbacks
            kwargs = {}
            if on_stdout:
                kwargs["on_stdout"] = on_stdout
            if on_stderr:
                kwargs["on_stderr"] = on_stderr

            # Set background execution if requested
            process_kwargs = {"background": background}  # Using a separate dict for process arguments

            # Execute the command
            result = self.sandbox.commands.run(command, **kwargs, **process_kwargs)

            # For background execution, return the command object
            if background:
                return "Command started in background. Use the returned command object to interact with it."

            # For synchronous execution, return the output
            output = []
            if hasattr(result, "stdout") and result.stdout:
                output.append(f"STDOUT:\n{result.stdout}")
            if hasattr(result, "stderr") and result.stderr:
                output.append(f"STDERR:\n{result.stderr}")

            return json.dumps(output) if output else "Command executed successfully with no output."

        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error executing command: {str(e)}"})

    def stream_command(self, command: str) -> str:
        """
        Run a shell command and stream its output.

        Args:
            command (str): Shell command to execute

        Returns:
            str: Summary of command execution
        """
        outputs = []

        def stdout_callback(data):
            outputs.append(f"STDOUT: {data}")
            logger.info(f"STDOUT: {data}")

        def stderr_callback(data):
            outputs.append(f"STDERR: {data}")
            logger.error(f"STDERR: {data}")

        try:
            self.run_command(command, on_stdout=stdout_callback, on_stderr=stderr_callback)
            return json.dumps(outputs) if outputs else "Command completed with no output."
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error streaming command: {str(e)}"})

    def run_background_command(self, command: str) -> Any:
        """
        Run a shell command in the background.

        Args:
            command (str): Shell command to execute in background

        Returns:
            object: Command object that can be used to interact with the background process
        """
        try:
            # Execute the command in background
            command_obj = self.sandbox.commands.run(command, background=True)
            return command_obj
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error starting background command: {str(e)}"})

    def kill_background_command(self, command_obj: Any) -> str:
        """
        Kill a background command.

        Args:
            command_obj: Command object returned from run_background_command

        Returns:
            str: Result of the kill operation
        """
        try:
            if isinstance(command_obj, str):
                return "Invalid command object. Please provide the object returned from run_background_command."

            command_obj.kill()
            return "Background command terminated successfully."
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error killing background command: {str(e)}"})

    # Filesystem Operations
    def list_files(self, directory_path: str = "/") -> str:
        """
        List files and directories in the specified path in the sandbox.

        Args:
            directory_path (str): Path to the directory to list (default: root directory)

        Returns:
            str: List of files and directories or error message
        """
        try:
            files = self.sandbox.files.list(directory_path)
            if not files:
                return f"No files found in {directory_path}"

            result = f"Contents of {directory_path}:\n"
            for file in files:
                file_type = "Directory" if file.is_dir else "File"
                size = f"{file.size} bytes" if file.size is not None else "Unknown size"
                result += f"- {file.name} ({file_type}, {size})\n"

            return result
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error listing files: {str(e)}"})

    def read_file_content(self, file_path: str, encoding: str = "utf-8") -> str:
        """
        Read the content of a file from the sandbox.

        Args:
            file_path (str): Path to the file in the sandbox
            encoding (str): Encoding to use for text files (default: utf-8)

        Returns:
            str: File content or error message
        """
        try:
            content = self.sandbox.files.read(file_path)

            # Try to decode as text if encoding is provided
            try:
                text_content = content.decode(encoding)
                return text_content
            except UnicodeDecodeError:
                return f"File read successfully but contains binary data ({len(content)} bytes). Use download_file_from_sandbox to save it."

        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error reading file: {str(e)}"})

    def write_file_content(self, file_path: str, content: str) -> str:
        """
        Write text content to a file in the sandbox.

        Args:
            file_path (str): Path to the file in the sandbox
            content (str): Text content to write

        Returns:
            str: Success message or error message
        """
        try:
            # Convert string to bytes
            bytes_content = content.encode("utf-8")

            # Write the file
            file_info = self.sandbox.files.write(file_path, bytes_content)

            return file_info.path
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error writing file: {str(e)}"})

    def watch_directory(self, directory_path: str, duration_seconds: int = 5) -> str:
        """
        Watch a directory for changes for a specified duration.

        Args:
            directory_path (str): Path to the directory to watch
            duration_seconds (int): How long to watch for changes in seconds (default: 5 seconds)

        Returns:
            str: List of changes detected or error message
        """
        try:
            changes = []

            # Setup watcher
            watcher = self.sandbox.files.watch_dir(directory_path)

            # Watch for changes
            start_time = time.time()
            while time.time() - start_time < duration_seconds:
                change = watcher.get_change(timeout=0.5)
                if change:
                    changes.append(f"{change.event} - {change.path}")

            # Close watcher
            watcher.close()

            if changes:
                return json.dumps(
                    {
                        "status": "success",
                        "message": f"Changes detected in {directory_path} over {duration_seconds} seconds:\n"
                        + "\n".join(changes),
                    }
                )
            else:
                return json.dumps(
                    {
                        "status": "success",
                        "message": f"No changes detected in {directory_path} over {duration_seconds} seconds",
                    }
                )

        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error watching directory: {str(e)}"})

    # Internet Access Functions
    def get_public_url(self, port: int) -> str:
        """
        Get a public URL for a service running in the sandbox on the specified port.

        Args:
            port (int): Port number the service is running on in the sandbox

        Returns:
            str: Public URL or error message
        """
        try:
            host = self.sandbox.get_host(port)

            return f"http://{host}"
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error getting public URL: {str(e)}"})

    def run_server(self, command: str, port: int) -> str:
        """
        Start a server in the sandbox and return its public URL.

        Args:
            command (str): Command to start the server
            port (int): Port the server will listen on

        Returns:
            str: Server information including public URL or error message
        """
        try:
            # Start the server in the background
            self.sandbox.commands.run(command, background=True)

            # # Wait a moment for the server to start
            time.sleep(2)

            # Get the public URL
            host = self.sandbox.get_host(port)
            url = f"http://{host}"

            return url
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error starting server: {str(e)}"})

    # Sandbox Management Functions
    def set_sandbox_timeout(self, timeout: int) -> str:
        """
        Update the timeout for the sandbox.

        Args:
            timeout: New timeout in seconds

        Returns:
            str: Success message or error message
        """
        try:
            # According to the documentation, it might be set_timeout in Python SDK
            if hasattr(self.sandbox, "set_timeout"):
                self.sandbox.set_timeout(timeout)
            # Fallback for direct property access if method doesn't exist
            else:
                self.sandbox.timeout = timeout

            return str(timeout)  # Convert int to str before returning
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error updating sandbox timeout: {str(e)}"})

    def get_sandbox_status(self) -> str:
        """
        Get the current status of the sandbox.

        Returns:
            str: Sandbox status information
        """
        try:
            # Collect sandbox information
            sandbox_id = getattr(self.sandbox, "id", "Unknown")

            return sandbox_id

        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error getting sandbox status: {str(e)}"})

    def shutdown_sandbox(self) -> str:
        """
        Shutdown the sandbox immediately.

        Returns:
            str: Success message or error message
        """
        try:
            cont = self.sandbox.kill()
            return json.dumps({"status": "success", "message": "Sandbox shut down successfully", "content": cont})
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error shutting down sandbox: {str(e)}"})

    def list_running_sandboxes(self) -> str:
        """
        List all running sandboxes.

        Returns:
            str: JSON string containing information about running sandboxes or error message
        """
        try:
            running_sandboxes = self.sandbox.list()

            if not running_sandboxes:
                return json.dumps({"status": "success", "message": "No running sandboxes found", "sandboxes": []})

            sandboxes_info = []
            for sandbox in running_sandboxes:
                info = {
                    "sandbox_id": getattr(sandbox, "sandbox_id", "Unknown"),
                    "started_at": str(getattr(sandbox, "started_at", "Unknown")),
                    "template_id": getattr(sandbox, "template_id", "Unknown"),
                    "metadata": getattr(sandbox, "metadata", {}),
                }
                sandboxes_info.append(info)

            return json.dumps(
                {
                    "status": "success",
                    "message": f"Found {len(sandboxes_info)} running sandboxes",
                    "sandboxes": sandboxes_info,
                },
                indent=2,
            )

        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error listing running sandboxes: {str(e)}"})
