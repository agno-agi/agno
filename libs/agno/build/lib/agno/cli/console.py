from rich.console import Console
from rich.style import Style

from agno.utils.log import logger

console = Console()

######################################################
## Styles
# Standard Colors: https://rich.readthedocs.io/en/stable/appendix/colors.html#appendix-colors
######################################################

heading_style = Style(
    color="green",
    bold=True,
    underline=True,
)
subheading_style = Style(
    color="chartreuse3",
    bold=True,
)
success_style = Style(color="chartreuse3")
fail_style = Style(color="red")
error_style = Style(color="red")
info_style = Style()
warn_style = Style(color="magenta")


######################################################
## Print functions
######################################################


def print_heading(msg: str) -> None:
    console.print(msg, style=heading_style)


def print_subheading(msg: str) -> None:
    console.print(msg, style=subheading_style)


def print_info(msg: str) -> None:
    console.print(msg, style=info_style)


def log_config_not_available_msg() -> None:
    logger.error("Agno config not found, please run `ag init` and try again")


def log_active_workspace_not_available() -> None:
    logger.error("Could not find an active workspace. You can:")
    logger.error("- Run `ag ws setup` to setup a workspace at the current path")
    logger.error("- Run `ag ws create` to create a new workspace")


def print_available_workspaces(avl_ws_list) -> None:
    avl_ws_names = [w.ws_root_path.stem for w in avl_ws_list] if avl_ws_list else []
    print_info("Available Workspaces:\n  - {}".format("\n  - ".join(avl_ws_names)))


def confirm_yes_no(question, default: str = "yes") -> bool:
    """Ask a yes/no question via raw_input().

    "question" is a string that is presented to the user.
    "default" is the presumed answer if the user just hits <Enter>.
            It must be "yes" (the default), "no" or None (meaning
            an answer is required of the user).

    The "answer" return value is True for "yes" or False for "no".
    """
    inp_to_result_map = {"yes": True, "y": True, "ye": True, "no": False, "n": False}
    if default is None:
        prompt = " [y/n]: "
    elif default == "yes":
        prompt = " [Y/n]: "
    elif default == "no":
        prompt = " [y/N]: "
    else:
        raise ValueError(f"Invalid default answer: {default}")

    choice = console.input(prompt=(question + prompt)).lower()
    if default is not None and choice == "":
        return inp_to_result_map[default]
    elif choice in inp_to_result_map:
        return inp_to_result_map[choice]
    else:
        logger.error(f"{choice} invalid")
        return False
