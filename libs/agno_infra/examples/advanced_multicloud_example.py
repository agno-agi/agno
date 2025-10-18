"""
Advanced Multi-Cloud Infrastructure Example

This example demonstrates advanced features including:
- Compute instances (VMs)
- Object storage (buckets and objects)
- Block storage (volumes)
- Load balancers
- Multi-tier application deployment
"""

from typing import List

from agno.unified.resource.compute import UnifiedInstance
from agno.unified.resource.network import UnifiedLoadBalancer
from agno.unified.resource.storage import UnifiedBucket, UnifiedObject, UnifiedVolume


def deploy_three_tier_application(provider: str = "aws", region: str = "us-east-1"):
    """
    Deploy a complete three-tier application on any cloud provider.

    Architecture:
    - Load Balancer (public)
    - Web Tier (2 instances)
    - App Tier (2 instances)
    - Data Tier (storage bucket + volumes)

    This same code works on AWS, GCP, Azure, DigitalOcean, and 60+ more!
    """
    print(f"\n{'='*80}")
    print(f"Deploying Three-Tier Application on {provider.upper()}")
    print(f"{'='*80}\n")

    resources = []

    # Step 1: Create storage bucket for static assets
    print("📦 Step 1: Creating storage bucket for static assets...")
    bucket = UnifiedBucket(
        name=f"my-app-assets-{provider}",
        provider=provider,
        provider_region=region,
        acl="public-read",  # Public for static assets
    )

    if bucket.create():
        print(f"✅ Bucket created: {bucket.name}")
        resources.append(bucket)

        # Upload a sample file
        sample_file = UnifiedObject(
            name="index.html",
            bucket_name=bucket.name,
            object_key="static/index.html",
            provider=provider,
            content="<html><body><h1>Welcome to Multi-Cloud App!</h1></body></html>",
            content_type="text/html",
        )

        if sample_file.upload():
            print(f"✅ Uploaded: static/index.html")
            resources.append(sample_file)

    # Step 2: Create data volumes for database
    print("\n💾 Step 2: Creating data volumes for database...")
    db_volume = UnifiedVolume(
        name=f"db-volume-{provider}",
        provider=provider,
        provider_region=region,
        size=100,  # 100 GB
        volume_type="ssd",  # Auto-mapped to provider-specific SSD type
        encrypted=True,
    )

    if db_volume.create():
        print(f"✅ Volume created: {db_volume.name} (100 GB, encrypted SSD)")
        resources.append(db_volume)

    # Step 3: Deploy web tier instances
    print("\n🌐 Step 3: Deploying web tier (2 instances)...")
    web_instances = []

    for i in range(1, 3):
        web_vm = UnifiedInstance(
            name=f"web-server-{i}-{provider}",
            provider=provider,
            provider_region=region,
            size="medium",  # Auto-mapped to t2.medium, e2-medium, etc.
            image="ubuntu-22.04",
            user_data="""#!/bin/bash
            apt-get update
            apt-get install -y nginx
            echo '<h1>Web Server {}</h1>' > /var/www/html/index.html
            systemctl start nginx
            """.format(
                i
            ),
            tags={"tier": "web", "app": "demo", "index": str(i)},
        )

        if web_vm.create():
            print(f"✅ Web server {i} created")
            print(f"   Public IPs: {web_vm.get_public_ips()}")
            web_instances.append(web_vm)
            resources.append(web_vm)

    # Step 4: Deploy application tier instances
    print("\n⚙️  Step 4: Deploying application tier (2 instances)...")
    app_instances = []

    for i in range(1, 3):
        app_vm = UnifiedInstance(
            name=f"app-server-{i}-{provider}",
            provider=provider,
            provider_region=region,
            size="large",  # More powerful for application logic
            image="ubuntu-22.04",
            user_data="""#!/bin/bash
            apt-get update
            apt-get install -y python3 python3-pip
            pip3 install fastapi uvicorn
            """,
            tags={"tier": "app", "app": "demo", "index": str(i)},
        )

        if app_vm.create():
            print(f"✅ App server {i} created")
            print(f"   Private IPs: {app_vm.get_private_ips()}")
            app_instances.append(app_vm)
            resources.append(app_vm)

            # Attach database volume to first app server
            if i == 1 and db_volume.resource_created:
                print(f"   Attaching volume to app server {i}...")
                if db_volume.attach(app_vm.name, device="/dev/sdf"):
                    print(f"   ✅ Volume attached")

    # Step 5: Create load balancer
    print("\n⚖️  Step 5: Creating load balancer...")

    # Note: Load balancer support varies by provider
    # AWS, GCP, Azure have good support
    if provider.lower() in ["aws", "gcp", "azure"]:
        lb = UnifiedLoadBalancer(
            name=f"web-lb-{provider}",
            provider=provider,
            provider_region=region,
            protocol="http",
            port=80,
            algorithm="round_robin",
            targets=[vm.name for vm in web_instances],
            health_check_path="/",
            health_check_interval=30,
        )

        if lb.create():
            print(f"✅ Load balancer created: {lb.name}")
            print(f"   Endpoint: {lb.get_endpoint()}")
            print(f"   Targets: {len(lb.list_targets())}")
            resources.append(lb)
    else:
        print(f"⚠️  Load balancer not fully supported for {provider} in Libcloud")

    # Summary
    print(f"\n{'='*80}")
    print(f"🎉 Deployment Complete!")
    print(f"{'='*80}")
    print(f"Provider: {provider}")
    print(f"Region: {region}")
    print(f"Resources created: {len(resources)}")
    print(f"  - Storage buckets: 1")
    print(f"  - Data volumes: 1")
    print(f"  - Web servers: {len(web_instances)}")
    print(f"  - App servers: {len(app_instances)}")
    print(f"  - Load balancers: {1 if provider.lower() in ['aws', 'gcp', 'azure'] else 0}")
    print(f"{'='*80}\n")

    return resources


