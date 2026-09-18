from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_error

try:
    from llm_sandbox import SandboxSession
    from llm_sandbox.exceptions import SandboxError
except ImportError:
    raise ImportError("`llm-sandbox` not installed. Please install using `pip install 'llm-sandbox[docker]'`")


# Dropping every capability breaks execution on its own: llm-sandbox copies the
# source file into the container, and without DAC_OVERRIDE it cannot be read.
# Everything else stays dropped -- CapEff is 0000000000000002 inside.
#
# read_only is deliberately absent: Docker rejects the code copy against a
# read-only rootfs ("container rootfs is marked read-only"), tmpfs or not.
DEFAULT_RUNTIME_CONFIGS: Dict[str, Any] = {
    "network_mode": "none",
    "mem_limit": "512m",
    "pids_limit": 128,
    "cap_drop": ["ALL"],
    "cap_add": ["DAC_OVERRIDE"],
    "security_opt": ["no-new-privileges:true"],
}


class LLMSandboxTools(Toolkit):
    def __init__(
        self,
        lang: str = "python",
        backend: str = "docker",
        image: Optional[str] = None,
        timeout: float = 30.0,
        runtime_configs: Optional[Dict[str, Any]] = None,
        keep_template: bool = True,
        verbose_session: bool = False,
        enable_run_code: bool = True,
        enable_list_languages: bool = True,
        **kwargs,
    ):
        """Initialize the LLM Sandbox toolkit for self-hosted code execution.

        Unlike the E2B and Daytona toolkits, execution happens on container
        infrastructure you already run -- Docker, Podman or Kubernetes -- so
        there is no API key, no per-execution cost, and code never leaves your
        machines.

        The container is hardened by default: no network, capped memory and
        pids, every Linux capability dropped except DAC_OVERRIDE, and
        no-new-privileges set.

        This is container isolation, not VM isolation: it inherits the threat
        model of the chosen backend and makes no kernel-level guarantee. For
        deliberately adversarial code, pair it with a hardened runtime such as
        gVisor or Kata Containers.

        Args:
            lang: Language to execute: python, javascript, java, cpp, go, r or ruby.
            backend: Container backend: docker, podman, kubernetes or micromamba.
            image: Optional custom image. There is no package-installation
                argument, because the default network isolation would block it
                and letting a model choose arbitrary PyPI packages runs
                setup.py at install time. Pre-bake dependencies here instead.
            timeout: Seconds before an execution is aborted.
            runtime_configs: Container settings passed to the backend. Defaults
                to DEFAULT_RUNTIME_CONFIGS.
            keep_template: Keep the base image after the session closes.
                Setting this False re-pulls the image on every call.
            verbose_session: Emit llm-sandbox session logs.
            enable_run_code: Register the run_code function.
            enable_list_languages: Register the list_supported_languages function.
        """
        self.lang = lang
        self.backend = backend
        self.image = image
        self.timeout = timeout
        self.runtime_configs = DEFAULT_RUNTIME_CONFIGS if runtime_configs is None else runtime_configs
        self.keep_template = keep_template
        self.verbose_session = verbose_session

        tools: List[Any] = []
        if enable_run_code:
            tools.append(self.run_code)
        if enable_list_languages:
            tools.append(self.list_supported_languages)

        super().__init__(name="llm_sandbox_tools", tools=tools, **kwargs)

    def _session_kwargs(self) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "lang": self.lang,
            "backend": self.backend,
            "verbose": self.verbose_session,
            "keep_template": self.keep_template,
            "runtime_configs": self.runtime_configs,
        }
        if self.image is not None:
            kwargs["image"] = self.image
        return kwargs

    def run_code(self, code: str) -> str:
        """
        Run code in an isolated, self-hosted container and return what it printed.

        Use this for calculations, data processing, and anything easier to
        compute than to reason about. Always print the result: only stdout is
        returned.

        Args:
            code (str): Source to execute, complete and self-contained.

        Returns:
            str: stdout on success. On a non-zero exit, the exit code followed
                by stderr, or stdout when stderr is empty.
        """
        try:
            with SandboxSession(**self._session_kwargs()) as session:
                result = session.run(code, timeout=self.timeout)
                exit_code, stdout, stderr = result.exit_code, result.stdout, result.stderr
        except SandboxError:
            # Logged rather than returned: the message can carry the
            # DOCKER_HOST socket path, which is host reconnaissance for a model
            # that may be acting on injected input.
            log_error("llm-sandbox execution failed")
            return "sandbox error: execution environment unavailable"

        if exit_code != 0:
            return f"exit {exit_code}\n{stderr or stdout}".strip()
        return stdout.strip() or "(no output)"

    def list_supported_languages(self) -> str:
        """
        List the languages this sandbox can execute.

        Returns:
            str: Comma-separated language identifiers.
        """
        return "python, javascript, java, cpp, go, r, ruby"
