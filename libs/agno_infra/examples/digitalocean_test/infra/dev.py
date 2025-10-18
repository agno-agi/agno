"""
Development environment resources for DigitalOcean testing.

This file defines real infrastructure resources that will be deployed
to your DigitalOcean account for testing the unified multi-cloud interface.

IMPORTANT: These resources will incur actual costs on DigitalOcean!
- Droplet: ~$6/month (prorated while running)
- Space: Free tier available, or ~$5/month

Make sure to run `ag infra down` to clean up resources after testing.
"""

from agno.unified.resources import UnifiedResources
from agno.unified.resource.compute import UnifiedInstance
from agno.unified.resource.storage import UnifiedBucket

#
# Development Environment Resources
#
dev_resources = UnifiedResources(
    env="dev",
    infra="unified",
    resources=[
        # DigitalOcean Droplet (VM)
        # This will create a real droplet in your DO account
        UnifiedInstance(
            name="agno-test-droplet",
            provider="digitalocean",
            provider_region="nyc3",  # New York datacenter

            # Size mapping: "small" -> s-1vcpu-1gb (1 CPU, 1GB RAM)
            # Cost: ~$6/month (prorated)
            size="small",

            # Image mapping: "ubuntu-22.04" -> ubuntu-22-04-x64
            image="ubuntu-22.04",

            # Optional: SSH key for access
            # ssh_keys=["your-ssh-key-id"],  # Add your SSH key ID here

            # Tags for easy identification
            tags={"purpose": "agno-test", "env": "dev"},

            # Resource grouping
            group="compute",
        ),

        # DigitalOcean Space (S3-compatible storage)
        # This will create a real Space in your DO account
        # UnifiedBucket(
        #     name="agno-test-space",
        #     provider="digitalocean",
        #     provider_region="nyc3",  # Must match a Space region
        #
        #     # Access control: private, public-read, public-read-write
        #     acl="private",
        #
        #     # Resource grouping
        #     group="storage",
        # ),
    ],
)
