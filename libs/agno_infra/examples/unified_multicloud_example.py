"""
Unified Multi-Cloud Infrastructure Example

This example demonstrates how to use agno_infra's unified interface to manage
infrastructure across multiple cloud providers (AWS, GCP, Azure, DigitalOcean, etc.)
with the same code.
"""

import os
from typing import List

from agno.unified.resource.compute import UnifiedInstance


def create_vm_on_multiple_providers():
    """
    Create identical VMs on multiple cloud providers using the same interface.

    This demonstrates the power of the unified API - same code works across
    60+ cloud providers!
    """
    print("=" * 80)
    print("Unified Multi-Cloud VM Creation Example")
    print("=" * 80)

    # Configuration for all providers
    vm_config = {
        "name": "my-agent-vm",
        "size": "medium",  # Automatically mapped to provider-specific sizes
        "image": "ubuntu-22.04",  # Automatically mapped to provider-specific images
        "ssh_key": "my-ssh-key",
        "tags": {"project": "agno-demo", "environment": "dev"},
    }

    # List of providers to deploy to
    providers = [
        {"name": "aws", "region": "us-east-1"},
        {"name": "gcp", "region": "us-central1-a"},
        {"name": "azure", "region": "eastus"},
        {"name": "digitalocean", "region": "nyc3"},
    ]

    instances: List[UnifiedInstance] = []

    for provider_config in providers:
        provider_name = provider_config["name"]
        region = provider_config["region"]

        print(f"\n{'='*60}")
        print(f"Creating VM on {provider_name.upper()} in {region}")
        print(f"{'='*60}")

        # Create instance with unified interface
        vm = UnifiedInstance(
            **vm_config,
            provider=provider_name,
            provider_region=region,
            # Provider credentials are loaded automatically from environment variables
            # AWS: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
            # GCP: GCE_SERVICE_ACCOUNT_EMAIL, GCE_SERVICE_ACCOUNT_KEY, GCE_PROJECT_ID
            # Azure: AZURE_TENANT_ID, AZURE_SUBSCRIPTION_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET
            # DigitalOcean: DIGITALOCEAN_ACCESS_TOKEN
        )

        # Create the VM (same method for all providers!)
        try:
            if vm.create():
                print(f"✅ VM created successfully on {provider_name}")
                print(f"   State: {vm.get_state()}")
                print(f"   Public IPs: {vm.get_public_ips()}")
                print(f"   Private IPs: {vm.get_private_ips()}")
                instances.append(vm)
            else:
                print(f"❌ Failed to create VM on {provider_name}")
        except Exception as e:
            print(f"❌ Error creating VM on {provider_name}: {e}")

    return instances


def cleanup_vms(instances: List[UnifiedInstance]):
    """Delete all created VMs."""
    print(f"\n{'='*80}")
    print("Cleaning up VMs across all providers")
    print(f"{'='*80}")

    for vm in instances:
        print(f"\nDeleting VM {vm.name} on {vm.provider}")
        try:
            if vm.delete():
                print(f"✅ VM deleted successfully")
            else:
                print(f"❌ Failed to delete VM")
        except Exception as e:
            print(f"❌ Error deleting VM: {e}")


def provider_specific_example():
    """
    Example showing how to use provider-specific features when needed.

    For most use cases, the unified interface is sufficient. But when you need
    advanced provider-specific features, you can use native SDKs.
    """
    print(f"\n{'='*80}")
    print("Provider-Specific Features Example")
    print(f"{'='*80}")

    # Create instance with provider-specific options
    vm = UnifiedInstance(
        name="advanced-vm",
        provider="aws",
        size="t2.large",  # Can use provider-specific size names
        image="ami-12345678",  # Or provider-specific image IDs
        provider_region="us-east-1",
        # Provider-specific options via provider_specific dict
        provider_specific={
            "ex_security_groups": ["my-security-group"],
            "ex_subnet": "subnet-12345678",
            "ex_blockdevicemappings": [
                {
                    "DeviceName": "/dev/sda1",
                    "Ebs": {"VolumeSize": 100, "VolumeType": "gp3"},
                }
            ],
        },
    )

    print("VM created with AWS-specific features like security groups and custom block device mappings")

    return vm


