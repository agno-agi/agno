import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional
from urllib.parse import parse_qs, quote, urlparse

from agno.cli.settings import agno_cli_settings


class CliAuthRequestHandler(BaseHTTPRequestHandler):
    """Request Handler to accept the CLI auth token after the web based auth flow.
    References:
        https://medium.com/@hasinthaindrajee/browser-sso-for-cli-applications-b0be743fa656
        https://gist.github.com/mdonkers/63e115cc0c79b4f6b8b3a6b797e485c7

    TODO:
        * Fix the header and limit to only localhost or agno.com
    """

    def _redirect_with_status(self, theme: str, redirect_uri, result: str, error_type: str = ""):
        """Render a simple HTML page with 'Authenticating...' and redirect with a loader."""
        redirect_url = f"{redirect_uri}?cli_auth={result}"
        if result == "error" and error_type:
            redirect_url += f"&type={quote(error_type)}"

        if theme == "dark":
            background_color = "#111113"
            text_color_large = "#FAFAFA"
            text_color_small = "#A1A1AA"
            loader_color = "#FAFAFA"
            auth_svg_link = "https://agno-public.s3.us-east-1.amazonaws.com/assets/Auth-darkmode.svg"
        else:
            background_color = "#FFFFFF"
            text_color_large = "#18181B"
            text_color_small = "rgba(113, 113, 122, 1)"
            loader_color = "#18181B"
            auth_svg_link = "https://agno-public.s3.us-east-1.amazonaws.com/assets/Auth-lightmode.svg"

        html = f"""
        <html>
        <head>
            <title>Agno Workspace</title>
            <meta http-equiv="refresh" content="1;url={redirect_url}" />
            <style>
                @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap');
                body {{
                    font-family: 'Inter', sans-serif;
                    display: flex;
                    align-items: center;
                    flex-direction: column;
                    height: 100vh;
                    width: 100vw;
                    margin: 0;
                    background-color: {background_color};
                    position: relative;
                    overflow: hidden;
                }}
                .container {{
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    text-align: center;
                    gap: 12px;
                    z-index: 1;
                    margin-top: 120px;
                }}
                .message-large {{
                    font-weight: 500;
                    font-size: 26px;
                    line-height: 100%;
                    letter-spacing: -0.02em;
                    text-align: center;
                    vertical-align: middle;
                    color: {text_color_large};
                }}
                .message-small {{
                    font-weight: 400;
                    font-size: 14px;
                    line-height: 150%;
                    letter-spacing: -0.02em;
                    text-align: center;
                    vertical-align: middle;
                    color: {text_color_small};
                }}
                .loader {{
                    width: 12px;
                    height: 12px;
                    border: 1px solid rgba(24, 24, 27, 0.2);
                    border-top-color: {loader_color};
                    border-radius: 50%;
                    animation: spin 0.8s linear infinite;
                    margin-bottom: 12px;
                }}
                .bottom-image {{
                    position: absolute;
                    bottom: 0;
                    left: 0;
                    right: 0;
                    width: 100%;
                    max-height: 50vh;
                    z-index: 0;
                }}
                @keyframes spin {{
                    0% {{ transform: rotate(0deg); }}
                    100% {{ transform: rotate(360deg); }}
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="loader"></div>
                <div class="message-large">Authenticating your workspace...</div>
                <div class="message-small">You will be redirected shortly.</div>
            </div>
            <img src={auth_svg_link} class="bottom-image" alt="Background Image" />
        </body>
        </html>
        """

        self._set_html_response(html, status_code=200)
        self.server.running = False  # type: ignore

    def _set_response(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "POST")
        self.end_headers()

    def _set_html_response(self, html_content: str, status_code: int = 200):
        """Set the response headers and content type to HTML."""
        self.send_response(status_code)
        self.send_header("Content-type", "text/html")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.end_headers()
        self.wfile.write(html_content.encode("utf-8"))

    def _store_token(self, auth_token: str):
        """Store the given token in a temporary file."""
        agno_cli_settings.tmp_token_path.parent.mkdir(parents=True, exist_ok=True)
        agno_cli_settings.tmp_token_path.touch(exist_ok=True)
        agno_cli_settings.tmp_token_path.write_text(json.dumps({"AuthToken": auth_token}))

    def do_GET(self):
        """Redirect to the provided redirect_uri after storing the auth token."""
        parsed_url = urlparse(self.path)
        query_params = parse_qs(parsed_url.query)
        auth_token = query_params.get("token", [""])[0]
        redirect_uri = query_params.get("redirect_uri", [""])[0]
        theme = query_params.get("theme", ["light"])[0]

        if not redirect_uri:
            self._set_html_response("<h2>Missing redirect_uri</h2>", status_code=400)
            return

        self._store_token(auth_token)
        self._redirect_with_status(theme, redirect_uri, "success")

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

    server = CliAuthServer(port)
    server.run()

    if agno_cli_settings.tmp_token_path.exists() and agno_cli_settings.tmp_token_path.is_file():
        auth_token_str = agno_cli_settings.tmp_token_path.read_text()
        auth_token_json = json.loads(auth_token_str)
        agno_cli_settings.tmp_token_path.unlink()
        return auth_token_json.get("AuthToken", None)
    return None
