from typing import Callable, Optional

from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text


def build_workflow_step_panel(
    step_name: Optional[str],
    step_content: Optional[str],
    markdown: bool,
    create_panel: Callable[..., Panel],
    running: bool = True,
) -> Optional[Panel]:
    """Build a panel for a workflow step.

    Args:
        step_name: The name of the workflow step.
        step_content: The content of the workflow step.
        markdown: Whether to render content as markdown.
        create_panel: Function to create a panel.
        running: Whether the step is still running (True) or completed (False).

    Returns:
        A Panel if step_name and step_content are provided, None otherwise.
    """
    if step_name and step_content:
        title_suffix = "(Running...)" if running else "(Completed)"
        return create_panel(
            content=Markdown(step_content) if markdown else Text(step_content),
            title=f"Step: {step_name} {title_suffix}",
            border_style="orange3",
        )
    return None
