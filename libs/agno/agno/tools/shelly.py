import json
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_info, logger

try:
    import requests
except ImportError:
    raise ImportError("`requests` not installed. Please install using `pip install requests`")


class ShellyTools(Toolkit):
    """
    ShellyTools is a toolkit for controlling Shelly smart home devices.
    
    This toolkit provides methods to control Shelly relay devices, allowing you to:
    - Turn devices on/off
    - Check device status
    - Get device information
    
    Args:
        device_ip (str): IP address of the Shelly device (e.g., "192.168.1.224")
        relay_id (int): Relay ID to control (default: 0)
        timeout (int): Request timeout in seconds (default: 10)
        enable_toggle_on (bool): Enable toggle_on function (default: True)
        enable_toggle_off (bool): Enable toggle_off function (default: True)
        enable_get_state (bool): Enable get_state function (default: True)
        enable_get_status (bool): Enable get_status function (default: True)
        enable_toggle (bool): Enable toggle function (default: True)
        all (bool): Enable all functions (default: False)
    """

    def __init__(
        self,
        device_ip: str,
        relay_id: int = 0,
        timeout: int = 10,
        enable_toggle_on: bool = True,
        enable_toggle_off: bool = True,
        enable_get_state: bool = True,
        enable_get_status: bool = True,
        enable_toggle: bool = True,
        all: bool = False,
        **kwargs,
    ):
        if not device_ip:
            raise ValueError("device_ip is required for ShellyTools")
        
        self.device_ip = device_ip.strip()
        self.relay_id = relay_id
        self.timeout = timeout
        self.base_url = f"http://{self.device_ip}"
        
        # Validate IP format (basic check)
        if not self._is_valid_ip_format(self.device_ip):
            raise ValueError(f"Invalid IP address format: {device_ip}")

        tools: List[Any] = []
        if enable_toggle_on or all:
            tools.append(self.toggle_on)
        if enable_toggle_off or all:
            tools.append(self.toggle_off)
        if enable_get_state or all:
            tools.append(self.get_state)
        if enable_get_status or all:
            tools.append(self.get_status)
        if enable_toggle or all:
            tools.append(self.toggle)

        super().__init__(name="shelly_tools", tools=tools, **kwargs)

    def _is_valid_ip_format(self, ip: str) -> bool:
        """Basic IP address format validation."""
        parts = ip.split('.')
        if len(parts) != 4:
            return False
        try:
            for part in parts:
                num = int(part)
                if not 0 <= num <= 255:
                    return False
            return True
        except ValueError:
            return False

    def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Make a request to the Shelly device.

        Args:
            endpoint (str): The API endpoint (e.g., "/relay/0")
            params (Optional[Dict]): Query parameters for the request

        Returns:
            Dict: The JSON response from the device or error information
        """
        url = f"{self.base_url}{endpoint}"
        
        try:
            log_debug(f"Making request to Shelly device: {url}")
            response = requests.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            
            result = response.json()
            log_debug(f"Shelly response: {result}")
            return result
            
        except requests.exceptions.Timeout:
            error_msg = f"Timeout connecting to Shelly device at {self.device_ip}"
            logger.error(error_msg)
            return {"error": error_msg, "device_ip": self.device_ip}
        except requests.exceptions.ConnectionError:
            error_msg = f"Failed to connect to Shelly device at {self.device_ip}"
            logger.error(error_msg)
            return {"error": error_msg, "device_ip": self.device_ip}
        except requests.exceptions.RequestException as e:
            error_msg = f"Error communicating with Shelly device: {str(e)}"
            logger.error(error_msg)
            return {"error": error_msg, "device_ip": self.device_ip}
        except json.JSONDecodeError:
            error_msg = "Invalid JSON response from Shelly device"
            logger.error(error_msg)
            return {"error": error_msg, "device_ip": self.device_ip}

    def toggle_on(self) -> str:
        """Turn on the Shelly relay.

        Returns:
            str: JSON string containing the operation result and device state
        """
        log_info(f"Turning on Shelly relay {self.relay_id} at {self.device_ip}")
        print(f"Turning on Shelly relay {self.relay_id} at {self.device_ip}")
        params = {"turn": "on"}
        result = self._make_request(f"/relay/{self.relay_id}", params)
        
        if "error" in result:
            return json.dumps({
                "operation": "toggle_on",
                "success": False,
                "error": result["error"],
                "device_ip": self.device_ip,
                "relay_id": self.relay_id
            })
        
        return json.dumps({
            "operation": "toggle_on",
            "success": True,
            "device_ip": self.device_ip,
            "relay_id": self.relay_id,
            "state": result
        })

    def toggle_off(self) -> str:
        """Turn off the Shelly relay.

        Returns:
            str: JSON string containing the operation result and device state
        """
        log_info(f"Turning off Shelly relay {self.relay_id} at {self.device_ip}")
        print(f"Turning off Shelly relay {self.relay_id} at {self.device_ip}")
        params = {"turn": "off"}
        result = self._make_request(f"/relay/{self.relay_id}", params)
        
        if "error" in result:
            return json.dumps({
                "operation": "toggle_off",
                "success": False,
                "error": result["error"],
                "device_ip": self.device_ip,
                "relay_id": self.relay_id
            })
        
        return json.dumps({
            "operation": "toggle_off",
            "success": True,
            "device_ip": self.device_ip,
            "relay_id": self.relay_id,
            "state": result
        })

    def get_state(self) -> str:
        """Get the current state of the Shelly relay.

        Returns:
            str: JSON string containing the current relay state
        """
        log_info(f"Getting state of Shelly relay {self.relay_id} at {self.device_ip}")
        
        result = self._make_request(f"/relay/{self.relay_id}")
        
        if "error" in result:
            return json.dumps({
                "operation": "get_state",
                "success": False,
                "error": result["error"],
                "device_ip": self.device_ip,
                "relay_id": self.relay_id
            })
        
        return json.dumps({
            "operation": "get_state",
            "success": True,
            "device_ip": self.device_ip,
            "relay_id": self.relay_id,
            "state": result
        })

    def get_status(self) -> str:
        """Get comprehensive status information from the Shelly device.

        Returns:
            str: JSON string containing detailed device status
        """
        log_info(f"Getting status of Shelly device at {self.device_ip}")
        
        result = self._make_request("/status")
        
        if "error" in result:
            return json.dumps({
                "operation": "get_status",
                "success": False,
                "error": result["error"],
                "device_ip": self.device_ip
            })
        
        return json.dumps({
            "operation": "get_status",
            "success": True,
            "device_ip": self.device_ip,
            "status": result
        })

    def toggle(self, state: Optional[str] = None) -> str:
        """Toggle the Shelly relay state or set it to a specific state.

        Args:
            state (Optional[str]): Desired state ('on', 'off', or None for toggle)
                                 If None, will toggle to opposite of current state

        Returns:
            str: JSON string containing the operation result and device state
        """
        if state and state.lower() not in ["on", "off"]:
            return json.dumps({
                "operation": "toggle",
                "success": False,
                "error": "State must be 'on', 'off', or None",
                "device_ip": self.device_ip,
                "relay_id": self.relay_id
            })

        log_info(f"Toggling Shelly relay {self.relay_id} at {self.device_ip} to state: {state or 'auto'}")
        
        # If no state specified, get current state and toggle
        if state is None:
            current_state_result = self._make_request(f"/relay/{self.relay_id}")
            if "error" in current_state_result:
                return json.dumps({
                    "operation": "toggle",
                    "success": False,
                    "error": f"Failed to get current state: {current_state_result['error']}",
                    "device_ip": self.device_ip,
                    "relay_id": self.relay_id
                })
            
            # Determine new state based on current state
            is_on = current_state_result.get("ison", False)
            state = "off" if is_on else "on"
        
        params = {"turn": state.lower()}
        result = self._make_request(f"/relay/{self.relay_id}", params)
        
        if "error" in result:
            return json.dumps({
                "operation": "toggle",
                "success": False,
                "error": result["error"],
                "device_ip": self.device_ip,
                "relay_id": self.relay_id
            })
        
        return json.dumps({
            "operation": "toggle",
            "success": True,
            "device_ip": self.device_ip,
            "relay_id": self.relay_id,
            "new_state": state,
            "state": result
        })
