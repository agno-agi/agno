"""
Unified load balancer resource for multi-cloud deployments.

This module provides a consistent interface for managing load balancers
across AWS ELB, GCP Load Balancing, Azure Load Balancer, and other providers.
"""

from typing import Any, ClassVar, Dict, List, Optional

from agno.base.unified import UnifiedResource
from agno.cli.console import print_info
from agno.utilities.logging import logger

try:
    from libcloud.loadbalancer.base import DEFAULT_ALGORITHM, Algorithm, LoadBalancer, Member
    from libcloud.loadbalancer.providers import get_driver as get_lb_driver
    from libcloud.loadbalancer.types import Provider as LBProvider

    LIBCLOUD_AVAILABLE = True
except ImportError:
    LIBCLOUD_AVAILABLE = False


class UnifiedLoadBalancer(UnifiedResource):
    """
    Unified load balancer resource across cloud providers.

    This provides consistent load balancer management across AWS ELB/ALB,
    GCP Load Balancing, Azure Load Balancer, and more.

    Attributes:
        protocol: Protocol (http, https, tcp, udp)
        port: Port to balance
        algorithm: Load balancing algorithm (round_robin, least_connections, etc.)
        health_check_path: Path for health checks
        health_check_interval: Health check interval in seconds
        targets: List of target instances/IPs
        ssl_certificate: SSL certificate for HTTPS

    Example:
        # Create load balancer on any provider
        lb = UnifiedLoadBalancer(
            name="my-app-lb",
            provider="aws",
            protocol="http",
            port=80,
            algorithm="round_robin",
            targets=["instance-1", "instance-2"]
        )
        lb.create()
    """

    resource_type: str = "UnifiedLoadBalancer"
    resource_type_list: List[str] = ["loadbalancer", "lb", "elb", "alb"]

    # Load balancer configuration
    protocol: str = "http"  # Protocol: http, https, tcp, udp
    port: int = 80  # Port to balance
    algorithm: str = "round_robin"  # Load balancing algorithm
    health_check_path: str = "/"  # Health check path (for HTTP/HTTPS)
    health_check_interval: int = 30  # Health check interval in seconds
    health_check_timeout: int = 5  # Health check timeout
    healthy_threshold: int = 2  # Consecutive successes for healthy
    unhealthy_threshold: int = 2  # Consecutive failures for unhealthy

    # Targets
    targets: Optional[List[str]] = None  # List of instance IDs or IPs
    target_port: Optional[int] = None  # Port on targets (defaults to port)

    # SSL configuration
    ssl_certificate: Optional[str] = None  # SSL certificate for HTTPS

    # Provider-specific
    internal: bool = False  # Internal (private) vs external (public) LB
    availability_zones: Optional[List[str]] = None  # AZs to deploy to

    # Cached LB driver
    lb_driver: Optional[Any] = None

    # Algorithm mapping
    ALGORITHM_MAP: ClassVar[Dict[str, str]] = {
        "round_robin": "ROUND_ROBIN",
        "least_connections": "LEAST_CONNECTIONS",
        "least_conn": "LEAST_CONNECTIONS",
        "random": "RANDOM",
        "source_ip": "SOURCE_IP",
        "weighted_round_robin": "WEIGHTED_ROUND_ROBIN",
    }

    def get_lb_driver(self) -> Optional[Any]:
        """Get or create load balancer driver for this provider."""
        if self.lb_driver is not None:
            return self.lb_driver

        if not LIBCLOUD_AVAILABLE:
            logger.error("Apache Libcloud not installed")
            return None

        try:
            # Map provider name to Libcloud LB provider
            provider_map = {
                "aws": "ELB",
                "gcp": "GCE",
                "azure": "AZURE",
                "rackspace": "RACKSPACE",
                "cloudstack": "CLOUDSTACK",
                "dimensiondata": "DIMENSIONDATA",
                "aliyun": "ALIYUN_SLB",
            }

            provider_const_name = provider_map.get(self.provider.lower())
            if not provider_const_name:
                logger.error(f"Load balancer not supported for provider: {self.provider}")
                return None

            provider_const = getattr(LBProvider, provider_const_name)
            driver_class = get_lb_driver(provider_const)

            # Get credentials
            credentials = self._get_provider_credentials()

            # Initialize driver
            self.lb_driver = driver_class(**credentials)
            return self.lb_driver

        except Exception as e:
            logger.error(f"Failed to initialize LB driver: {e}")
            return None

    def _get_algorithm(self) -> str:
        """Get Libcloud algorithm constant."""
        algo = self.ALGORITHM_MAP.get(self.algorithm.lower(), self.algorithm.upper())
        return algo

    def _read(self, driver: Any) -> Optional[LoadBalancer]:
        """Read load balancer from cloud provider."""
        logger.debug(f"Reading load balancer: {self.name}")

        try:
            balancers = driver.list_balancers()

            for lb in balancers:
                if lb.name == self.name:
                    logger.info(f"Found load balancer: {lb.name} (ID: {lb.id})")
                    self.active_resource = lb
                    return lb

            logger.debug(f"Load balancer {self.name} not found")
            return None

        except Exception as e:
            logger.error(f"Failed to read load balancer: {e}")
            return None

    def _create(self, driver: Any) -> bool:
        """Create load balancer on cloud provider."""
        print_info(f"Creating {self.get_resource_type()}: {self.name}")

        try:
            # Get algorithm
            algorithm = self._get_algorithm()

            # Build creation parameters
            create_params: Dict[str, Any] = {
                "name": self.name,
                "port": self.port,
                "protocol": self.protocol.upper(),
                "algorithm": algorithm,
            }

            # Add members (targets) if specified
            if self.targets:
                members = []
                target_port = self.target_port or self.port

                for target in self.targets:
                    # Create member
                    member = Member(id=target, ip=target, port=target_port)
                    members.append(member)

                create_params["members"] = members

            # Create load balancer
            logger.debug(f"Creating load balancer with params: {list(create_params.keys())}")
            lb = driver.create_balancer(**create_params)

            if lb:
                logger.info(f"Load balancer created: {lb.name} (ID: {lb.id})")
                self.active_resource = lb
                return True
            else:
                logger.error("Failed to create load balancer: no LB returned")
                return False

        except Exception as e:
            logger.error(f"Failed to create load balancer: {e}")
            import traceback

            logger.debug(traceback.format_exc())
            return False

    def _update(self, driver: Any) -> bool:
        """Update load balancer configuration."""
        logger.warning("Load balancer update operations are limited in Libcloud")
        return True

    def _delete(self, driver: Any) -> bool:
        """Delete load balancer from cloud provider."""
        print_info(f"Deleting {self.get_resource_type()}: {self.name}")

        try:
            lb = self.active_resource or self._read(driver)

            if not lb:
                logger.error(f"Load balancer {self.name} not found")
                return False

            # Delete load balancer
            result = driver.destroy_balancer(lb)

            if result:
                logger.info(f"Load balancer deleted: {self.name}")
                self.active_resource = None
                return True
            else:
                logger.error("Failed to delete load balancer")
                return False

        except Exception as e:
            logger.error(f"Failed to delete load balancer: {e}")
            return False

    def read(self, client: Any = None) -> Any:
        """Read load balancer using LB driver."""
        if self.use_cache and self.active_resource is not None:
            return self.active_resource

        if self.skip_read:
            print_info(f"Skipping read: {self.name}")
            return True

        driver = client or self.get_lb_driver()
        if driver is None:
            logger.error(f"Failed to get LB driver for {self.name}")
            return None

        return self._read(driver)

    def create(self, client: Any = None) -> bool:
        """Create load balancer using LB driver."""
        if self.skip_create:
            print_info(f"Skipping create: {self.name}")
            return True

        driver = client or self.get_lb_driver()
        if driver is None:
            logger.error(f"Failed to get LB driver for {self.name}")
            return False

        # Check if already exists
        if self.use_cache and self.is_active(driver):
            self.resource_created = True
            print_info(f"{self.get_resource_type()}: {self.name} already exists")
        else:
            self.resource_created = self._create(driver)
            if self.resource_created:
                print_info(f"{self.get_resource_type()}: {self.name} created")

        if self.resource_created:
            if self.save_output:
                self.save_output_file()
            return self.post_create(driver)

        logger.error(f"Failed to create {self.get_resource_type()}: {self.name}")
        return False

    def delete(self, client: Any = None) -> bool:
        """Delete load balancer using LB driver."""
        if self.skip_delete:
            print_info(f"Skipping delete: {self.name}")
            return True

        driver = client or self.get_lb_driver()
        if driver is None:
            logger.error(f"Failed to get LB driver for {self.name}")
            return False

        if not self.is_active(driver):
            print_info(f"{self.get_resource_type()}: {self.name} does not exist")
            return True

        self.resource_deleted = self._delete(driver)

        if self.resource_deleted:
            print_info(f"{self.get_resource_type()}: {self.name} deleted")
            if self.save_output:
                self.delete_output_file()
            return self.post_delete(driver)

        logger.error(f"Failed to delete {self.get_resource_type()}: {self.name}")
        return False

    def is_active(self, client: Any = None) -> bool:
        """Check if load balancer exists."""
        resource = self.read(client)
        return resource is not None

    def add_target(self, target_id: str, target_ip: Optional[str] = None, port: Optional[int] = None) -> bool:
        """
        Add a target instance to the load balancer.

        Args:
            target_id: Instance ID
            target_ip: Instance IP (optional, will be looked up)
            port: Target port (optional, uses LB port by default)

        Returns:
            True if target added successfully
        """
        driver = self.get_lb_driver()
        if not driver:
            return False

        print_info(f"Adding target {target_id} to load balancer {self.name}")

        try:
            lb = self.active_resource or self._read(driver)

            if not lb:
                logger.error(f"Load balancer {self.name} not found")
                return False

            # Create member
            target_port = port or self.target_port or self.port
            ip = target_ip or target_id  # Use ID as IP if IP not provided

            member = Member(id=target_id, ip=ip, port=target_port)

            # Attach member
            result = driver.balancer_attach_member(lb, member)

            if result:
                logger.info(f"Target added: {target_id}")
                return True
            else:
                logger.error("Failed to add target")
                return False

        except Exception as e:
            logger.error(f"Failed to add target: {e}")
            return False

    def remove_target(self, target_id: str) -> bool:
        """
        Remove a target instance from the load balancer.

        Args:
            target_id: Instance ID

        Returns:
            True if target removed successfully
        """
        driver = self.get_lb_driver()
        if not driver:
            return False

        print_info(f"Removing target {target_id} from load balancer {self.name}")

        try:
            lb = self.active_resource or self._read(driver)

            if not lb:
                logger.error(f"Load balancer {self.name} not found")
                return False

            # Find member
            members = driver.balancer_list_members(lb)
            member = None
            for m in members:
                if m.id == target_id:
                    member = m
                    break

            if not member:
                logger.error(f"Target {target_id} not found in load balancer")
                return False

            # Detach member
            result = driver.balancer_detach_member(lb, member)

            if result:
                logger.info(f"Target removed: {target_id}")
                return True
            else:
                logger.error("Failed to remove target")
                return False

        except Exception as e:
            logger.error(f"Failed to remove target: {e}")
            return False

    def list_targets(self) -> List[Member]:
        """List all targets attached to the load balancer."""
        driver = self.get_lb_driver()
        if not driver:
            return []

        try:
            lb = self.active_resource or self._read(driver)

            if not lb:
                logger.error(f"Load balancer {self.name} not found")
                return []

            members = driver.balancer_list_members(lb)
            return members

        except Exception as e:
            logger.error(f"Failed to list targets: {e}")
            return []

    def get_endpoint(self) -> Optional[str]:
        """Get the load balancer endpoint URL."""
        if self.active_resource:
            # Different providers expose endpoint differently
            if hasattr(self.active_resource, "ip"):
                return f"{self.protocol}://{self.active_resource.ip}:{self.port}"
            elif hasattr(self.active_resource, "extra") and "dnsName" in self.active_resource.extra:
                return f"{self.protocol}://{self.active_resource.extra['dnsName']}:{self.port}"

        return None
