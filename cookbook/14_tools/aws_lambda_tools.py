"""
AWS Lambda Tools - Serverless Function Management

This example demonstrates how to use AWSLambdaTools for AWS Lambda operations.
Shows enable_ flag patterns for selective function access.
AWSLambdaTools is a small tool (<6 functions) so it uses enable_ flags.

Prerequisites:
- Run: `pip install boto3` to install dependencies
- Set up AWS credentials (AWS CLI, environment variables, or IAM roles)
- Ensure proper IAM permissions for Lambda operations
"""

from agno.agent import Agent
from agno.tools.aws_lambda import AWSLambdaTools

# Example 1: All functions enabled (default behavior)
agent_full = Agent(
    tools=[AWSLambdaTools(region_name="us-east-1")],  # All functions enabled
    name="Full AWS Lambda Agent",
    description="You are a comprehensive AWS Lambda specialist with all serverless capabilities.",
    instructions=[
        "Help users with all AWS Lambda operations including listing, invoking, and managing functions",
        "Provide clear explanations of Lambda operations and results",
        "Ensure proper error handling for AWS operations",
        "Format responses clearly using markdown",
    ],
    markdown=True,
)

# Example 2: Enable only function listing and invocation
agent_basic = Agent(
    tools=[
        AWSLambdaTools(
            region_name="us-east-1",
            enable_list_functions=True,
            enable_invoke_function=True,
            enable_create_function=False,  # Disable function creation
            enable_update_function=False,  # Disable function updates
        )
    ],
    name="Lambda Reader Agent",
    description="You are an AWS Lambda specialist focused on reading and invoking existing functions.",
    instructions=[
        "List and invoke existing Lambda functions",
        "Cannot create or modify Lambda functions",
        "Provide insights about function execution and performance",
        "Focus on function monitoring and execution",
    ],
    markdown=True,
)

# Example 3: Enable all functions using 'all=True' pattern
agent_comprehensive = Agent(
    tools=[AWSLambdaTools(region_name="us-east-1", all=True)],
    name="Comprehensive Lambda Agent",
    description="You are a full-featured AWS Lambda manager with all capabilities enabled.",
    instructions=[
        "Manage complete AWS Lambda lifecycle including creation, updates, and deployments",
        "Provide comprehensive serverless architecture guidance",
        "Support advanced Lambda configurations and optimizations",
        "Handle complex serverless workflows and integrations",
    ],
    markdown=True,
)

# Example 4: Invoke-only agent for testing
agent_tester = Agent(
    tools=[
        AWSLambdaTools(
            region_name="us-east-1",
            enable_list_functions=True,  # Enable listing for reference
            enable_invoke_function=True,  # Enable function testing
            enable_create_function=False,  # Disable creation
            enable_delete_function=False,  # Disable deletion (safety)
        )
    ],
    name="Lambda Tester Agent",
    description="You are an AWS Lambda testing specialist focused on safe function execution.",
    instructions=[
        "Test and validate Lambda function execution",
        "Cannot create or delete functions for safety",
        "Provide detailed execution results and performance metrics",
        "Focus on function testing and validation workflows",
    ],
    markdown=True,
)

# Example usage
print("=== Basic Lambda Operations Example ===")
agent_basic.print_response(
    "List all Lambda functions in our AWS account", markdown=True
)

print("\n=== Function Testing Example ===")
agent_tester.print_response(
    "Invoke the 'hello-world' Lambda function with an empty payload and analyze the results",
    markdown=True,
)

print("\n=== Comprehensive Management Example ===")
agent_comprehensive.print_response(
    "Provide an overview of our Lambda environment including function count, runtimes, and recent activity",
    markdown=True,
)

# Note: Make sure you have the necessary AWS credentials set up in your environment
# or use AWS CLI's configure command to set them up before running this script.
