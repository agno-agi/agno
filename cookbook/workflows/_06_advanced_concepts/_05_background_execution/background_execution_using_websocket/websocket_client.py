import asyncio
import json
import sys
from datetime import datetime
from typing import Optional

import websockets
from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.text import Text


class WorkflowWebSocketClient:
    def __init__(
        self,
        server_url: str = "ws://localhost:8000/ws",
        auth_token: Optional[str] = None,
    ):
        self.server_url = server_url
        self.auth_token = auth_token
        self.console = Console()
        self.websocket = None
        self.connection_id = None
        self.events = []
        self.is_running = True
        self.current_step_content = {}  # Track streaming content per step
        self.is_authenticated = False

    def get_event_style(self, event_type: str) -> tuple[str, str]:
        """Get style (emoji, color) for event type"""
        styles = {
            "connected": ("🔌", "cyan"),
            "connection_established": ("🔌", "cyan"),
            "authenticated": ("🔐", "green"),
            "auth_error": ("❌", "red"),
            "auth_required": ("🔒", "yellow"),
            "workflow_starting": ("🚀", "yellow"),
            "workflow_initiated": ("✅", "green"),
            "WorkflowStarted": ("🚀", "blue"),
            "StepStarted": ("⏳", "yellow"),
            "StepCompleted": ("✅", "green"),
            "WorkflowCompleted": ("🎉", "bright_green"),
            "WorkflowError": ("❌", "red"),
            "workflow_error": ("❌", "red"),
            "RunStarted": ("🏁", "blue"),
            "RunContent": ("📝", "white"),
            "RunCompleted": ("🏆", "green"),
            "ToolCallStarted": ("🔧", "magenta"),
            "ToolCallCompleted": ("🔧", "green"),
            "error": ("❌", "red"),
            "pong": ("📡", "dim"),
            "echo": ("📡", "dim"),
        }
        return styles.get(event_type, ("📝", "white"))

    def parse_sse_message(self, message: str) -> Optional[dict]:
        """Parse SSE format message (event: X \n data: {...})"""
        lines = message.strip().split("\n")
        event_type = None
        data = None

        for line in lines:
            if line.startswith("event: "):
                event_type = line[7:].strip()
            elif line.startswith("data: "):
                data_str = line[6:].strip()
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    return None

        if data:
            data["type"] = event_type or data.get("event", "unknown")
            return data
        return None

    def format_event(self, event_data: dict) -> Panel:
        """Format event data into a beautiful panel"""
        event_type = event_data.get("type", event_data.get("event", "unknown"))
        emoji, color = self.get_event_style(event_type)
        timestamp = datetime.now().strftime("%H:%M:%S")

        # Handle streaming content differently
        if event_type == "RunContent":
            return self.format_streaming_content(event_data, emoji, color, timestamp)

        # Build content for other events
        content_lines = []

        # Main message
        message = event_data.get("message", "")
        content = event_data.get("content", "")

        if message:
            content_lines.append(f"[bold]{message}[/bold]")
        elif content and len(content) < 200:
            content_lines.append(f"[bold]{content}[/bold]")
        elif content:
            # For long content, show truncated version
            content_lines.append(f"[bold]{content[:200]}...[/bold]")

        # Additional details
        details = []
        important_fields = [
            "step_name",
            "agent_name",
            "run_id",
            "session_id",
            "step_index",
        ]

        for key in important_fields:
            if key in event_data:
                details.append(f"[dim]{key}:[/dim] {event_data[key]}")

        if details:
            content_lines.extend(details)

        if not content_lines:
            content_lines.append(f"[dim]Event: {event_type}[/dim]")

        content_text = "\n".join(content_lines)

        return Panel(
            content_text,
            title=f"{emoji} [{color}]{event_type}[/{color}] [{timestamp}]",
            border_style=color,
            width=100,
        )

    def format_streaming_content(
        self, event_data: dict, emoji: str, color: str, timestamp: str
    ) -> Optional[Panel]:
        """Handle streaming content with accumulation"""
        step_id = event_data.get("step_id", "unknown")
        step_name = event_data.get("step_name", "unknown")
        agent_name = event_data.get("agent_name", "unknown")
        content = event_data.get("content", "")

        # Accumulate content for this step
        if step_id not in self.current_step_content:
            self.current_step_content[step_id] = {
                "content": "",
                "step_name": step_name,
                "agent_name": agent_name,
                "last_update": timestamp,
            }

        self.current_step_content[step_id]["content"] += content
        self.current_step_content[step_id]["last_update"] = timestamp

        # Only show panels for meaningful content chunks (not single characters)
        if len(content.strip()) > 3 or content.endswith("\n"):
            accumulated_content = self.current_step_content[step_id]["content"]

            # Show last 300 chars if too long
            display_content = accumulated_content
            if len(accumulated_content) > 300:
                display_content = f"...{accumulated_content[-300:]}"

            content_lines = [
                f"[bold]{agent_name}[/bold] → [dim]{step_name}[/dim]",
                f"[white]{display_content}[/white]",
            ]

            return Panel(
                "\n".join(content_lines),
                title=f"{emoji} [{color}]Streaming Content[/{color}] [{timestamp}]",
                border_style=color,
                width=100,
            )

        return None

    async def connect(self):
        """Connect to WebSocket server and authenticate"""
        try:
            self.websocket = await websockets.connect(self.server_url)
            self.console.print(f"🔌 [green]Connected to {self.server_url}[/green]")

            # Auto-authenticate if token provided
            if self.auth_token:
                await self.authenticate()
            else:
                self.console.print(
                    "⚠️  [yellow]No authentication token provided.[/yellow]"
                )
                self.console.print(
                    "💡 [blue]Use 'auth' command to authenticate interactively[/blue]"
                )

            return True
        except Exception as e:
            self.console.print(f"❌ [red]Failed to connect: {e}[/red]")
            return False

    async def authenticate(self, token: str = None):
        """Send authentication token to server"""
        auth_token = token or self.auth_token

        if not auth_token:
            self.console.print("❌ [red]No authentication token available[/red]")
            return False

        auth_message = {"action": "authenticate", "token": auth_token}

        await self.websocket.send(json.dumps(auth_message))
        self.console.print("🔐 [blue]Sent authentication token[/blue]")
        return True

    async def prompt_for_auth(self):
        """Interactively prompt for authentication token"""
        try:
            token = await asyncio.get_event_loop().run_in_executor(
                None, lambda: input("🔐 Enter authentication token: ").strip()
            )

            if token:
                self.auth_token = token
                return await self.authenticate(token)
            else:
                self.console.print("❌ [red]No token provided[/red]")
                return False
        except Exception as e:
            self.console.print(f"❌ [red]Error getting token: {e}[/red]")
            return False

    async def disconnect(self):
        """Disconnect from WebSocket server"""
        if self.websocket:
            await self.websocket.close()
            self.console.print("🔌 [yellow]Disconnected from server[/yellow]")

    async def send_message(self, message_data: dict):
        """Send message to WebSocket server"""
        if self.websocket:
            await self.websocket.send(json.dumps(message_data))

    async def listen_for_events(self):
        """Listen for events from WebSocket server"""
        try:
            async for message in self.websocket:
                if not self.is_running:
                    break

                try:
                    # Try parsing as pure JSON first
                    event_data = json.loads(message)
                    self.events.append(event_data)

                    # Display event immediately
                    panel = self.format_event(event_data)
                    if panel:
                        self.console.print(panel)

                    # Store connection ID and authentication status
                    if (
                        event_data.get("event") == "connected"
                        or event_data.get("type") == "connection_established"
                    ):
                        self.connection_id = event_data.get("connection_id")
                    elif event_data.get("event") == "authenticated":
                        self.is_authenticated = True
                        self.console.print(
                            "✅ [green]Authentication successful![/green]"
                        )
                    elif event_data.get("event") == "auth_error":
                        self.console.print(
                            f"❌ [red]Authentication failed: {event_data.get('error')}[/red]"
                        )
                    elif event_data.get("event") == "auth_required":
                        self.console.print(
                            f"🔒 [yellow]Authentication required: {event_data.get('error')}[/yellow]"
                        )

                except json.JSONDecodeError:
                    # Try parsing as SSE format
                    event_data = self.parse_sse_message(message)
                    if event_data:
                        self.events.append(event_data)

                        # Display event immediately
                        panel = self.format_event(event_data)
                        if panel:
                            self.console.print(panel)
                    else:
                        # Only show error for very short messages (real errors)
                        if len(message) < 100:
                            self.console.print(
                                f"❌ [red]Could not parse message: {message[:50]}...[/red]"
                            )

        except websockets.exceptions.ConnectionClosed:
            self.console.print("🔌 [yellow]WebSocket connection closed[/yellow]")
        except Exception as e:
            self.console.print(f"❌ [red]Error listening for events: {e}[/red]")

    async def start_workflow(
        self, workflow_message: str, session_id: Optional[str] = None
    ):
        """Start a workflow via WebSocket"""
        if not self.is_authenticated and self.auth_token:
            self.console.print(
                "❌ [red]Not authenticated. Please authenticate first.[/red]"
            )
            return

        if not session_id:
            session_id = f"cli-session-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        message_data = {
            "type": "start-workflow",
            "message": workflow_message,
            "session_id": session_id,
        }

        self.console.print(
            f"🚀 [blue]Starting workflow with message:[/blue] [bold]{workflow_message}[/bold]"
        )
        await self.send_message(message_data)

    async def ping_server(self):
        """Send ping to server"""
        await self.send_message({"action": "ping"})

    def print_banner(self):
        """Print application banner"""
        banner = Text("🚀 Agno Workflow WebSocket Client", style="bold blue")
        self.console.print(Align.center(banner))
        self.console.print(Align.center(f"Connected to: {self.server_url}"))
        self.console.print()

    async def run_interactive(self):
        """Run interactive mode"""
        if not await self.connect():
            return

        self.print_banner()

        # Start listening for events in background
        listen_task = asyncio.create_task(self.listen_for_events())

        self.console.print("[green]Interactive mode started. Type commands:[/green]")
        self.console.print("  [bold]auth[/bold] - Authenticate with token")
        self.console.print("  [bold]start <message>[/bold] - Start workflow")
        self.console.print("  [bold]ping[/bold] - Ping server")
        self.console.print("  [bold]quit[/bold] - Exit")

        # Prominent auth message if not authenticated
        if not self.is_authenticated:
            if not self.auth_token:
                self.console.print()
                self.console.print(
                    "🔒 [yellow bold]AUTHENTICATION REQUIRED[/yellow bold]"
                )
                self.console.print(
                    "   [yellow]Type 'auth' to authenticate with your token[/yellow]"
                )
            else:
                self.console.print(
                    "   [yellow]⚠️  Waiting for authentication...[/yellow]"
                )
        self.console.print()

        try:
            while self.is_running:
                try:
                    # Get user input
                    user_input = await asyncio.get_event_loop().run_in_executor(
                        None, input, "💬 Enter command: "
                    )

                    if user_input.lower() in ["quit", "exit", "q"]:
                        self.is_running = False
                        break
                    elif user_input.lower() == "auth":
                        await self.prompt_for_auth()
                    elif user_input.lower() == "ping":
                        if not self.is_authenticated:
                            self.console.print(
                                "❌ [red]Not authenticated. Use 'auth' command first.[/red]"
                            )
                            continue
                        await self.ping_server()
                    elif user_input.lower().startswith("start "):
                        workflow_message = user_input[6:].strip()
                        if workflow_message:
                            await self.start_workflow(workflow_message)
                        else:
                            self.console.print(
                                "❌ [red]Please provide a message for the workflow[/red]"
                            )
                    else:
                        self.console.print(
                            "❌ [red]Unknown command. Use 'auth', 'start <message>', 'ping', or 'quit'[/red]"
                        )

                except KeyboardInterrupt:
                    self.is_running = False
                    break
                except Exception as e:
                    self.console.print(f"❌ [red]Error: {e}[/red]")

        finally:
            self.is_running = False
            listen_task.cancel()
            await self.disconnect()

    async def run_with_message(self, message: str):
        """Run with a single message and listen for events"""
        if not await self.connect():
            return

        self.print_banner()

        # Start listening for events in background
        listen_task = asyncio.create_task(self.listen_for_events())

        # Start workflow
        await self.start_workflow(message)

        # Wait for workflow to complete or timeout
        try:
            self.console.print(
                "⏳ [yellow]Listening for workflow events... (Press Ctrl+C to stop)[/yellow]"
            )
            await listen_task
        except KeyboardInterrupt:
            self.console.print("\n⏹️ [yellow]Stopping...[/yellow]")
            self.is_running = False
            listen_task.cancel()
            await self.disconnect()


async def main():
    """Main CLI function"""
    import argparse

    parser = argparse.ArgumentParser(description="Agno Workflow WebSocket Client")
    parser.add_argument(
        "--server", default="ws://localhost:8000/ws", help="WebSocket server URL"
    )
    parser.add_argument("--message", "-m", help="Workflow message to send")
    parser.add_argument(
        "--interactive", "-i", action="store_true", help="Run in interactive mode"
    )
    parser.add_argument(
        "--token",
        "-t",
        help="Authentication bearer token (or set SECURITY_KEY env var)",
    )

    args = parser.parse_args()

    # Get token from args or environment variable
    import os

    auth_token = args.token or os.getenv("SECURITY_KEY")

    client = WorkflowWebSocketClient(args.server, auth_token)

    if args.interactive or not args.message:
        await client.run_interactive()
    else:
        await client.run_with_message(args.message)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
        sys.exit(0)
