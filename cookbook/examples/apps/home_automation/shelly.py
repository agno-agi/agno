import requests

class Shelly():
    def __init__(self, file_name: str) -> None:
        # config = open(file_name)
        # config_data = json.load(config)
        config_data = {
            "shelly_ip": "192.168.1.224"

        }
        self.device_ip = config_data["shelly_ip"]

    def toggle_on(self):

        PARAMS = {"turn":"on"}
        r = requests.get(url = "http://{}/relay/0".format(self.device_ip), params=PARAMS)
        print(r.json())

    def toggle_off(self):

        PARAMS = {"turn":"off"}
        r = requests.get(url = "http://{}/relay/0".format(self.device_ip), params=PARAMS)
        print(r.json())

    def get_state(self):
        url = "{}/relay/0".format(self.device_ip)
        print("Checking state at", url)
        r = requests.get(url = "http://{}/relay/0".format(self.device_ip))
        print(r.json())