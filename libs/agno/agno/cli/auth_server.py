from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

from agno.cli.settings import agno_cli_settings


class CliAuthRequestHandler(BaseHTTPRequestHandler):
    """Request Handler to accept the CLI auth token after the web based auth flow.
    References:
        https://medium.com/@hasinthaindrajee/browser-sso-for-cli-applications-b0be743fa656
        https://gist.github.com/mdonkers/63e115cc0c79b4f6b8b3a6b797e485c7

    TODO:
        * Fix the header and limit to only localhost or agno.com
    """

    def _set_response(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "POST")
        self.end_headers()

    # def do_GET(self):
    #     logger.info("GET request,\nPath: %s\nHeaders:\n%s\n", str(self.path), str(self.headers))
    #     self._set_response()
    #     self.wfile.write("GET request for {}".format(self.path).encode('utf-8'))

    def do_OPTIONS(self):
        # logger.debug(
        #     "OPTIONS request,\nPath: %s\nHeaders:\n%s\n",
        #     str(self.path),
        #     str(self.headers),
        # )
        self._set_response()
        # self.wfile.write("OPTIONS request for {}".format(self.path).encode('utf-8'))

    def do_POST(self):
        content_length = int(self.headers["Content-Length"])  # <--- Gets the size of data
        post_data = self.rfile.read(content_length)  # <--- Gets the data itself
        decoded_post_data = post_data.decode("utf-8")
        # logger.debug(
        #     "POST request,\nPath: {}\nHeaders:\n{}\n\nBody:\n{}\n".format(
        #         str(self.path), str(self.headers), decoded_post_data
        #     )
        # )
        # logger.debug("Data: {}".format(decoded_post_data))
        # logger.info("type: {}".format(type(post_data)))
        agno_cli_settings.tmp_token_path.parent.mkdir(parents=True, exist_ok=True)
        agno_cli_settings.tmp_token_path.touch(exist_ok=True)
        agno_cli_settings.tmp_token_path.write_text(decoded_post_data)
        # TODO: Add checks before shutting down the server
        self.server.running = False  # type: ignore
        self._set_response()

    def log_message(self, format, *args):
        pass


class CliAuthServer:
    """
    Source: https://stackoverflow.com/a/38196725/10953921
    """

    def __init__(self, port: int = 9191):
        import threading

        self._server = HTTPServer(("", port), CliAuthRequestHandler)
        self._thread = threading.Thread(target=self.run)
        self._thread.daemon = True
        self._server.running = False  # type: ignore

    def run(self):
        self._server.running = True  # type: ignore
        while self._server.running:  # type: ignore
            self._server.handle_request()

    def start(self):
        self._thread.start()

    def shut_down(self):
        self._thread.close()  # type: ignore


def check_port(port: int):
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            return s.connect_ex(("localhost", port)) == 0
        except Exception as e:
            print(f"Error occurred: {e}")
            return False


def get_port_for_auth_server():
    starting_port = 9191
    for port in range(starting_port, starting_port + 100):
        if not check_port(port):
            return port


def get_auth_token_from_web_flow(port: int) -> Optional[str]:
    """
    GET request: curl http://localhost:9191
    POST request: curl -d "foo=bar&bin=baz" http://localhost:9191
    """
    import json

    server = CliAuthServer(port)
    server.run()

    if agno_cli_settings.tmp_token_path.exists() and agno_cli_settings.tmp_token_path.is_file():
        auth_token_str = agno_cli_settings.tmp_token_path.read_text()
        auth_token_json = json.loads(auth_token_str)
        agno_cli_settings.tmp_token_path.unlink()
        return auth_token_json.get("AuthToken", None)
    return None