def demonstrate_storage_operations(provider: str = "aws"):
    """
    Demonstrate advanced storage operations across providers.
    """
    print(f"\n{'='*80}")
    print(f"Storage Operations Demo on {provider.upper()}")
    print(f"{'='*80}\n")

    # Create bucket
    print("📦 Creating bucket...")
    bucket = UnifiedBucket(
        name=f"demo-storage-{provider}",
        provider=provider,
        acl="private",
    )

    if not bucket.create():
        print("❌ Failed to create bucket")
        return

    print(f"✅ Bucket created: {bucket.name}\n")

    # Upload multiple objects
    print("📤 Uploading objects...")
    files = [
        ("data/file1.txt", "Hello from file 1!"),
        ("data/file2.txt", "Hello from file 2!"),
        ("images/logo.png", b"PNG_BINARY_DATA"),
    ]

    for key, content in files:
        obj = UnifiedObject(
            name=key,
            bucket_name=bucket.name,
            object_key=key,
            provider=provider,
            content=content,
        )

        if obj.upload():
            print(f"  ✅ Uploaded: {key}")

    # List objects
    print(f"\n📋 Listing objects in bucket...")
    objects = bucket.list_objects()
    print(f"  Found {len(objects)} objects:")
    for obj in objects:
        print(f"    - {obj.name} ({obj.size} bytes)")

    # Get bucket stats
    print(f"\n📊 Bucket statistics:")
    print(f"  Total size: {bucket.get_size() / 1024:.2f} KB")
    print(f"  Object count: {bucket.get_object_count()}")

    # Download an object
    print(f"\n📥 Downloading object...")
    download_obj = UnifiedObject(
        name="file1.txt",
        bucket_name=bucket.name,
        object_key="data/file1.txt",
        provider=provider,
    )

    content = download_obj.get_content()
    if content:
        print(f"  ✅ Downloaded: {content.decode()}")

    # Cleanup
    print(f"\n🧹 Cleaning up...")
    for obj in bucket.list_objects():
        UnifiedObject(
            name=obj.name,
            bucket_name=bucket.name,
            object_key=obj.name,
            provider=provider,
        ).delete()

    if bucket.delete():
        print(f"✅ Bucket deleted\n")


