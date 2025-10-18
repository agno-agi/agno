# DigitalOcean CLI Testing Guide

This project demonstrates testing unified multi-cloud infrastructure with **real DigitalOcean resources** using the `ag` CLI.

## ⚠️ Important Notes

- **Real Resources**: This will create actual resources in your DigitalOcean account
- **Real Costs**: Resources incur charges (~$6/month for droplet, prorated)
- **Cleanup Required**: Run `ag infra down` after testing to avoid ongoing charges

## Prerequisites

### 1. Install Dependencies

```bash
# From agno_infra root directory
cd ../../..  # Navigate to agno_infra root
pip install -e .[unified]
```

### 2. DigitalOcean Credentials

DigitalOcean uses **two different credential types**:

#### A. Personal Access Token (for Droplets/VMs)
Get from: https://cloud.digitalocean.com/account/api/tokens

Create a token with **Read and Write** permissions.

#### B. Spaces Access Keys (for Object Storage)
Get from: https://cloud.digitalocean.com/account/api/spaces

Click "Generate New Key" to create Spaces access key + secret.

## Setup

### Set Your DigitalOcean Credentials

```bash
# For Droplets (Required)
export DIGITALOCEAN_ACCESS_TOKEN="your-personal-access-token"

# For Spaces - Optional (only needed if deploying buckets)
export DIGITALOCEAN_SPACES_ACCESS_KEY="your-spaces-key"
export DIGITALOCEAN_SPACES_SECRET_KEY="your-spaces-secret"

# Verify they're set
echo $DIGITALOCEAN_ACCESS_TOKEN
echo $DIGITALOCEAN_SPACES_ACCESS_KEY
```

**Note**: If you only want to test Droplets, you can skip the Spaces keys. The bucket creation will fail gracefully.

### Optional: Configure SSH Key

To access your droplet via SSH, add your SSH key ID to `infra/dev.py`:

1. Get your SSH key ID from DigitalOcean dashboard or API
2. Edit `infra/dev.py` and uncomment the `ssh_keys` line
3. Replace `"your-ssh-key-id"` with your actual key ID

## Testing Workflow

### Navigate to Test Project

```bash
cd examples/digitalocean_test
```

### View Resources to Deploy

```bash
# Dry run - see what will be created without actually creating
ag infra up --dry-run
```

Expected output:
```
Resources to create (2):
  - UnifiedInstance: agno-test-droplet (provider: digitalocean)
  - UnifiedBucket: agno-test-space (provider: digitalocean)
```

### Deploy Resources

```bash
# Create resources in DigitalOcean
ag infra up

# Or skip confirmation prompt
ag infra up -y
```

This will:
1. Show resources to be created
2. Ask for confirmation
3. Create droplet and space in your DO account
4. Display creation status

Expected output:
```
Creating resources on DIGITALOCEAN
✅ Created UnifiedInstance: agno-test-droplet
✅ Created UnifiedBucket: agno-test-space

✅ Successfully created 2 resources
```

### Verify in DigitalOcean Dashboard

1. Go to https://cloud.digitalocean.com/droplets
2. You should see `agno-test-droplet` running
3. Go to https://cloud.digitalocean.com/spaces
4. You should see `agno-test-space` bucket

### Filter Resources (Optional)

```bash
# Create only compute resources
ag infra up --group compute

# Create only storage resources
ag infra up --group storage

# Create specific resource by name
ag infra up --name agno-test-droplet
```

### Clean Up Resources

**IMPORTANT**: Delete resources to stop incurring charges!

```bash
# Delete all resources
ag infra down

# Or skip confirmation
ag infra down -y
```

Expected output:
```
Resources to delete (2):
  - UnifiedBucket: agno-test-space (provider: digitalocean)
  - UnifiedInstance: agno-test-droplet (provider: digitalocean)

Deleting resources...
✅ Deleted UnifiedBucket: agno-test-space
✅ Deleted UnifiedInstance: agno-test-droplet

✅ Successfully deleted 2 resources
```

### Verify Cleanup

1. Check DigitalOcean dashboard to confirm resources are deleted
2. Both droplet and space should be gone

## Troubleshooting

### Authentication Error

```
Error: Invalid credentials
```

**Solution**: Verify your DIGITALOCEAN_ACCESS_TOKEN is set correctly:
```bash
echo $DIGITALOCEAN_ACCESS_TOKEN
# Should output your token, not empty
```

### Region Not Available

```
Error: Region 'nyc3' not available
```

**Solution**: Edit `infra/dev.py` and change `provider_region` to an available region:
- `nyc1`, `nyc3` (New York)
- `sfo3` (San Francisco)
- `ams3` (Amsterdam)
- `sgp1` (Singapore)
- `lon1` (London)
- `fra1` (Frankfurt)

### Import Error

```
ModuleNotFoundError: No module named 'agno.unified'
```

**Solution**: Install agno-infra with unified dependencies:
```bash
cd ../../..  # Navigate to agno_infra root
pip install -e .[unified]
```

### Libcloud Not Installed

```
ModuleNotFoundError: No module named 'libcloud'
```

**Solution**: Install apache-libcloud:
```bash
pip install apache-libcloud>=3.8.0
```

## Cost Breakdown

**Resources Created**:
- **Droplet (s-1vcpu-1gb)**: $6/month prorated (≈$0.009/hour)
- **Space**: Free for first 250GB, then $5/month

**Example Costs**:
- 1 hour testing: ~$0.01
- 1 day testing: ~$0.20
- 1 week testing: ~$1.40

**To minimize costs**: Delete resources immediately after testing with `ag infra down`

## What Gets Created

### 1. Droplet (Virtual Machine)
- **Name**: agno-test-droplet
- **Size**: 1 CPU, 1GB RAM
- **Image**: Ubuntu 22.04
- **Region**: NYC3
- **Tags**: purpose=agno-test, env=dev

### 2. Space (S3-Compatible Storage)
- **Name**: agno-test-space
- **Type**: Object storage bucket
- **Region**: NYC3
- **ACL**: Private

## Next Steps

After successful testing:

1. ✅ Verify resources created correctly
2. ✅ Test CLI filtering (`--group`, `--name`)
3. ✅ Clean up with `ag infra down`
4. 📦 Try other providers (AWS, GCP, Azure)
5. 🚀 Build your own multi-cloud infrastructure

## Additional Resources

- [Unified Multi-Cloud Documentation](../../UNIFIED_MULTICLOUD.md)
- [DigitalOcean API Documentation](https://docs.digitalocean.com/reference/api/)
- [Apache Libcloud Documentation](https://libcloud.readthedocs.io/)
