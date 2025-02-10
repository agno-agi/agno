from typing import Any, Dict, List, Optional

from agno.docker.api_client import DockerApiClient
from agno.docker.resource.base import DockerResource
from agno.utils.log import logger


class DockerNetwork(DockerResource):
    resource_type: str = "Network"

    # driver (str) – Name of the driver used to create the network
    driver: Optional[str] = None
    # options (dict) – Driver options as a key-value dictionary
    options: Optional[Dict[str, Any]] = None
    # check_duplicate (bool) – Request daemon to check for networks with same name. Default: None.
    auto_remove: Optional[bool] = None
    # internal (bool) – Restrict external access to the network. Default False.
    internal: Optional[bool] = None
    # labels (dict) – Map of labels to set on the network. Default None.
    labels: Optional[Dict[str, Any]] = None
    # enable_ipv6 (bool) – Enable IPv6 on the network. Default False.
    enable_ipv6: Optional[bool] = None
    # attachable (bool) – If enabled, and the network is in the global scope
    # non-service containers on worker nodes will be able to connect to the network.
    attachable: Optional[bool] = None
    # scope (str) – Specify the network’s scope (local, global or swarm)
    scope: Optional[str] = None
    # ingress (bool) – If set, create an ingress network which provides the routing-mesh in swarm mode.
    ingress: Optional[bool] = None

    # Set skip_delete=True so that the network is not deleted when the `ag ws down` command is run
    skip_delete: bool = True
    skip_update: bool = True

    def _create(self, docker_client: DockerApiClient) -> bool:
        """Creates the Network on docker

        Args:
            docker_client: The DockerApiClient for the current cluster
        """
        from docker import DockerClient
        from docker.models.networks import Network

        logger.debug("Creating: {}".format(self.get_resource_name()))
        network_name: Optional[str] = self.name
        network_object: Optional[Network] = None

        try:
            _api_client: DockerClient = docker_client.api_client
            network_object = _api_client.networks.create(network_name)
            if network_object is not None:
                logger.debug("Network Created: {}".format(network_object.name))
            else:
                logger.debug("Network could not be created")
            # logger.debug("Network {}".format(network_object.attrs))
        except Exception:
            raise

        # By this step the network should be created
        # Validate that the network is created
        logger.debug("Validating network is created")
        if network_object is not None:
            # TODO: validate that the network was actually created
            self.active_resource = network_object
            return True

        logger.debug("Network not found")
        return False

    def _read(self, docker_client: DockerApiClient) -> Any:
        """Returns a Network object if the network is active

        Args:
            docker_client: The DockerApiClient for the current cluster"""
        from docker import DockerClient
        from docker.models.networks import Network

        logger.debug("Reading: {}".format(self.get_resource_name()))
        # Get active networks from the docker_client
        network_name: Optional[str] = self.name
        try:
            _api_client: DockerClient = docker_client.api_client
            network_list: Optional[List[Network]] = _api_client.networks.list()
            # logger.debug("network_list: {}".format(network_list))
            if network_list is not None:
                for network in network_list:
                    if network.name == network_name:
                        logger.debug(f"Network {network_name} exists")
                        self.active_resource = network
                        return network
        except Exception:
            logger.debug(f"Network {network_name} not found")

        return None

    def _delete(self, docker_client: DockerApiClient) -> bool:
        """Deletes the Network from docker

        Args:
            docker_client: The DockerApiClient for the current cluster
        """
        from docker.errors import NotFound
        from docker.models.networks import Network

        logger.debug("Deleting: {}".format(self.get_resource_name()))
        network_object: Optional[Network] = self._read(docker_client)
        # Return True if there is no Network to delete
        if network_object is None:
            return True

        # Delete Network
        try:
            self.active_resource = None
            network_object.remove()
        except Exception as e:
            logger.exception("Error while deleting network: {}".format(e))

        # Validate that the network is deleted
        logger.debug("Validating network is deleted")
        try:
            logger.debug("Reloading network_object: {}".format(network_object))
            network_object.reload()
        except NotFound:
            logger.debug("Got NotFound Exception, Network is deleted")
            return True

        return False
