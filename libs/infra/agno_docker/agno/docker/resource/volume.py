from typing import Any, Dict, List, Optional

from agno.docker.api_client import DockerApiClient
from agno.docker.resource.base import DockerResource
from agno.utils.log import logger


class DockerVolume(DockerResource):
    resource_type: str = "Volume"

    # driver (str) – Name of the driver used to create the volume
    driver: Optional[str] = None
    # driver_opts (dict) – Driver options as a key-value dictionary
    driver_opts: Optional[Dict[str, Any]] = None
    # labels (dict) – Labels to set on the volume
    labels: Optional[Dict[str, Any]] = None

    def _create(self, docker_client: DockerApiClient) -> bool:
        """Creates the Volume on docker

        Args:
            docker_client: The DockerApiClient for the current cluster
        """
        from docker import DockerClient
        from docker.models.volumes import Volume

        logger.debug("Creating: {}".format(self.get_resource_name()))
        volume_name: Optional[str] = self.name
        volume_object: Optional[Volume] = None

        try:
            _api_client: DockerClient = docker_client.api_client
            volume_object = _api_client.volumes.create(
                name=volume_name,
                driver=self.driver,
                driver_opts=self.driver_opts,
                labels=self.labels,
            )
            if volume_object is not None:
                logger.debug("Volume Created: {}".format(volume_object.name))
            else:
                logger.debug("Volume could not be created")
            # logger.debug("Volume {}".format(volume_object.attrs))
        except Exception:
            raise

        # By this step the volume should be created
        # Get the data from the volume object
        logger.debug("Validating volume is created")
        if volume_object is not None:
            _id: str = volume_object.id
            _short_id: str = volume_object.short_id
            _name: str = volume_object.name
            _attrs: str = volume_object.attrs
            if _id:
                logger.debug("_id: {}".format(_id))
                self.id = _id
            if _short_id:
                logger.debug("_short_id: {}".format(_short_id))
                self.short_id = _short_id
            if _name:
                logger.debug("_name: {}".format(_name))
            if _attrs:
                logger.debug("_attrs: {}".format(_attrs))
                # TODO: use json_to_dict(_attrs)
                self.attrs = _attrs  # type: ignore

            # TODO: Validate that the volume object is created properly
            self.active_resource = volume_object
            return True
        return False

    def _read(self, docker_client: DockerApiClient) -> Any:
        """Returns a Volume object if the volume is active on the docker_client"""
        from docker import DockerClient
        from docker.models.volumes import Volume

        logger.debug("Reading: {}".format(self.get_resource_name()))
        volume_name: Optional[str] = self.name

        try:
            _api_client: DockerClient = docker_client.api_client
            volume_list: Optional[List[Volume]] = _api_client.volumes.list()
            # logger.debug("volume_list: {}".format(volume_list))
            if volume_list is not None:
                for volume in volume_list:
                    if volume.name == volume_name:
                        logger.debug(f"Volume {volume_name} exists")
                        self.active_resource = volume

                        return volume
        except Exception:
            logger.debug(f"Volume {volume_name} not found")

        return None

    def _delete(self, docker_client: DockerApiClient) -> bool:
        """Deletes the Volume on docker

        Args:
            docker_client: The DockerApiClient for the current cluster
        """
        from docker.errors import NotFound
        from docker.models.volumes import Volume

        logger.debug("Deleting: {}".format(self.get_resource_name()))
        volume_object: Optional[Volume] = self._read(docker_client)
        # Return True if there is no Volume to delete
        if volume_object is None:
            return True

        # Delete Volume
        try:
            self.active_resource = None
            volume_object.remove(force=True)
        except Exception as e:
            logger.exception("Error while deleting volume: {}".format(e))

        # Validate that the volume is deleted
        logger.debug("Validating volume is deleted")
        try:
            logger.debug("Reloading volume_object: {}".format(volume_object))
            volume_object.reload()
        except NotFound:
            logger.debug("Got NotFound Exception, Volume is deleted")
            return True

        return False
