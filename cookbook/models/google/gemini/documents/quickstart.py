"""
Quickstart Example
==================

This example shows how to get started with the SDK.
"""

from sdk import Client

# Initialize client
client = Client(api_key="your-api-key")

# Create a user
user = client.users.create(
    name="John Doe",
    email="john@example.com"
)

# List users
users = client.users.list()
for user in users:
    print(f"User: {user.name} - {user.email}")

# Update a user
client.users.update(
    user_id=user.id,
    name="Jane Doe"
)

# Delete a user
client.users.delete(user_id=user.id)

print("Done!")
