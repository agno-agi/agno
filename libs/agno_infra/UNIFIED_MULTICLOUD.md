# Unified Multi-Cloud Support for Agno Infra

Agno Infra now supports **60+ cloud providers** through a unified interface powered by Apache Libcloud, while maintaining backward compatibility with AWS-specific resources.

## 🌍 Supported Providers

### Major Cloud Providers
- **AWS** (Amazon Web Services)
- **GCP** (Google Cloud Platform)
- **Azure** (Microsoft Azure)

### Developer-Friendly Clouds
- **DigitalOcean** - Simple, affordable cloud computing
- **Linode** - High-performance SSD Linux servers
- **Vultr** - Instant deployment cloud servers

### Enterprise & Private Clouds
- **OpenStack** - Open-source cloud computing platform
- **VMware vSphere** - Enterprise virtualization
- **CloudStack** - Open-source cloud orchestration

### And 50+ More!
Apache Libcloud supports dozens of additional providers including Rackspace, Alibaba Cloud, IBM Cloud, Oracle Cloud, and more.

## 📦 Installation

### Basic Installation (Unified Multi-Cloud)
```bash
# Install with unified multi-cloud support
pip install agno-infra[unified]

# Or install for specific providers
pip install agno-infra[aws]      # AWS only
pip install agno-infra[gcp]      # GCP native SDK
pip install agno-infra[azure]    # Azure native SDK

# Or install everything
pip install agno-infra[all-clouds]
```

## 🚀 Quick Start

### Create a VM on Any Provider

```python
from agno.unified.resource.compute import UnifiedInstance

# Works identically across 60+ providers!
vm = UnifiedInstance(
    name="my-vm",
    provider="gcp",  # or "aws", "azure", "digitalocean", etc.
    size="medium",   # Automatically mapped to provider sizes
    image="ubuntu-22.04",
    provider_region="us-central1-a"
)

vm.create()
```

### Same Code, Different Providers

```python
# AWS
aws_vm = UnifiedInstance(
    name="aws-vm",
    provider="aws",
    size="medium",  # Mapped to t2.medium
    image="ubuntu-22.04",
    provider_region="us-east-1"
)

# GCP
gcp_vm = UnifiedInstance(
    name="gcp-vm",
    provider="gcp",
    size="medium",  # Mapped to e2-medium
    image="ubuntu-22.04",
    provider_region="us-central1-a"
)

# Azure
azure_vm = UnifiedInstance(
    name="azure-vm",
    provider="azure",
    size="medium",  # Mapped to Standard_B2s
    image="ubuntu-22.04",
    provider_region="eastus"
)

# Create all with same interface
aws_vm.create()
gcp_vm.create()
azure_vm.create()
```

## 🎯 Key Features

### 1. **Unified Interface**
Write once, deploy anywhere. Same Python code works across all supported providers.

### 2. **Automatic Resource Mapping**
Common resource names (like "medium" for VM size or "ubuntu-22.04" for image) are automatically mapped to provider-specific equivalents.

### 3. **Backward Compatible**
Existing AWS-specific code continues working unchanged. The unified interface is opt-in.

### 4. **Native SDK Fallback**
Need provider-specific features? Fall back to native SDKs (boto3, google-cloud, azure-sdk) for advanced functionality.

### 5. **Environment-Based Credentials**
Credentials are automatically loaded from environment variables for all providers.

## 🔧 Configuration

### Credentials Management

Agno Infra loads credentials from environment variables:

#### AWS
```bash
export AWS_ACCESS_KEY_ID="your-key-id"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_REGION="us-east-1"
```

#### GCP
```bash
export GCE_SERVICE_ACCOUNT_EMAIL="your-email@project.iam.gserviceaccount.com"
export GCE_SERVICE_ACCOUNT_KEY="/path/to/key.json"
export GCE_PROJECT_ID="your-project-id"
export GCE_REGION="us-central1-a"
```

#### Azure
```bash
export AZURE_TENANT_ID="your-tenant-id"
export AZURE_SUBSCRIPTION_ID="your-subscription-id"
export AZURE_CLIENT_ID="your-client-id"
export AZURE_CLIENT_SECRET="your-client-secret"
```

#### DigitalOcean
```bash
export DIGITALOCEAN_ACCESS_TOKEN="your-access-token"
```

#### Linode
```bash
export LINODE_API_KEY="your-api-key"
```

## 📚 Resource Types

### Currently Implemented

#### Compute Resources
- **UnifiedInstance** - Virtual machines/instances across all providers
  - Auto-mapped sizes: nano, micro, small, medium, large, xlarge
  - Auto-mapped images: ubuntu-22.04, ubuntu-20.04, debian-11, centos-8
  - Full CRUD operations: create, read, update, delete
  - Operations: start, stop, reboot (provider-dependent)

### Coming Soon

#### Storage Resources
- **UnifiedObjectStorage** - S3-compatible object storage
- **UnifiedBlockStorage** - Block volumes/disks

#### Network Resources
- **UnifiedLoadBalancer** - Load balancing
- **UnifiedSecurityGroup** - Firewall rules
- **UnifiedDNS** - DNS management

## 🎨 Usage Patterns

### Pattern 1: Multi-Cloud Deployment

Deploy the same infrastructure across multiple clouds for redundancy:

```python
providers = ["aws", "gcp", "azure"]

for provider in providers:
    vm = UnifiedInstance(
        name=f"agent-worker-{provider}",
        provider=provider,
        size="large",
        image="ubuntu-22.04",
        tags={"role": "agent-worker", "cloud": provider}
    )
    vm.create()
```

### Pattern 2: Geographic Distribution

Deploy close to users across different regions and providers:

