from agno.docker.app.base import ContainerContext, DockerApp  # noqa: F401


class Whoami(DockerApp):
    # -*- App Name
    name: str = "whoami"

    # -*- Image Configuration
    image_name: str = "traefik/whoami"
    image_tag: str = "v1.10"

    # -*- App Ports
    # Open a container port if open_port=True
    open_port: bool = True
    port_number: int = 80
