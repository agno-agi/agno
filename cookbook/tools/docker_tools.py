import sys

from agno.agent import Agent

try:
    from agno.tools.docker import DockerTools

    docker_tools = DockerTools(
        enable_container_management=True,
        enable_image_management=True,
        enable_volume_management=True,
        enable_network_management=True,
    )

    # Create an agent with Docker tools
    docker_agent = Agent(
        name="Docker Agent",
        instructions=[
            "You are a Docker management assistant that can perform various Docker operations.",
            "You can manage containers, images, volumes, and networks.",
        ],
        tools=[docker_tools],
        show_tool_calls=True,
        markdown=True,
    )

    # Example 1: List running containers
    docker_agent.print_response("List all running Docker containers", stream=True)

    # Example 2: List all images
    docker_agent.print_response("List all Docker images on this system", stream=True)

    # Example 3: Pull an image
    docker_agent.print_response("Pull the latest nginx image", stream=True)

    # Example 4: Run a container
    docker_agent.print_response(
        "Run an nginx container named 'web-server' on port 8080", stream=True
    )

    # Example 5: Get container logs
    docker_agent.print_response("Get logs from the 'web-server' container", stream=True)

    # # Example 6: List volumes
    docker_agent.print_response("List all Docker volumes", stream=True)

    # Example 7: Create a network
    docker_agent.print_response(
        "Create a new Docker network called 'test-network'", stream=True
    )

    # Example 8: Stop and remove container
    docker_agent.print_response(
        "Stop and remove the 'web-server' container", stream=True
    )

    # Example 9: Inspect an image
    docker_agent.print_response("Inspect the nginx image", stream=True)

    # # Example 10: Build an image (uncomment and modify path as needed)
    # docker_agent.print_response(
    #     "Build a Docker image from the Dockerfile in ./app with tag 'myapp:latest'",
    #     stream=True
    # )

except ValueError as e:
    print(f"\n❌ Docker Tool Error: {e}")
    print("\n🔍 Troubleshooting steps:")

    if sys.platform == "darwin":  # macOS
        print("1. Ensure Docker Desktop is running")
        print("2. Check Docker Desktop settings")
        print("3. Try running 'docker ps' in terminal to verify access")

    elif sys.platform == "linux":
        print("1. Check if Docker service is running:")
        print("   systemctl status docker")
        print("2. Make sure your user has permissions to access Docker:")
        print("   sudo usermod -aG docker $USER")

    elif sys.platform == "win32":
        print("1. Ensure Docker Desktop is running")
        print("2. Check Docker Desktop settings")
