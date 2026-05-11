import functools
import runpy
import subprocess
import sys
from pathlib import Path
from typing import Any, FrozenSet, Iterable, List, Optional

from agno.tools import Toolkit
from agno.tools._security import build_safe_builtins
from agno.utils.log import log_debug, log_error, log_info, logger

_PACKAGE_NAME_BAD_CHARS: FrozenSet[str] = frozenset(" ;|&`\n\r\\\"'<>$")


@functools.lru_cache(maxsize=None)
def warn() -> None:
    logger.warning("PythonTools can run arbitrary code, please provide human supervision.")


class PythonTools(Toolkit):
    """Execute and edit Python code on the host filesystem.

    Security notes (hardened build):

    * **In-process Python exec cannot be safely sandboxed.** The three
      code-execution tools (:meth:`save_to_file_and_run`,
      :meth:`run_python_code`, :meth:`run_python_file_return_variable`)
      are **not registered as LLM-callable tools** unless the caller
      passes ``unsafe_exec=True`` at construction time. CPython offers
      no primitive for truly safe in-process execution: even with a
      restricted ``__builtins__``, the subclass-traversal pattern
      ``().__class__.__mro__[-1].__subclasses__()`` reaches every
      loaded class (including ``subprocess.Popen`` and
      ``os._wrap_close``) and escapes any Python-level sandbox. Treat
      ``unsafe_exec=True`` as "I have an out-of-process sandbox
      (nsjail / firejail / seccomp-bpf / ephemeral container with no
      host mounts and a read-only rootfs), and I am accepting the
      in-process RCE surface inside that sandbox".
    * When ``unsafe_exec=True`` is set, a restricted ``__builtins__``
      is still injected as defence-in-depth: it omits ``__import__``,
      ``open``, ``exec``, ``eval``, ``compile``, ``getattr`` /
      ``setattr`` / ``delattr``, ``globals`` / ``locals`` / ``vars`` /
      ``dir``, and the runtime-introspection helpers used by classic
      Python sandbox escapes. This raises the bar for casual abuse
      but does **not** close the subclass-traversal path. Pass
      ``unsafe_exec_full_builtins=True`` to also restore the full
      builtins module when the out-of-process sandbox makes that
      acceptable.
    * ``restrict_to_base_dir`` defaults to ``True`` and cannot be
      disabled without also setting ``unsafe_unrestricted=True``;
      constructing the toolkit with neither flag set raises
      :class:`ValueError`. This applies to :meth:`read_file` and
      :meth:`list_files`, which remain LLM-callable by default
      because they are bounded filesystem reads, not code execution.
    * :meth:`pip_install_package` and :meth:`uv_pip_install_package`
      are not registered as tools unless ``enable_pip_install=True``
      is set explicitly. When they are registered, an optional
      ``pip_install_allowlist`` restricts which packages may be
      installed.

    Args:
        base_dir: Base directory for all file operations. Defaults to
            the current working directory.
        safe_globals: Optional globals dict to seed code execution.
            Defaults to an empty dict. The restricted ``__builtins__``
            is injected unless the caller already supplied one or sets
            ``unsafe_exec_full_builtins=True``.
        safe_locals: Optional locals dict to seed code execution.
            Defaults to an empty dict.
        restrict_to_base_dir: When True (default), every path is
            validated against ``base_dir``.
        unsafe_unrestricted: Must be True to combine with
            ``restrict_to_base_dir=False``. Intended as an opt-in
            foot-gun.
        unsafe_exec: Must be True to register the three code-execution
            tools as LLM-callable. Defaults to False so a hardened
            deployment does not accidentally ship arbitrary Python
            execution to the LLM.
        unsafe_exec_full_builtins: When True, expose the full
            ``builtins`` module to executed code. Requires
            ``unsafe_exec=True``. Defaults to False.
        enable_pip_install: When True, register ``pip_install_package``
            and ``uv_pip_install_package`` as agent tools.
        pip_install_allowlist: Optional iterable of package names that
            may be installed. When set, any package outside the list
            is refused, even with ``enable_pip_install=True``.
    """

    def __init__(
        self,
        base_dir: Optional[Path] = None,
        safe_globals: Optional[dict] = None,
        safe_locals: Optional[dict] = None,
        restrict_to_base_dir: bool = True,
        unsafe_unrestricted: bool = False,
        unsafe_exec: bool = False,
        unsafe_exec_full_builtins: bool = False,
        enable_pip_install: bool = False,
        pip_install_allowlist: Optional[Iterable[str]] = None,
        **kwargs,
    ):
        if not restrict_to_base_dir and not unsafe_unrestricted:
            raise ValueError(
                "restrict_to_base_dir=False requires "
                "unsafe_unrestricted=True; refusing to construct "
                "PythonTools with unrestricted filesystem access."
            )
        if unsafe_exec_full_builtins and not unsafe_exec:
            raise ValueError(
                "unsafe_exec_full_builtins=True requires "
                "unsafe_exec=True; refusing to expose full builtins "
                "while the code-execution tools are disabled."
            )

        self.base_dir: Path = (base_dir or Path.cwd()).resolve()
        self.restrict_to_base_dir: bool = restrict_to_base_dir
        self.unsafe_exec: bool = bool(unsafe_exec)
        self.unsafe_exec_full_builtins: bool = bool(unsafe_exec_full_builtins)

        base_globals: dict = dict(safe_globals) if safe_globals is not None else {}
        if "__builtins__" not in base_globals and not self.unsafe_exec_full_builtins:
            base_globals["__builtins__"] = build_safe_builtins()
        self.safe_globals: dict = base_globals
        self.safe_locals: dict = safe_locals if safe_locals is not None else {}
        self._pip_allowlist: Optional[FrozenSet[str]] = (
            frozenset(p.strip() for p in pip_install_allowlist) if pip_install_allowlist else None
        )

        tools: List[Any] = [
            self.read_file,
            self.list_files,
        ]
        if self.unsafe_exec:
            tools.insert(0, self.save_to_file_and_run)
            tools.insert(1, self.run_python_code)
            tools.insert(2, self.run_python_file_return_variable)
        if enable_pip_install:
            tools.append(self.pip_install_package)
            tools.append(self.uv_pip_install_package)

        super().__init__(name="python_tools", tools=tools, **kwargs)

    def _fresh_exec_globals(self) -> dict:
        """Return a fresh globals dict for a single exec / runpy call.

        Copies the outer mapping and, when a restricted ``__builtins__``
        dict is present, copies that too. Without the inner copy, LLM
        code could mutate the shared dict across calls (e.g.
        ``__builtins__['x'] = something_nasty``) and persist state
        between invocations. ``unsafe_exec=True`` bypasses this path
        entirely — the caller has opted into the full builtins module.
        """
        globals_copy = dict(self.safe_globals)
        builtins_entry = globals_copy.get("__builtins__")
        if isinstance(builtins_entry, dict):
            globals_copy["__builtins__"] = dict(builtins_entry)
        return globals_copy

    def _check_install_allowed(self, package_name: str) -> Optional[str]:
        """Validate ``package_name`` against the install policy.

        Args:
            package_name: The raw value forwarded by the LLM, e.g.
                ``"requests"`` or ``"requests==2.31"``.

        Returns:
            None when the package is allowed. Otherwise a
            human-readable reason string suitable for surfacing to
            the agent.
        """
        if not isinstance(package_name, str) or not package_name.strip():
            return "Package name must be a non-empty string."
        if any(c in _PACKAGE_NAME_BAD_CHARS for c in package_name):
            return "Package name contains disallowed characters."
        if self._pip_allowlist is not None:
            base = package_name
            for sep in ("==", ">", "<", "~", "!"):
                base = base.split(sep, 1)[0]
            base = base.strip()
            if base not in self._pip_allowlist:
                return f"Package '{base}' is not on the install allowlist."
        return None

    def save_to_file_and_run(
        self,
        file_name: str,
        code: str,
        variable_to_return: Optional[str] = None,
        overwrite: bool = True,
    ) -> str:
        """Save Python code to ``file_name`` and execute it.

        Make sure the file_name ends with ``.py``.

        :param file_name: The name of the file the code will be saved to.
        :param code: The code to save and run.
        :param variable_to_return: The variable to return.
        :param overwrite: Overwrite the file if it already exists.
        :return: The value of ``variable_to_return`` if provided and
            the run succeeded, otherwise a success/error message.
        """
        try:
            warn()
            safe, file_path = self._check_path(file_name, self.base_dir, self.restrict_to_base_dir)
            if not safe:
                return f"Error: Path '{file_name}' is outside the allowed base directory"
            log_debug(f"Saving code to {file_path}")
            if not file_path.parent.exists():
                file_path.parent.mkdir(parents=True, exist_ok=True)
            if file_path.exists() and not overwrite:
                return f"File {file_name} already exists"
            file_path.write_text(code, encoding="utf-8")
            log_info(f"Saved: {file_path}")
            log_info(f"Running {file_path}")
            globals_after_run = runpy.run_path(
                str(file_path),
                init_globals=self._fresh_exec_globals(),
                run_name="__main__",
            )

            if variable_to_return:
                variable_value = globals_after_run.get(variable_to_return)
                if variable_value is None:
                    return f"Variable {variable_to_return} not found"
                log_debug(f"Variable {variable_to_return} value: {variable_value}")
                return str(variable_value)
            return f"successfully ran {str(file_path)}"
        except Exception as e:
            logger.exception("Error saving and running code")
            return f"Error saving and running code: {e}"

    def run_python_file_return_variable(self, file_name: str, variable_to_return: Optional[str] = None) -> str:
        """Run code already on disk and optionally return a variable.

        :param file_name: The name of the file to run.
        :param variable_to_return: The variable to return.
        :return: The value of ``variable_to_return`` if provided and
            the run succeeded, otherwise a success/error message.
        """
        try:
            warn()
            safe, file_path = self._check_path(file_name, self.base_dir, self.restrict_to_base_dir)
            if not safe:
                return f"Error: Path '{file_name}' is outside the allowed base directory"
            log_info(f"Running {file_path}")
            globals_after_run = runpy.run_path(
                str(file_path),
                init_globals=self._fresh_exec_globals(),
                run_name="__main__",
            )
            if variable_to_return:
                variable_value = globals_after_run.get(variable_to_return)
                if variable_value is None:
                    return f"Variable {variable_to_return} not found"
                log_debug(f"Variable {variable_to_return} value: {variable_value}")
                return str(variable_value)
            return f"successfully ran {str(file_path)}"
        except Exception as e:
            logger.exception("Error running file")
            return f"Error running file: {e}"

    def read_file(self, file_name: str) -> str:
        """Read the contents of ``file_name``.

        :param file_name: The name of the file to read.
        :return: The contents of the file on success, otherwise an
            error message.
        """
        try:
            log_info(f"Reading file: {file_name}")
            safe, file_path = self._check_path(file_name, self.base_dir, self.restrict_to_base_dir)
            if not safe:
                log_error(f"Attempted to read file outside base directory: {file_name}")
                return "Error reading file: path outside allowed directory"
            return file_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.exception("Error reading file")
            return f"Error reading file: {e}"

    def list_files(self) -> str:
        """Return a comma-separated list of files in ``base_dir``."""
        try:
            log_info(f"Reading files in : {self.base_dir}")
            files = [str(file_path.name) for file_path in self.base_dir.iterdir()]
            return ", ".join(files)
        except Exception as e:
            logger.exception("Error reading files")
            return f"Error reading files: {e}"

    def run_python_code(self, code: str, variable_to_return: Optional[str] = None) -> str:
        """Execute Python code in-process and optionally return a variable.

        :param code: The code to run.
        :param variable_to_return: The variable to return.
        :return: The value of ``variable_to_return`` if provided,
            otherwise a success/error message.
        """
        try:
            warn()
            log_debug(f"Running code:\n\n{code}\n\n")
            # Fresh copies so LLM code cannot mutate the toolkit's scope.
            exec_globals = self._fresh_exec_globals()
            exec_locals = dict(self.safe_locals)
            exec(code, exec_globals, exec_locals)

            if variable_to_return:
                variable_value = exec_locals.get(variable_to_return)
                if variable_value is None:
                    return f"Variable {variable_to_return} not found"
                log_debug(f"Variable {variable_to_return} value: {variable_value}")
                return str(variable_value)
            return "successfully ran python code"
        except Exception as e:
            logger.exception("Error running python code")
            return f"Error running python code: {e}"

    def pip_install_package(self, package_name: str) -> str:
        """Install a package using ``pip``.

        Registered as an agent tool only when the toolkit is
        constructed with ``enable_pip_install=True``. When an
        allowlist is configured, packages outside the allowlist are
        refused.

        :param package_name: The requirement specifier, e.g.
            ``"requests"`` or ``"requests==2.31"``.
        :return: A success or error message.
        """
        err = self._check_install_allowed(package_name)
        if err:
            return f"Error installing package {package_name}: {err}"
        try:
            warn()
            log_debug(f"Installing package {package_name}")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
            return f"successfully installed package {package_name}"
        except Exception as e:
            logger.exception(f"Error installing package {package_name}")
            return f"Error installing package {package_name}: {e}"

    def uv_pip_install_package(self, package_name: str) -> str:
        """Install a package using ``uv pip``.

        Same controls and error semantics as
        :meth:`pip_install_package`.
        """
        err = self._check_install_allowed(package_name)
        if err:
            return f"Error installing package {package_name}: {err}"
        try:
            warn()
            log_debug(f"Installing package {package_name}")
            subprocess.check_call([sys.executable, "-m", "uv", "pip", "install", package_name])
            return f"successfully installed package {package_name}"
        except Exception as e:
            logger.exception(f"Error installing package {package_name}")
            return f"Error installing package {package_name}: {e}"
