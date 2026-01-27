# Engineering Wiki

## Development Environment Setup

### Prerequisites

Before setting up your development environment, ensure you have:
- macOS 12+ or Ubuntu 20.04+
- 16GB RAM minimum (32GB recommended)
- 50GB free disk space
- Admin access to install software

### Required Software

1. **Package Manager**
   - macOS: Install Homebrew from https://brew.sh
   - Linux: Use apt or your distribution's package manager

2. **Version Control**
   ```bash
   brew install git
   git config --global user.name "Your Name"
   git config --global user.email "your.email@acmecorp.example.com"
   ```

3. **Programming Languages**
   - Python 3.11+ (using pyenv)
   - Node.js 18+ (using nvm)
   - Go 1.21+ (using gvm)

4. **Docker**
   - Install Docker Desktop
   - Request access to company Docker registry

5. **IDE**
   - VS Code with recommended extensions (see .vscode/extensions.json)
   - Or JetBrains IDE with company license

### Repository Access

1. Generate SSH key: `ssh-keygen -t ed25519`
2. Add public key to GitHub profile
3. Request access to organization repos through IT portal
4. Clone starter repositories:
   ```bash
   git clone git@github.com:acmecorp/platform.git
   git clone git@github.com:acmecorp/frontend.git
   git clone git@github.com:acmecorp/services.git
   ```

### Database Setup

For local development, use Docker Compose:
```bash
cd platform
docker-compose up -d postgres redis
```

Default credentials:
- PostgreSQL: localhost:5432, user: dev, password: devpass
- Redis: localhost:6379, no password

## Coding Standards

### Python Style Guide

We follow PEP 8 with these additions:
- Line length: 100 characters
- Use type hints for all public functions
- Use dataclasses or Pydantic for data structures
- Format with Black, lint with Ruff

Example:
```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class User:
    id: int
    name: str
    email: Optional[str] = None

def get_user_by_id(user_id: int) -> Optional[User]:
    """Retrieve a user by their ID.

    Args:
        user_id: The unique identifier of the user.

    Returns:
        The User object if found, None otherwise.
    """
    # Implementation
    pass
```

### JavaScript/TypeScript Style Guide

- Use TypeScript for all new code
- Follow Airbnb style guide
- Use ESLint and Prettier
- Prefer functional components with hooks in React

### Code Review Guidelines

All changes require review before merging:
1. Create a pull request with clear description
2. Ensure all CI checks pass
3. Request review from at least one team member
4. Address feedback or discuss alternatives
5. Squash commits when merging

## Architecture Overview

### System Components

```
                    +-----------+
                    |   CDN     |
                    +-----+-----+
                          |
                    +-----v-----+
                    |  Frontend |
                    |   (React) |
                    +-----+-----+
                          |
                    +-----v-----+
                    |    API    |
                    |  Gateway  |
                    +-----+-----+
                          |
         +----------------+----------------+
         |                |                |
   +-----v-----+    +-----v-----+    +-----v-----+
   |   Users   |    |  Orders   |    |  Products |
   |  Service  |    |  Service  |    |  Service  |
   +-----------+    +-----------+    +-----------+
         |                |                |
         +-------+--------+--------+-------+
                 |                 |
           +-----v-----+     +-----v-----+
           | PostgreSQL|     |   Redis   |
           +-----------+     +-----------+
```

### Services

| Service | Language | Purpose |
|---------|----------|---------|
| API Gateway | Go | Request routing, auth |
| Users Service | Python | User management |
| Orders Service | Python | Order processing |
| Products Service | Go | Product catalog |
| Frontend | TypeScript | Web application |

### Communication

- Services communicate via gRPC internally
- REST API exposed through API Gateway
- Event-driven updates via Redis pub/sub
- Async jobs via Celery with Redis broker

## Testing Requirements

### Test Coverage

- Unit tests: 80% minimum coverage
- Integration tests: All API endpoints
- E2E tests: Critical user flows

### Running Tests

```bash
# Unit tests
pytest tests/unit

# Integration tests
pytest tests/integration

# E2E tests
npm run test:e2e
```

### Test Environments

| Environment | Purpose | Database |
|-------------|---------|----------|
| Local | Development | Local Docker |
| Dev | Feature testing | Shared dev DB |
| Staging | Pre-production | Production clone |
| Production | Live users | Production DB |

## Deployment

### CI/CD Pipeline

1. Push to feature branch triggers CI
2. Tests run automatically
3. PR merge to main deploys to staging
4. Manual approval deploys to production

### Deployment Schedule

- Staging: Continuous deployment
- Production: Tuesday and Thursday, 10 AM - 4 PM
- No deployments on Fridays or during holidays
- Hotfixes follow expedited process

### Rollback Procedure

1. Identify the issue
2. Notify #engineering-alerts channel
3. Run rollback script: `./scripts/rollback.sh <previous-version>`
4. Verify service health
5. Create incident report

## On-Call

### Schedule

- Engineers rotate weekly
- Primary and secondary on-call
- Schedule managed in PagerDuty
- Swap requests via #engineering-oncall channel

### Responsibilities

- Monitor alerts and respond within SLA
- Triage issues and escalate as needed
- Document incidents and resolutions
- Participate in post-incident reviews

### Escalation Path

1. Primary on-call (15 min response)
2. Secondary on-call (30 min response)
3. Engineering Manager
4. VP of Engineering

## Questions?

- Slack: #engineering
- Email: eng@acmecorp.example.com
- Office Hours: Wednesdays 2-3 PM
