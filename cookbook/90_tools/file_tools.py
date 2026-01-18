"""
File Tools - File System Operations and Management

This example demonstrates how to use FileTools for file operations.
Shows enable_ flag patterns for selective function access.
FileTools is a small tool (<6 functions) so it uses enable_ flags.
"""

from pathlib import Path

from agno.agent import Agent
from agno.tools.file import FileTools

# Example 1: All functions enabled (default behavior)
agent_full = Agent(
    tools=[
        FileTools(Path("tmp/file"))
    ],  # All functions enabled by default, except file deletion
    description="You are a comprehensive file management assistant with all file operation capabilities.",
    instructions=[
        "Help users with all file operations including read, write, search, and management",
        "Create, modify, and organize files and directories",
        "Provide clear feedback on file operations",
        "Ensure file paths and operations are valid",
    ],
    markdown=True,
)

# Example 2: Enable only file reading and searching
agent_readonly = Agent(
    tools=[
        FileTools(
            Path("tmp/file"),
            enable_read_file=True,
            enable_search_files=True,
            enable_list_files=True,
        )
    ],
    description="You are a file reader focused on accessing and searching existing files.",
    instructions=[
        "Read and search through existing files",
        "List file contents and directory structures",
        "Cannot create, modify, or delete files",
        "Focus on information retrieval and file exploration",
    ],
    markdown=True,
)

# Example 3: Enable all functions using 'all=True' pattern
agent_comprehensive = Agent(
    tools=[FileTools(Path("tmp/file"), all=True)],
    description="You are a full-featured file system manager with all capabilities enabled.",
    instructions=[
        "Perform comprehensive file system operations",
        "Manage complete file lifecycles including creation, modification, and deletion",
        "Support advanced file organization and processing workflows",
        "Provide end-to-end file management solutions",
    ],
    markdown=True,
)

# Example 4: Write-only operations (for content creation)
agent_writer = Agent(
    tools=[
        FileTools(
            Path("tmp/file"),
            enable_save_file=True,
            enable_read_file=False,  # Disable file reading
            enable_read_file_chunk=False,  # Disable reading in chunks as well
            enable_search_files=False,  # Disable file searching
        )
    ],
    description="You are a content creator focused on writing and organizing new files.",
    instructions=[
        "Create new files and directories",
        "Generate and save content to files",
        "Cannot read existing files or search directories",
        "Focus on content creation and file organization",
    ],
    markdown=True,
)

# Example usage
print("=== Full File Management Example ===")
agent_full.print_response(
    "What is the most advanced LLM currently? Save the answer to a file.", markdown=True
)

print("\n=== Read-Only File Operations Example ===")
agent_readonly.print_response(
    "Search for all files in the directory and list their names and sizes",
    markdown=True,
)

print("\n=== File Writing Example ===")
agent_writer.print_response(
    "Create a summary of Python best practices and save it to 'python_guide.txt'",
    markdown=True,
)

print("\n=== File Search Example ===")
agent_full.print_response(
    "Search for all files which have an extension '.txt' and save the answer to a new file named 'all_txt_files.txt'",
    markdown=True,
)
