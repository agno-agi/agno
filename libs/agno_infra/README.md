# Agno Infra

**A lightweight framework and CLI for managing Agentic Infrastructure**

[![PyPI version](https://badge.fury.io/py/agno-infra.svg)](https://badge.fury.io/py/agno-infra)
[![Python 3.7+](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/downloads/)

## Overview

Agno Infra is a powerful infrastructure management framework designed specifically for building and deploying agentic applications. It provides a unified interface for managing infrastructure across multiple platforms including AWS, Docker, and local environments, making it easy to deploy AI agents and supporting services.

## 🚀 Key Features

- **Multi-Platform Support**: Seamlessly manage infrastructure across AWS, Docker, and local environments
- **Agent-Focused**: Purpose-built for deploying AI agents and their supporting infrastructure
- **Template-Based**: Quick start with pre-built infrastructure templates
- **Unified CLI**: Single command interface (`ag` or `agno`) for all infrastructure operations
- **Resource Management**: Comprehensive resource management for databases, networking, storage, and compute
- **Application Support**: Built-in support for FastAPI, Streamlit, Celery, Django, and more

## 📦 Installation

### Using pip

```bash
pip install agno-infra
```

### With optional dependencies

```bash
# For AWS support
pip install agno-infra[aws]

# For Docker support
pip install agno-infra[docker]

# For development
pip install agno-infra[dev]
```

## 🛠 Quick Start

### 1. Create Infrastructure from Template

```bash
# Create a new agent infrastructure project
ag create my-agent-infra --template agent-infra-docker

# Navigate to your project
cd my-agent-infra
```

### 2. CLI Operations

```bash
# List available templates
ag templates

# Deploy infrastructure
ag deploy

# Check infrastructure status
ag status

# Tear down infrastructure
ag destroy
```

## 🏗 Project Structure

```
agno/
├── aws/                    # AWS resource management
│   ├── resource/          # AWS resource types (EC2, RDS, S3, etc.)
│   └── app/              # AWS application deployments
├── docker/                # Docker resource management
│   ├── resource/         # Docker resources (containers, networks, volumes)
│   └── app/             # Dockerized applications
├── base/                  # Base classes and interfaces
├── cli/                   # Command-line interface
├── infra/                 # Core infrastructure management
└── utilities/             # Helper utilities and tools
```

## 🌟 Supported Resources

### AWS Resources
- **Compute**: EC2 instances, ECS clusters, ECS services
- **Storage**: S3 buckets, EBS volumes
- **Database**: RDS instances and clusters
- **Networking**: VPC, subnets, security groups, load balancers
- **Security**: IAM roles and policies, ACM certificates
- **Analytics**: EMR clusters, Glue crawlers
- **Caching**: ElastiCache clusters

### Docker Resources
- **Containers**: Docker containers with full lifecycle management
- **Networks**: Custom Docker networks
- **Volumes**: Persistent and ephemeral volumes
- **Images**: Container image management

### Application Types
- **FastAPI**: REST API applications
- **Streamlit**: Data science and ML dashboards
- **Celery**: Distributed task processing
- **Django**: Web applications
- **PostgreSQL**: Database with pgvector support
- **Redis**: Caching and message brokering

## 📋 Requirements

- Python 3.7 or higher
- For AWS: Valid AWS credentials configured
- For Docker: Docker engine installed and running

## 📚 Documentation

- **Main Documentation**: [docs.agno.com](https://docs.agno.com)

## 🏘 Community

- **Discord**: [Join our community](https://discord.gg/4MtYHHrgA8)
- **Discourse**: [Community forum](https://community.agno.com/)
- **GitHub Issues**: [Report bugs or request features](https://github.com/agno-agi/agno/issues)

## 📄 License

This project is licensed under the Mozilla Public License 2.0 - see the [LICENSE](LICENSE) file for details.

## 🙋‍♀️ Support

- **Documentation**: Check our comprehensive docs at [docs.agno.com](https://docs.agno.com)
- **Community**: Join our Discord or post on Discourse
- **Issues**: Open an issue on GitHub for bugs or feature requests
- **Commercial Support**: Contact us at [agno.com](https://agno.com)

---

**Built with ❤️ by the Agno team**