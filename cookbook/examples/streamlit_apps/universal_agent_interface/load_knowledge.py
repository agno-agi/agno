"""
Load the Knowledge Base for the Universal Agent Interface
"""

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from uagi import uagi_knowledge

# Create a Rich console for enhanced output
console = Console()


def load_knowledge(recreate: bool = False):
    """
    Load the Universal Agent Interface knowledge base.

    Args:
        recreate (bool, optional): Whether to recreate the knowledge base.
            Defaults to False.
    """
    with Progress(
        SpinnerColumn(), TextColumn("[bold blue]{task.description}"), console=console
    ) as progress:
        task = progress.add_task(
            "Loading Universal Agent Interface knowledge...", total=None
        )

        # Load the knowledge base
        uagi_knowledge.load(recreate=recreate)
        progress.update(task, completed=True)

    # Display success message in a panel
    console.print(
        Panel.fit(
            "[bold green]Universal Agent Interface knowledge loaded successfully!",
            title="Knowledge Loaded",
        )
    )


if __name__ == "__main__":
    load_knowledge()
