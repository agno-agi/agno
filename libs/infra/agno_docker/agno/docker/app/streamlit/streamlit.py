from typing import Dict, List, Optional, Union

from agno.docker.app.base import ContainerContext, DockerApp  # noqa: F401


class Streamlit(DockerApp):
    # -*- App Name
    name: str = "streamlit"

    # -*- Image Configuration
    image_name: str = "agnohq/streamlit"
    image_tag: str = "1.27"
    command: Optional[Union[str, List[str]]] = "streamlit hello"

    # -*- App Ports
    # Open a container port if open_port=True
    open_port: bool = True
    port_number: int = 8501

    # -*- Workspace Configuration
    # Path to the workspace directory inside the container
    workspace_dir_container_path: str = "/app"
    # Mount the workspace directory from host machine to the container
    mount_workspace: bool = False

    # -*- Streamlit Configuration
    # Server settings
    # Defaults to the port_number
    streamlit_server_port: Optional[int] = None
    streamlit_server_headless: bool = True
    streamlit_server_run_on_save: Optional[bool] = None
    streamlit_server_max_upload_size: Optional[int] = None
    streamlit_browser_gather_usage_stats: bool = False
    # Browser settings
    streamlit_browser_server_port: Optional[str] = None
    streamlit_browser_server_address: Optional[str] = None

    def get_container_env(self, container_context: ContainerContext) -> Dict[str, str]:
        container_env: Dict[str, str] = super().get_container_env(container_context=container_context)

        streamlit_server_port = self.streamlit_server_port
        if streamlit_server_port is None:
            port_number = self.port_number
            if port_number is not None:
                streamlit_server_port = port_number
        if streamlit_server_port is not None:
            container_env["STREAMLIT_SERVER_PORT"] = str(streamlit_server_port)

        if self.streamlit_server_headless is not None:
            container_env["STREAMLIT_SERVER_HEADLESS"] = str(self.streamlit_server_headless)

        if self.streamlit_server_run_on_save is not None:
            container_env["STREAMLIT_SERVER_RUN_ON_SAVE"] = str(self.streamlit_server_run_on_save)

        if self.streamlit_server_max_upload_size is not None:
            container_env["STREAMLIT_SERVER_MAX_UPLOAD_SIZE"] = str(self.streamlit_server_max_upload_size)

        if self.streamlit_browser_gather_usage_stats is not None:
            container_env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = str(self.streamlit_browser_gather_usage_stats)

        if self.streamlit_browser_server_port is not None:
            container_env["STREAMLIT_BROWSER_SERVER_PORT"] = self.streamlit_browser_server_port

        if self.streamlit_browser_server_address is not None:
            container_env["STREAMLIT_BROWSER_SERVER_ADDRESS"] = self.streamlit_browser_server_address

        return container_env
