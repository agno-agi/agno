"""Operator-declared watch commands.

A monitor stores only the *name* of a watch, never a shell string, so creating
one never carries a command over the wire and monitors:write is not equivalent
to shell access. This is where the operator says what those names mean.

A declaration used to be a bare command string, which left the two things an
operator most often needs -- where the command runs, and what it is for -- with
nowhere to live: the directory had to be baked into the string as a `cd ... &&`
prefix, and the description had to be repeated in a second mapping handed to
MonitorTools. Both hang off the declaration now, and a bare string still works.
"""

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Union


@dataclass
class WatchCommand:
    """A shell command monitors may run, and how to run it.

    Args:
        command: The shell command. Runs through a shell, so pipelines work.
        description: What this watch is for. Reaches the model through
            ``MonitorTools(watches=...)``, which is what lets it answer "none of
            these fit" instead of picking the closest-sounding name.
        cwd: Directory to run in. Without it the command inherits the server's
            working directory, which is wherever the process happened to start.
        env: Extra environment variables for the command. These are layered on
            top of the server's environment, never a replacement for it -- the
            command otherwise sees everything the AgentOS process sees,
            including any credentials in its environment. Nothing is scrubbed by
            default: a command that needs PATH would stop working, and these
            declarations are the operator's own.
    """

    command: str
    description: str = ""
    cwd: Optional[str] = None
    env: Dict[str, str] = field(default_factory=dict)


def normalize_watch_commands(
    watch_commands: Optional[Mapping[str, Union[str, WatchCommand]]],
) -> Dict[str, WatchCommand]:
    """Accept the bare-string form and the full form, return only the full form."""
    normalized: Dict[str, WatchCommand] = {}
    for name, declared in (watch_commands or {}).items():
        normalized[name] = WatchCommand(command=declared) if isinstance(declared, str) else declared
    return normalized