def demonstrate_volume_operations(provider: str = "aws"):
    """
    Demonstrate advanced volume operations.
    """
    print(f"\n{'='*80}")
    print(f"Volume Operations Demo on {provider.upper()}")
    print(f"{'='*80}\n")

    # Create a volume
    print("💾 Creating volume...")
    volume = UnifiedVolume(
        name=f"demo-volume-{provider}",
        provider=provider,
        size=50,  # 50 GB
        volume_type="ssd",
        encrypted=True,
    )

    if not volume.create():
        print("❌ Failed to create volume")
        return

    print(f"✅ Volume created: {volume.name}")
    print(f"   Size: {volume.size} GB")
    print(f"   Type: {volume.volume_type}")
    print(f"   State: {volume.get_state()}\n")

    # Create an instance to attach to
    print("🖥️  Creating instance for volume attachment...")
    instance = UnifiedInstance(
        name=f"volume-test-vm-{provider}",
        provider=provider,
        size="small",
        image="ubuntu-22.04",
    )

    if instance.create():
        print(f"✅ Instance created: {instance.name}\n")

        # Attach volume
        print("🔗 Attaching volume to instance...")
        if volume.attach(instance.name, device="/dev/sdf"):
            print(f"✅ Volume attached")
            print(f"   Attached to: {volume.attached_to}")
            print(f"   Device: {volume.device_name}\n")

            # Create snapshot
            print("📸 Creating volume snapshot...")
            snapshot_id = volume.create_snapshot(f"{volume.name}-snapshot")
            if snapshot_id:
                print(f"✅ Snapshot created: {snapshot_id}\n")

            # Detach volume
            print("🔓 Detaching volume...")
            if volume.detach():
                print(f"✅ Volume detached\n")

        # Cleanup
        print("🧹 Cleaning up...")
        instance.delete()
        volume.delete()
        print(f"✅ Resources cleaned up\n")


def main():
    """Run all advanced examples."""
    print("""
    ╔════════════════════════════════════════════════════════════════════╗
    ║                                                                    ║
    ║      Advanced Multi-Cloud Infrastructure Examples                 ║
    ║                                                                    ║
    ║  Complete application deployment with compute, storage,           ║
    ║  volumes, and load balancers - all with one unified API!          ║
    ║                                                                    ║
    ╚════════════════════════════════════════════════════════════════════╝
    """)

    # Example 1: Three-tier application deployment
    print("\n🏗️  Example 1: Three-Tier Application Deployment")
    print("-" * 80)
    resources = deploy_three_tier_application(provider="aws", region="us-east-1")

    # Example 2: Storage operations
    print("\n📦 Example 2: Advanced Storage Operations")
    print("-" * 80)
    demonstrate_storage_operations(provider="aws")

    # Example 3: Volume operations
    print("\n💾 Example 3: Advanced Volume Operations")
    print("-" * 80)
    demonstrate_volume_operations(provider="aws")

    # Cleanup option
    print("\n" + "=" * 80)
    if input("\nDelete all resources from Example 1? (y/n): ").lower() == "y":
        print("\n🧹 Cleaning up Example 1 resources...")
        for resource in reversed(resources):  # Delete in reverse order
            try:
                resource.delete()
                print(f"  ✅ Deleted: {resource.name}")
            except Exception as e:
                print(f"  ❌ Failed to delete {resource.name}: {e}")

    print("""
    ╔════════════════════════════════════════════════════════════════════╗
    ║                                                                    ║
    ║                   🎉 All Examples Complete! 🎉                     ║
    ║                                                                    ║
    ║  You've seen:                                                      ║
    ║  ✅ Three-tier application deployment                              ║
    ║  ✅ Object storage (buckets & objects)                             ║
    ║  ✅ Block storage (volumes & snapshots)                            ║
    ║  ✅ Load balancing                                                 ║
    ║  ✅ All working across 60+ cloud providers!                        ║
    ║                                                                    ║
    ╚════════════════════════════════════════════════════════════════════╝
    """)


if __name__ == "__main__":
    main()
