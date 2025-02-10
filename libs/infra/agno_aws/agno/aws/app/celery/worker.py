from typing import List, Optional, Union

from agno.aws.app.base import AwsApp, AwsBuildContext, ContainerContext  # noqa: F401


class CeleryWorker(AwsApp):
    # -*- App Name
    name: str = "celery-worker"

    # -*- Image Configuration
    image_name: str = "agnohq/celery-worker"
    image_tag: str = "latest"
    command: Optional[Union[str, List[str]]] = "celery -A tasks.celery worker --loglevel=info"

    # -*- Workspace Configuration
    # Path to the workspace directory inside the container
    workspace_dir_container_path: str = "/app"
