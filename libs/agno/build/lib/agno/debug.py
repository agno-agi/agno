def enable_debug_mode() -> None:
    """Enable debug mode for the agno library.

    This function sets the logging level to DEBUG
    """
    from agno.utils.log import set_log_level_to_debug

    set_log_level_to_debug()


def disable_debug_mode() -> None:
    """Disable debug mode for the agno library.

    This function resets the logging level to INFO
    """
    from agno.utils.log import set_log_level_to_info

    set_log_level_to_info()
