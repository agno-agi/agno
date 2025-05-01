from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from typing import Optional
from agno.cli.settings import agno_cli_settings
from agno.cli.popup import (
    get_success_page,
    get_no_cookies_error_page,
    get_no_auth_token_error_page,
    get_loading_page

)


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
    
    def _set_html_response(self, html_content: str, status_code: int = 200):
        """Set the response headers and content type to HTML."""
        self.send_response(status_code)
        self.send_header("Content-type", "text/html")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.end_headers()
        self.wfile.write(html_content.encode("utf-8"))

    
    
    def do_GET(self):
        """Handle the redirect from the browser with auth cookies."""
        
        # If path contains success or error parameters, show appropriate page
        if "?result=success" in self.path:
            self._set_html_response(get_success_page(), status_code=200)
            # Shutdown server after showing success
            self.server.running = False
            return
        elif "?result=error" in self.path:
            error_type = self.path.split("error_type=")[1].split("&")[0] if "error_type=" in self.path else ""
            if error_type == "no_cookies":
                self._set_html_response(get_no_cookies_error_page(), status_code=400)
            else:
                self._set_html_response(get_no_auth_token_error_page(), status_code=400)
            return
        
        # Extract cookies from the request when processing
        cookies_header = self.headers.get('Cookie')
        
        # If no cookies, redirect to error page
        if not cookies_header:
            # First show loading page
            self._show_loading_with_redirect("?result=error&error_type=no_cookies")
            return
            
        # Parse cookies - find the session or auth cookie
        cookies = {}
        for cookie in cookies_header.split(';'):
            if '=' in cookie:
                name, value = cookie.strip().split('=', 1)
                cookies[name] = value
        
        # Find your specific session cookie
        auth_token = cookies.get('__agno_session')
        
        if not auth_token:
            # First show loading page
            self._show_loading_with_redirect("?result=error&error_type=no_token")
            return
        
        # Save the auth token
        agno_cli_settings.tmp_token_path.parent.mkdir(parents=True, exist_ok=True)
        agno_cli_settings.tmp_token_path.touch(exist_ok=True)
        agno_cli_settings.tmp_token_path.write_text(json.dumps({"AuthToken": auth_token}))
        
        # Show loading page first, then redirect to success page
        self._show_loading_with_redirect("?result=success")
    
    def _show_loading_with_redirect(self, redirect_params):
        """Show loading page with auto-redirect after delay."""
        html=get_loading_page(redirect_params)

        self._set_html_response(html, status_code=200) 

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