def multi_cloud_agentic_infra():
    """
    Example of deploying AI agent infrastructure across multiple clouds.

    This shows how agno_infra makes it easy to deploy agentic applications
    with redundancy and geographic distribution across multiple providers.
    """
    print(f"\n{'='*80}")
    print("Multi-Cloud Agentic Infrastructure Example")
    print(f"{'='*80}")

    # Deploy agent workers across multiple clouds for redundancy
    agent_configs = [
        {
            "name": "agent-worker-aws-1",
            "provider": "aws",
            "region": "us-east-1",
            "size": "large",
            "tags": {"role": "agent-worker", "region": "us-east"},
        },
        {
            "name": "agent-worker-gcp-1",
            "provider": "gcp",
            "region": "us-central1-a",
            "size": "large",
            "tags": {"role": "agent-worker", "region": "us-central"},
        },
        {
            "name": "agent-worker-azure-1",
            "provider": "azure",
            "region": "eastus",
            "size": "large",
            "tags": {"role": "agent-worker", "region": "us-east"},
        },
    ]

    workers = []
    for config in agent_configs:
        print(f"\nDeploying {config['name']} on {config['provider']}")

        worker = UnifiedInstance(
            name=config["name"],
            provider=config["provider"],
            provider_region=config["region"],
            size=config["size"],
            image="ubuntu-22.04",
            tags=config["tags"],
            # Cloud-init script to setup agent worker
            user_data="""#!/bin/bash
            # Install agent dependencies
            apt-get update
            apt-get install -y python3-pip docker.io
            pip3 install agno

            # Start agent worker
            systemctl start agno-worker
            """,
        )

        if worker.create():
            print(f"✅ Agent worker deployed on {config['provider']}")
            workers.append(worker)

    print(f"\n{'='*60}")
    print(f"Deployed {len(workers)} agent workers across {len(set(w.provider for w in workers))} cloud providers")
    print(f"{'='*60}")

    return workers


def main():
    """Run all examples."""
    print("""
    ╔════════════════════════════════════════════════════════════════════╗
    ║                                                                    ║
    ║        Agno Infra - Unified Multi-Cloud Infrastructure            ║
    ║                                                                    ║
    ║    Manage resources across 60+ cloud providers with one API       ║
    ║                                                                    ║
    ╚════════════════════════════════════════════════════════════════════╝
    """)

    # Example 1: Create VMs on multiple providers
    print("\n📦 Example 1: Create VMs on Multiple Providers")
    instances = create_vm_on_multiple_providers()

    # Example 2: Provider-specific features
    print("\n🔧 Example 2: Provider-Specific Features")
    advanced_vm = provider_specific_example()

    # Example 3: Multi-cloud agentic infrastructure
    print("\n🤖 Example 3: Multi-Cloud Agentic Infrastructure")
    workers = multi_cloud_agentic_infra()

    # Cleanup
    print("\n🧹 Cleanup: Delete all created resources")
    if input("\nDelete all created resources? (y/n): ").lower() == "y":
        cleanup_vms(instances + [advanced_vm] + workers)

    print("""
    ╔════════════════════════════════════════════════════════════════════╗
    ║                                                                    ║
    ║                     🎉 Examples Complete! 🎉                       ║
    ║                                                                    ║
    ║  You can now deploy AI agents and infrastructure across any       ║
    ║  cloud provider using the same simple interface!                  ║
    ║                                                                    ║
    ║  Supported providers: AWS, GCP, Azure, DigitalOcean, Linode,      ║
    ║  Vultr, OpenStack, and 50+ more!                                  ║
    ║                                                                    ║
    ╚════════════════════════════════════════════════════════════════════╝
    """)


if __name__ == "__main__":
    main()
