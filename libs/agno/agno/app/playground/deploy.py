import tarfile
from pathlib import Path
from typing import List, Optional, cast

from rich import box
from rich.panel import Panel
from rich.text import Text

from agno.api.playground import deploy_playground_archive
from agno.cli.settings import agno_cli_settings
from agno.utils.log import logger


def create_deployment_info(
    app: str, root: Path, elapsed_time: str = "[waiting...]", status: Optional[str] = None, error: Optional[str] = None
) -> Text:
    """Create a formatted text display showing deployment information.

    Args:
        app (str): The name of the application being deployed
        root (Path): The path to the root directory
        elapsed_time (str): The elapsed deployment time. Defaults to "[waiting...]"
        status (Optional[str]): The current deployment status. Defaults to None
        error (Optional[str]): The deployment error message. Defaults to None

    Returns:
        Text: A Rich Text object containing formatted deployment information
    """
    # Base info always shown
    elements = [
        ("📦 App: ", "bold"),
        (f"{app}\n", "cyan"),
        ("📂 Root: ", "bold"),
        (f"{root}\n", "cyan"),
        ("⏱️  Time: ", "bold"),
        (f"{elapsed_time}\n", "yellow"),
    ]

    # Add either status or error, not both
    if error is not None:
        elements.extend(
            [
                ("🚨 Error: ", "bold"),
                (f"{error}", "red"),
            ]
        )
    elif status is not None:
        elements.extend(
            [
                ("🚧 Status: ", "bold"),
                (f"{status}", "yellow"),
            ]
        )

    return Text.assemble(*elements)


def create_info_panel(deployment_info: Text) -> Panel:
    """Create a formatted panel to display deployment information.

    Args:
        deployment_info (Text): The Rich Text object containing deployment information

    Returns:
        Panel: A Rich Panel object containing the formatted deployment information
    """
    return Panel(
        deployment_info,
        title="[bold green]🚀 Deploying Playground App[/bold green]",
        border_style="cyan",
        box=box.HEAVY,
        padding=(1, 2),
    )


def create_error_panel(deployment_info: Text) -> Panel:
    """Create a formatted panel to display deployment error information.

    Args:
        deployment_info (Text): The Rich Text object containing deployment error information

    Returns:
        Panel: A Rich Panel object containing the formatted deployment error information
    """
    return Panel(
        deployment_info,
        title="[bold red]🚨 Deployment Failed[/bold red]",
        border_style="red",
        box=box.HEAVY,
        padding=(1, 2),
    )


def create_tar_archive(root: Path) -> Path:
    """Create a gzipped tar archive of the playground files.

    Args:
        root (Path): The path to the directory to be archived

    Returns:
        Path: The path to the created tar archive

    Raises:
        Exception: If archive creation fails
    """
    tar_path = root.with_suffix(".tar.gz")
    try:
        logger.debug(f"Creating playground archive: {tar_path.name}")
        with tarfile.open(tar_path, "w:gz") as tar:
            tar.add(root, arcname=root.name)
        logger.debug(f"Successfully created playground archive: {tar_path.name}")
        return tar_path
    except Exception as e:
        logger.error(f"Failed to create playground archive: {e}")
        raise


def deploy_archive(name: str, tar_path: Path) -> None:
    """Deploying the tar archive to agno-cloud.

    Args:
        name (str): The name of the playground app
        tar_path (Path): The path to the tar archive to be deployed

    Raises:
        Exception: If the deployment process fails
    """
    try:
        logger.debug(f"Deploying playground archive: {tar_path.name}")
        deploy_playground_archive(name=name, tar_path=tar_path)
        logger.debug(f"Successfully deployed playground archive: {tar_path.name}")
    except Exception:
        raise


def cleanup_archive(tar_path: Path) -> None:
    """Delete the temporary tar archive after deployment.

    Args:
        tar_path (Path): The path to the tar archive to be deleted

    Raises:
        Exception: If the deletion process fails
    """
    try:
        logger.debug(f"Deleting playground archive: {tar_path.name}")
        tar_path.unlink()
        logger.debug(f"Successfully deleted playground archive: {tar_path.name}")
    except Exception as e:
        logger.error(f"Failed to delete playground archive: {e}")
        raise


def deploy_playground_app(
    app: str,
    name: str,
    root: Optional[Path] = None,
) -> None:
    """Deploy a playground application to agno-cloud.

    This function:
    1. Creates a tar archive of the root directory.
    2. Uploades the archive to agno-cloud.
    3. Cleaning up temporary files.
    4. Displaying real-time progress updates.

    Args:
        app (str): The application to deploy as a string identifier.
                It should be the name of the module containing the Playground app from the root path.
        name (str): The name of the playground app.
        root (Optional[Path]): The root path containing the application files. Defaults to the current working directory.

    Raises:
        Exception: If any step of the deployment process fails
    """

    agno_cli_settings.gate_alpha_feature()

    from rich.console import Group
    from rich.live import Live
    from rich.status import Status

    from agno.utils.timer import Timer

    if app is None:
        raise ValueError("PlaygroundApp is required")

    if name is None:
        raise ValueError("PlaygroundApp name is required")

    with Live(refresh_per_second=4) as live_display:
        response_timer = Timer()
        response_timer.start()
        root = root or Path.cwd()
        root = cast(Path, root)
        try:
            deployment_info = create_deployment_info(app=app, root=root, status="Initializing...")
            panels: List[Panel] = [create_info_panel(deployment_info=deployment_info)]

            status = Status(
                "[bold blue]Initializing playground...[/bold blue]",
                spinner="aesthetic",
                speed=2,
            )
            panels.append(status)  # type: ignore
            live_display.update(Group(*panels))

            # Step 1: Create archive
            status.update("[bold blue]Creating playground archive...[/bold blue]")
            tar_path = create_tar_archive(root=root)
            panels[0] = create_info_panel(
                create_deployment_info(
                    app=app, root=root, elapsed_time=f"{response_timer.elapsed:.1f}s", status="Creating archive..."
                )
            )
            live_display.update(Group(*panels))

            # Step 2: Upload archive
            status.update("[bold blue]Uploading playground archive...[/bold blue]")
            deploy_archive(name=name, tar_path=tar_path)
            panels[0] = create_info_panel(
                create_deployment_info(
                    app=app, root=root, elapsed_time=f"{response_timer.elapsed:.1f}s", status="Uploading archive..."
                )
            )
            live_display.update(Group(*panels))

            # Step 3: Cleanup
            status.update("[bold blue]Deleting playground archive...[/bold blue]")
            cleanup_archive(tar_path)
            panels[0] = create_info_panel(
                create_deployment_info(
                    app=app, root=root, elapsed_time=f"{response_timer.elapsed:.1f}s", status="Deleting archive..."
                )
            )
            live_display.update(Group(*panels))

            # Final display update
            status.stop()
            panels.pop()
            live_display.update(Group(*panels))
        except Exception as e:
            status.update(f"[bold red]Deployment failed: {str(e)}[/bold red]")
            panels[0] = create_error_panel(
                create_deployment_info(app=app, root=root, elapsed_time=f"{response_timer.elapsed:.1f}s", error=str(e))
            )
            status.stop()
            panels.pop()
            live_display.update(Group(*panels))
