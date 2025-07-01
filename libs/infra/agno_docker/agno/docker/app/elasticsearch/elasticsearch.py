from typing import Dict, List, Optional, Union

from agno.docker.app.base import ContainerContext, DockerApp  # noqa: F401


class ElasticSearch(DockerApp):
    # -*- App Name
    name: str = "elasticsearch"

    # -*- Image Configuration
    image_name: str = "docker.elastic.co/elasticsearch/elasticsearch"
    image_tag: str = "8.17.3"
    # command: Optional[Union[str, List[str]]] = "elastic -e 'discovery.type=single-node"

    # -*- App Ports
    # Open a container port if open_port=True
    open_port: bool = True
    port_number: int = 9200

    # -*- Elasticsearch Volume
    # Create a volume for elasticsearch storage
    create_volume: bool = True
    # Path to mount the volume inside the container
    volume_container_path: str = "/data"

    # -*- Elasticsearch Configuration
    # -*- Workspace Configuration
    # Path to the workspace directory inside the container
    workspace_dir_container_path: str = "/app"
    # Mount the workspace directory from host machine to the container
    mount_workspace: bool = False
