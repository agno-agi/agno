import logging
from os import getenv
from typing import Any, Optional

from rich.logging import RichHandler
from rich.text import Text

LOGGER_NAME = "agno"

# Define custom styles for different log sources
LOG_STYLES = {
    "warning": "magenta",
    "error": "red",
    "exception": "red",
    "debug": "green",
    "info": "blue",
}


class ColoredRichHandler(RichHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def get_level_text(self, record: logging.LogRecord) -> Text:
        # Return empty Text if message is empty
        if not record.msg:
            return Text("")

        level_name = record.levelname.lower()
        color = LOG_STYLES[level_name]
        return Text(record.levelname, style=color)


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


logger: AgnoLogger = build_logger(LOGGER_NAME)

debug_on: bool = False


def set_log_level_to_debug():
    _logger = logging.getLogger(LOGGER_NAME)
    _logger.setLevel(logging.DEBUG)

    global debug_on
    debug_on = True


def set_log_level_to_info():
    _logger = logging.getLogger(LOGGER_NAME)
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
