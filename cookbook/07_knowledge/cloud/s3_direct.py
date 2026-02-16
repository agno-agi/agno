"""
S3 Direct File Listing — Without AgentOS
============================================================

Use S3Config.list_files() directly in scripts without running
an AgentOS server. Useful for browsing bucket contents.

Requirements:
- boto3: pip install boto3
- AWS credentials configured
"""

from os import getenv

from agno.knowledge.remote_content import S3Config

# Configure S3 source
s3_config = S3Config(
    id="my-bucket",
    name="My S3 Bucket",
    bucket_name=getenv("S3_BUCKET_NAME", "my-bucket"),
    region=getenv("AWS_REGION", "us-east-1"),
    aws_access_key_id=getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=getenv("AWS_SECRET_ACCESS_KEY"),
)


def list_all_files():
    """List files at the bucket root."""
    print("Listing files at bucket root...")
    result = s3_config.list_files(limit=20)

    print(f"\nFolders ({len(result.folders)}):")
    for folder in result.folders:
        empty_marker = " (empty)" if folder["is_empty"] else ""
        print(f"  {folder['name']}/{empty_marker}")

    print(f"\nFiles ({len(result.files)}):")
    for f in result.files:
        size_kb = f["size"] / 1024 if f["size"] else 0
        print(f"  {f['name']} ({size_kb:.1f} KB)")

    print(
        f"\nPage {result.page} of {result.total_pages} ({result.total_count} total files)"
    )


def list_folder(prefix: str):
    """List files in a specific folder."""
    print(f"\nListing files in '{prefix}'...")
    result = s3_config.list_files(prefix=prefix, limit=20)

    print(f"\nSubfolders ({len(result.folders)}):")
    for folder in result.folders:
        print(f"  {folder['name']}/")

    print(f"\nFiles ({len(result.files)}):")
    for f in result.files:
        size_kb = f["size"] / 1024 if f["size"] else 0
        print(f"  {f['name']} ({size_kb:.1f} KB)")


def paginate_all():
    """Paginate through all files."""
    print("\nPaginating through all files...")
    page = 1
    total = 0

    while True:
        result = s3_config.list_files(limit=10, page=page)
        total += len(result.files)
        print(f"Page {page}/{result.total_pages}: {len(result.files)} files")

        if page >= result.total_pages:
            break
        page += 1

    print(f"\nTotal files: {total}")


if __name__ == "__main__":
    print("S3 Direct File Listing Demo")
    print("=" * 50)

    try:
        list_all_files()
    except ImportError as e:
        print(f"Missing dependency: {e}")
        print("Install boto3: pip install boto3")
    except Exception as e:
        if "NoCredentials" in str(e) or "credentials" in str(e).lower():
            print(f"AWS credentials not configured: {e}")
            print("\nSet these environment variables:")
            print("  export AWS_ACCESS_KEY_ID=...")
            print("  export AWS_SECRET_ACCESS_KEY=...")
            print("  export S3_BUCKET_NAME=...")
        elif "NoSuchBucket" in str(e):
            print(f"Bucket not found: {s3_config.bucket_name}")
        else:
            print(f"Error: {e}")
