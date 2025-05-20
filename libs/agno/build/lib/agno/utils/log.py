import logging
from os import getenv
from typing import Any, Optional

from rich.logging import RichHandler
from rich.text import Text

LOGGER_NAME = "agno"
TEAM_LOGGER_NAME = f"{LOGGER_NAME}-team"

# Define custom styles for different log sources
LOG_STYLES = {
    "agent": {
        "debug": "green",
        "info": "blue",
    },
    "team": {
        "debug": "magenta",
        "info": "steel_blue1",
    },
}


class ColoredRichHandler(RichHandler):
    def __init__(self, *args, source_type: Optional[str] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.source_type = source_type

    def get_level_text(self, record: logging.LogRecord) -> Text:
        # Return empty Text if message is empty
        if not record.msg:
            return Text("")

        level_name = record.levelname.lower()
        if self.source_type and self.source_type in LOG_STYLES:
            if level_name in LOG_STYLES[self.source_type]:
                color = LOG_STYLES[self.source_type][level_name]
                return Text(record.levelname, style=color)
        return super().get_level_text(record)


class AgnoLogger(logging.Logger):
    def __init__(self, name: str, level: int = logging.NOTSET):
        super().__init__(name, level)

    def debug(self, msg: str, center: bool = False, symbol: str = "*", *args, **kwargs):
        if center:
            msg = center_header(str(msg), symbol)
        super().debug(msg, *args, **kwargs)

    def info(self, msg: str, center: bool = False, symbol: str = "*", *args, **kwargs):
        if center:
            msg = center_header(str(msg), symbol)
        super().info(msg, *args, **kwargs)


def build_logger(logger_name: str, source_type: Optional[str] = None) -> Any:
    # Set the custom logger class as the default for this logger
    logging.setLoggerClass(AgnoLogger)

    # Create logger with custom class
    _logger = logging.getLogger(logger_name)

    # Reset logger class to default to avoid affecting other loggers
    logging.setLoggerClass(logging.Logger)

    # https://rich.readthedocs.io/en/latest/reference/logging.html#rich.logging.RichHandler
    # https://rich.readthedocs.io/en/latest/logging.html#handle-exceptions
    rich_handler = ColoredRichHandler(
        show_time=False,
        rich_tracebacks=False,
        show_path=True if getenv("AGNO_API_RUNTIME") == "dev" else False,
        tracebacks_show_locals=False,
        source_type=source_type or "agent",
    )
    rich_handler.setFormatter(
        logging.Formatter(
            fmt="%(message)s",
            datefmt="[%X]",
        )
    )

    _logger.addHandler(rich_handler)
    _logger.setLevel(logging.INFO)
    _logger.propagate = False
    return _logger


agent_logger: AgnoLogger = build_logger(LOGGER_NAME, source_type="agent")
team_logger: AgnoLogger = build_logger(TEAM_LOGGER_NAME, source_type="team")

# Set the default logger to the agent logger
logger: AgnoLogger = agent_logger

debug_on: bool = False


def set_log_level_to_debug(source_type: Optional[str] = None):
    _logger = logging.getLogger(LOGGER_NAME if source_type is None else f"{LOGGER_NAME}-{source_type}")
    _logger.setLevel(logging.DEBUG)

    global debug_on
    debug_on = True


def set_log_level_to_info(source_type: Optional[str] = None):
    _logger = logging.getLogger(LOGGER_NAME if source_type is None else f"{LOGGER_NAME}-{source_type}")
    _logger.setLevel(logging.INFO)

    global debug_on
    debug_on = False


def center_header(message: str, symbol: str = "*") -> str:
    try:
        import shutil

        terminal_width = shutil.get_terminal_size().columns
    except Exception:
        terminal_width = 80  # fallback width

    header = f" {message} "
    return f"{header.center(terminal_width - 20, symbol)}"


def use_team_logger():
    """Switch the default logger to use team_logger"""
    global logger
    logger = team_logger


def use_agent_logger():
    """Switch the default logger to use the default agent logger"""
    global logger
    logger = agent_logger


def log_debug(msg, center: bool = False, symbol: str = "*", *args, **kwargs):
    global logger
    global debug_on
    if debug_on:
        logger.debug(msg, center, symbol, *args, **kwargs)


def log_info(msg, center: bool = False, symbol: str = "*", *args, **kwargs):
    global logger
    logger.info(msg, center, symbol, *args, **kwargs)


def log_warning(msg, *args, **kwargs):
    global logger
    logger.warning(msg, *args, **kwargs)


def log_error(msg, *args, **kwargs):
    global logger
    logger.error(msg, *args, **kwargs)


def log_exception(msg, *args, **kwargs):
    global logger
    logger.exception(msg, *args, **kwargs)