```python
locations = [
    {"provider": "aws", "region": "us-east-1"},
    {"provider": "gcp", "region": "europe-west1-b"},
    {"provider": "azure", "region": "eastasia"},
    {"provider": "digitalocean", "region": "sgp1"}
]

for loc in locations:
    vm = UnifiedInstance(
        name=f"app-{loc['region']}",
        provider=loc['provider'],
        provider_region=loc['region'],
        size="medium",
        image="ubuntu-22.04"
    )
    vm.create()
```

### Pattern 3: Cost Optimization

Use cheaper providers for dev/test, premium providers for production:

```python
# Development on DigitalOcean (cheaper)
dev_vm = UnifiedInstance(
    name="dev-instance",
    provider="digitalocean",
    size="small",
    image="ubuntu-22.04"
)

# Production on AWS (more services)
prod_vm = UnifiedInstance(
    name="prod-instance",
    provider="aws",
    size="large",
    image="ubuntu-22.04",
    provider_specific={
        "ex_security_groups": ["production-sg"],
        "ex_monitoring": True
    }
)
```

### Pattern 4: Hybrid Architecture

Combine unified resources with provider-specific resources:

```python
from agno.unified.resource.compute import UnifiedInstance
from agno.aws.resource.rds import RDSInstance  # AWS-specific

# Use unified interface for compute
app_server = UnifiedInstance(
    name="app-server",
    provider="aws",
    size="medium",
    image="ubuntu-22.04"
)

# Use AWS-specific resource for database
database = RDSInstance(
    name="app-db",
    engine="postgres",
    instance_class="db.t3.micro"
)

app_server.create()
database.create()
```

## 🔐 Security Best Practices

1. **Never hardcode credentials** - Always use environment variables or credential files
2. **Use least-privilege IAM roles** - Grant only required permissions
3. **Rotate credentials regularly** - Set up automatic credential rotation
4. **Use security groups** - Restrict network access appropriately
5. **Enable encryption** - Use encrypted volumes and transit encryption

## 🤝 Backward Compatibility

All existing AWS-specific code continues working unchanged:

```python
# Existing AWS code still works!
from agno.aws.resource.ec2 import SecurityGroup
from agno.aws.resource.rds import RDSInstance

sg = SecurityGroup(name="my-sg")
sg.create()

db = RDSInstance(name="my-db")
db.create()
```

## 🏗️ Architecture

```
agno_infra/
├── base/
│   ├── resource.py          # InfraResource (existing)
│   └── unified.py           # UnifiedResource (new)
├── aws/                     # AWS resources (existing, unchanged)
├── docker/                  # Docker resources (existing, unchanged)
└── unified/                 # NEW: Multi-cloud resources
    ├── provider.py          # Provider factory & routing
    └── resource/
        ├── compute/
        │   └── instance.py  # UnifiedInstance
        ├── storage/         # Coming soon
        └── network/         # Coming soon
```

## 🆚 Comparison: Unified vs Provider-Specific

| Feature | Unified Interface | Provider-Specific |
|---------|-------------------|-------------------|
| **Providers** | 60+ providers | Single provider |
| **Code Portability** | ✅ Write once, deploy anywhere | ❌ Rewrite for each provider |
| **Learning Curve** | ✅ Learn once, use everywhere | ❌ Learn each provider's API |
| **Feature Coverage** | ⚠️ Common features only | ✅ All provider features |
| **Maintenance** | ✅ Libcloud handles updates | ❌ Manual SDK updates |
| **Advanced Features** | ⚠️ Via native SDK fallback | ✅ Full access |

## 💡 When to Use What

### Use Unified Interface When:
- ✅ Deploying across multiple cloud providers
- ✅ Building portable infrastructure code
- ✅ Working with common resources (VMs, storage, networking)
- ✅ Rapid prototyping and development
- ✅ Cost optimization through provider flexibility

### Use Provider-Specific Resources When:
- ✅ Need advanced provider-specific features
- ✅ Deep integration with provider ecosystem
- ✅ Performance-critical optimizations
- ✅ Existing codebase is provider-specific
- ✅ Regulatory requirements mandate specific provider

## 📖 Examples

See `examples/unified_multicloud_example.py` for comprehensive usage examples including:
- Creating VMs on multiple providers
- Provider-specific features
- Multi-cloud agentic infrastructure deployment
- Cleanup and resource management

## 🐛 Troubleshooting

### Import Error: libcloud not found
```bash
pip install apache-libcloud>=3.8.0
```

### Authentication Failed
Check that environment variables are set correctly:
```python
import os
print(os.getenv("AWS_ACCESS_KEY_ID"))  # Should not be None
```

### Provider Not Supported
Check the list of supported providers:
```python
from agno.unified.provider import ProviderType
print(list(ProviderType))
```

### Feature Not Available
Some features are provider-specific. Use native SDK fallback:
```python
vm = UnifiedInstance(
    name="vm",
    provider="aws",
    use_native_sdk=True  # Use boto3 instead of Libcloud
)
```

## 🤝 Contributing

We welcome contributions! To add support for new resources or improve existing ones:

1. Extend `UnifiedResource` base class
2. Implement `_create`, `_read`, `_update`, `_delete` methods
3. Add resource mapping for common names (sizes, images)
4. Add tests for major providers (AWS, GCP, Azure)
5. Update documentation

## 📝 License

Apache License 2.0 (same as Apache Libcloud)

## 🔗 Resources

- [Apache Libcloud Documentation](https://libcloud.readthedocs.io/)
- [Agno Documentation](https://docs.agno.com)
- [GitHub Issues](https://github.com/agno-agi/agno/issues)
- [Community Discord](https://discord.gg/4MtYHHrgA8)

---

**Built with ❤️ by the Agno team**

*Making multi-cloud infrastructure management as simple as Docker*
