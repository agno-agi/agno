from typing import List, Optional, Union

from agno.aws.app.base import AwsApp, ContainerContext  # noqa: F401


class Django(AwsApp):
    # -*- App Name
    name: str = "django"

    # -*- Image Configuration
    image_name: str = "agnohq/django"
    image_tag: str = "4.2.2"
    command: Optional[Union[str, List[str]]] = "python manage.py runserver 0.0.0.0:8000"

    # -*- App Ports
    # Open a container port if open_port=True
    open_port: bool = True
    port_number: int = 8000

    # -*- Workspace Configuration
    # Path to the workspace directory inside the container
    workspace_dir_container_path: str = "/app"

    # -*- ECS Configuration
    ecs_task_cpu: str = "1024"
    ecs_task_memory: str = "2048"
    ecs_service_count: int = 1
    assign_public_ip: Optional[bool] = True
