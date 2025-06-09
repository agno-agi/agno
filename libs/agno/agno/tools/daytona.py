import json
from os import getenv
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.code_execution import prepare_python_code
from agno.utils.log import logger

try:
    from daytona_sdk import (
        CodeLanguage,
        CreateSandboxParams,
        Daytona,
        DaytonaConfig,
        Sandbox,
        SandboxTargetRegion,
    )
    from daytona_sdk.common.process import ExecuteResponse
except ImportError:
    raise ImportError("`daytona_sdk` not installed. Please install using `pip install daytona_sdk`")


class DaytonaTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        sandbox_language: Optional[CodeLanguage] = None,
        sandbox_target_region: Optional[SandboxTargetRegion] = None,
        sandbox_os: Optional[str] = None,
        sandbox_os_user: Optional[str] = None,
        sandbox_env_vars: Optional[Dict[str, str]] = None,
        sandbox_labels: Optional[Dict[str, str]] = None,
        sandbox_public: Optional[bool] = None,
        sandbox_auto_stop_interval: Optional[int] = None,
        organization_id: Optional[str] = None,
        timeout: int = 300,  # 5 minutes default timeout
        **kwargs,
    ):
        """Daytona Toolkit for remote code execution.

        Args:
            api_key: Daytona API key (defaults to DAYTONA_API_KEY environment variable)
            api_url: Daytona API URL (defaults to DAYTONA_API_URL environment variable)
            sandbox_language: The programming language to run on the sandbox (default: python)
            sandbox_target_region: The region where the sandbox will be created
            sandbox_os: The operating system to run on the sandbox (default: ubuntu)
            sandbox_os_user: The user to run the sandbox as (default: root)
            sandbox_env_vars: The environment variables to set in the sandbox
            sandbox_labels: The labels to set in the sandbox
            sandbox_public: Whether the sandbox should be public
            sandbox_auto_stop_interval: The interval in minutes after which the sandbox will be stopped if no activity occurs
            organization_id: The contextual Daytona organization ID for the sandbox
            timeout: Timeout in seconds for communication with the sandbox (default: 5 minutes)
        """

        self.api_key = api_key or getenv("DAYTONA_API_KEY")
        if not self.api_key:
            raise ValueError("DAYTONA_API_KEY not set. Please set the DAYTONA_API_KEY environment variable.")

        self.api_url = api_url or getenv("DAYTONA_API_URL")
        self.sandbox_target_region = sandbox_target_region
        self.organization_id = organization_id
        self.sandbox_language = sandbox_language
        self.sandbox_os = sandbox_os
        self.sandbox_os_user = sandbox_os_user
        self.sandbox_env_vars = sandbox_env_vars
        self.sandbox_labels = sandbox_labels
        self.sandbox_public = sandbox_public
        self.sandbox_auto_stop_interval = sandbox_auto_stop_interval
        self.timeout = timeout

        self.config = DaytonaConfig(
            api_key=self.api_key,
            api_url=self.api_url,
            target=self.sandbox_target_region,
            organization_id=self.organization_id,
        )  # type: ignore

        try:
            params = CreateSandboxParams(
                language=self.sandbox_language,
                os_user=self.sandbox_os_user,
                env_vars=self.sandbox_env_vars,
                labels=self.sandbox_labels,
                public=self.sandbox_public,
                auto_stop_interval=self.sandbox_auto_stop_interval,
                timeout=self.timeout,
            )
            daytona = Daytona(self.config)
            self.sandbox: Sandbox = daytona.create(params)
        except Exception as e:
            logger.error(f"Error creating Daytona sandbox: {e}")
            raise e

        # Last execution result for reference
        self.last_execution: Optional[ExecuteResponse] = None

        tools: List[Any] = []

        if self.sandbox_language == CodeLanguage.PYTHON:
            tools.append(self.run_python_code)
        else:
            tools.append(self.run_code)

        super().__init__(name="daytona_tools", tools=tools, **kwargs)

    def run_python_code(self, code: str) -> str:
        """Prepare and run Python code in the contextual Daytona sandbox."""
        try:
            executable_code = prepare_python_code(code)

            execution = self.sandbox.process.code_run(executable_code)

            self.last_execution = execution
            self.result = execution.result
            return self.result
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error executing code: {str(e)}"})

    def run_code(self, code: str) -> str:
        """General function to run non-Python code in the contextual Daytona sandbox."""
        try:
            response = self.sandbox.process.code_run(code)

            self.last_execution = response
            self.result = response.result
            return self.result
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Error executing code: {str(e)}"})
