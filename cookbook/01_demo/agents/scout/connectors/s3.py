"""S3 connector (stub implementation with mock data).

S3 is the primary connector for demos and most enterprise deployments.
"""

from typing import Any

from .base import BaseConnector

# Mock data simulating a typical company's S3 knowledge base
MOCK_BUCKETS: list[dict[str, Any]] = [
    {
        "name": "company-docs",
        "region": "us-east-1",
        "description": "Company documents and policies",
    },
    {
        "name": "engineering-docs",
        "region": "us-east-1",
        "description": "Engineering documentation",
    },
    {
        "name": "data-exports",
        "region": "us-east-1",
        "description": "Data exports and reports",
    },
]

MOCK_FILES: dict[str, list[dict[str, Any]]] = {
    "company-docs": [
        {
            "key": "policies/employee-handbook.md",
            "size": 45000,
            "modified": "2024-01-15",
        },
        {"key": "policies/pto-policy.md", "size": 8500, "modified": "2024-02-01"},
        {"key": "policies/data-retention.md", "size": 12000, "modified": "2024-03-10"},
        {"key": "policies/security-policy.md", "size": 25000, "modified": "2024-01-20"},
        {
            "key": "policies/remote-work-policy.md",
            "size": 6000,
            "modified": "2024-02-15",
        },
        {"key": "hr/benefits-guide.md", "size": 18000, "modified": "2024-02-15"},
        {"key": "hr/onboarding-checklist.md", "size": 5000, "modified": "2024-03-01"},
        {"key": "hr/expense-policy.md", "size": 4500, "modified": "2024-01-10"},
        {"key": "planning/q4-2024-okrs.md", "size": 15000, "modified": "2024-10-01"},
        {"key": "planning/q3-2024-okrs.md", "size": 14000, "modified": "2024-07-01"},
        {"key": "planning/2024-strategy.md", "size": 28000, "modified": "2024-01-05"},
        {"key": "planning/budget-2024.md", "size": 8000, "modified": "2024-01-15"},
    ],
    "engineering-docs": [
        {
            "key": "architecture/system-overview.md",
            "size": 35000,
            "modified": "2024-04-20",
        },
        {"key": "architecture/api-design.md", "size": 22000, "modified": "2024-05-15"},
        {
            "key": "architecture/database-schema.md",
            "size": 18000,
            "modified": "2024-03-20",
        },
        {
            "key": "architecture/security-architecture.md",
            "size": 15000,
            "modified": "2024-04-01",
        },
        {"key": "runbooks/deployment.md", "size": 18000, "modified": "2024-03-01"},
        {
            "key": "runbooks/incident-response.md",
            "size": 25000,
            "modified": "2024-03-15",
        },
        {"key": "runbooks/oncall-guide.md", "size": 12000, "modified": "2024-04-01"},
        {
            "key": "runbooks/database-maintenance.md",
            "size": 10000,
            "modified": "2024-02-20",
        },
        {
            "key": "runbooks/rollback-procedures.md",
            "size": 8000,
            "modified": "2024-03-10",
        },
        {"key": "guides/getting-started.md", "size": 8000, "modified": "2024-05-01"},
        {"key": "guides/code-review.md", "size": 10000, "modified": "2024-04-15"},
        {"key": "guides/testing-guide.md", "size": 12000, "modified": "2024-04-20"},
        {"key": "guides/api-development.md", "size": 15000, "modified": "2024-05-10"},
        {
            "key": "rfcs/rfc-001-search-redesign.md",
            "size": 20000,
            "modified": "2024-05-20",
        },
        {"key": "rfcs/rfc-002-api-v2.md", "size": 18000, "modified": "2024-06-01"},
        {
            "key": "rfcs/rfc-003-auth-overhaul.md",
            "size": 16000,
            "modified": "2024-06-15",
        },
    ],
    "data-exports": [
        {
            "key": "reports/monthly-metrics-2024-01.csv",
            "size": 45000,
            "modified": "2024-02-01",
        },
        {
            "key": "reports/monthly-metrics-2024-02.csv",
            "size": 48000,
            "modified": "2024-03-01",
        },
        {
            "key": "reports/monthly-metrics-2024-03.csv",
            "size": 52000,
            "modified": "2024-04-01",
        },
        {
            "key": "reports/monthly-metrics-2024-04.csv",
            "size": 50000,
            "modified": "2024-05-01",
        },
        {
            "key": "reports/monthly-metrics-2024-05.csv",
            "size": 55000,
            "modified": "2024-06-01",
        },
        {
            "key": "reports/quarterly-review-q1-2024.md",
            "size": 30000,
            "modified": "2024-04-15",
        },
        {
            "key": "reports/quarterly-review-q2-2024.md",
            "size": 32000,
            "modified": "2024-07-15",
        },
        {
            "key": "exports/user-data-export.json",
            "size": 100000,
            "modified": "2024-06-01",
        },
        {
            "key": "exports/analytics-dashboard.json",
            "size": 25000,
            "modified": "2024-06-01",
        },
    ],
}

MOCK_CONTENTS: dict[str, str] = {
    "company-docs/policies/employee-handbook.md": """# Employee Handbook

## Welcome to Acme Corp

This handbook outlines our company policies, benefits, and expectations.

## Table of Contents
1. Core Values
2. Employment Policies
3. Benefits
4. Time Off (PTO)
5. Remote Work
6. Code of Conduct

## 1. Core Values

Our core values guide everything we do:
- **Customer First** — We exist to serve our customers
- **Move Fast** — Speed matters, but not at the expense of quality
- **Be Transparent** — Default to openness
- **Own Your Work** — Take responsibility for outcomes

## 2. Employment Policies

### At-Will Employment
Employment at Acme Corp is at-will, meaning either party may terminate the relationship at any time.

### Equal Opportunity
We are an equal opportunity employer and do not discriminate based on race, color, religion, sex, national origin, age, disability, or any other protected characteristic.

## 3. Benefits

See the Benefits Guide for detailed information on:
- Health insurance (medical, dental, vision)
- 401(k) with company match
- Life insurance
- Disability coverage
- Professional development budget

## 4. Time Off (PTO)

### PTO Policy
- Unlimited PTO with manager approval
- Minimum 2 weeks recommended per year
- No carryover or payout (it's unlimited!)
- Please give 2 weeks notice for vacations over 1 week

### Holidays
Company-observed holidays:
- New Year's Day
- MLK Day
- Presidents Day
- Memorial Day
- Independence Day
- Labor Day
- Thanksgiving (Thu + Fri)
- Christmas Eve & Christmas Day
- New Year's Eve

### Sick Leave
Take what you need. No questions asked for short-term illness. For extended illness (5+ days), please coordinate with HR.

## 5. Remote Work

### Hybrid Policy
- Minimum 2 days in office per week
- Core hours: 10am-4pm local time
- All-hands meetings: Tuesdays at 10am PT

### Home Office
- $500 stipend for home office setup (one-time)
- Monthly internet reimbursement: $50

## 6. Code of Conduct

We are committed to providing a respectful, inclusive workplace. This includes:
- Treating all colleagues with respect
- No harassment or discrimination
- Protecting confidential information
- Reporting concerns to HR or your manager

For questions about any policy, contact hr@acme.com.
""",
    "company-docs/policies/pto-policy.md": """# PTO Policy

## Overview
Acme Corp offers unlimited paid time off (PTO) to all full-time employees.

## Guidelines

### Requesting Time Off
1. Submit requests via the HR system
2. Get manager approval before booking travel
3. For 5+ consecutive days, give at least 2 weeks notice
4. For 2+ weeks, give at least 1 month notice

### Blackout Periods
Please avoid scheduling PTO during:
- Last two weeks of each quarter
- Company all-hands weeks
- Your team's on-call rotation

### Manager Responsibilities
- Respond to PTO requests within 48 hours
- Ensure adequate team coverage
- Don't deny requests unreasonably

## Frequently Asked Questions

**Q: Is there a maximum amount of PTO I can take?**
A: No formal maximum, but use good judgment. Most employees take 3-4 weeks per year.

**Q: Can I take PTO during my first 90 days?**
A: Yes, but keep it minimal while you're ramping up.

**Q: What if I'm sick?**
A: Sick time doesn't count against your PTO. Take care of yourself.

**Q: Do I get paid out for unused PTO if I leave?**
A: No, because PTO is unlimited there's nothing to pay out.

For questions, contact hr@acme.com.
""",
    "company-docs/policies/data-retention.md": """# Data Retention Policy

## Overview
This policy defines how long Acme Corp retains different types of data.

## Retention Periods

| Data Type | Retention Period | Notes |
|-----------|-----------------|-------|
| Customer data | Duration of contract + 7 years | Legal requirement |
| Employee records | Duration of employment + 7 years | Legal requirement |
| Financial records | 7 years | Tax and audit requirements |
| Email | 3 years | Unless litigation hold |
| Slack messages | 2 years | Unless litigation hold |
| System logs | 90 days | Security and debugging |
| Analytics data | 2 years | Aggregated data kept longer |

## Data Deletion

### Automatic Deletion
Data is automatically deleted after the retention period expires, unless:
- Subject to litigation hold
- Required for ongoing investigation
- Customer requests earlier deletion (where applicable)

### Manual Deletion Requests
- Customer data: Process within 30 days per GDPR/CCPA
- Employee data: Contact HR
- Other data: Contact legal@acme.com

## Backups

Backups follow the same retention schedule as primary data:
- Daily backups: 30 days
- Weekly backups: 90 days
- Monthly backups: 1 year

## Exceptions

To request an exception to this policy, contact legal@acme.com with:
- Data type and location
- Reason for exception
- Requested retention period
- Business justification

## Compliance

This policy complies with:
- GDPR (EU)
- CCPA (California)
- SOC 2
- Industry best practices

Last updated: March 2024
Contact: legal@acme.com
""",
    "company-docs/policies/security-policy.md": """# Security Policy

## Overview
This policy outlines security requirements for all Acme Corp employees.

## Access Control

### Authentication
- All systems require SSO authentication
- MFA is mandatory for all accounts
- Passwords must be at least 12 characters
- Password rotation every 90 days

### Authorization
- Principle of least privilege
- Access reviews quarterly
- Immediate revocation on termination

## Device Security

### Company Devices
- Full disk encryption required
- Automatic screen lock after 5 minutes
- Remote wipe capability enabled
- No unapproved software installation

### Personal Devices (BYOD)
- Must be enrolled in MDM
- Company data must be encrypted
- Separate work profile required

## Data Classification

| Level | Description | Examples | Requirements |
|-------|-------------|----------|--------------|
| Public | Safe to share externally | Marketing materials | None |
| Internal | Company-wide access | Policies, guides | SSO required |
| Confidential | Need-to-know basis | Financial data, PII | MFA + encryption |
| Restricted | Highly sensitive | Security keys, credentials | Hardware key + audit |

## Incident Reporting

Report security incidents immediately to:
- Email: security@acme.com
- Slack: #security-incidents
- PagerDuty: Security on-call

## Training

All employees must complete:
- Security awareness training (annual)
- Phishing simulation (quarterly)
- Role-specific training (as needed)

Last updated: January 2024
Contact: security@acme.com
""",
    "company-docs/hr/benefits-guide.md": """# Benefits Guide

## Overview
Acme Corp offers comprehensive benefits to all full-time employees.

## Health Insurance

### Medical
- Provider: Blue Cross Blue Shield
- Plans: PPO, HMO, HDHP
- Coverage: Employee, Employee + Spouse, Family
- Company pays: 90% of premium

### Dental
- Provider: Delta Dental
- Coverage: Preventive 100%, Basic 80%, Major 50%
- Annual maximum: $2,000

### Vision
- Provider: VSP
- Coverage: Annual exam, frames, lenses/contacts
- Frame allowance: $200

## 401(k) Retirement Plan

- Provider: Fidelity
- Company match: 100% up to 4% of salary
- Vesting: Immediate
- Contribution limit: IRS annual limit ($23,000 in 2024)

## Life & Disability Insurance

### Life Insurance
- Basic: 2x annual salary (company paid)
- Supplemental: Up to 5x salary (employee paid)

### Disability
- Short-term: 60% of salary, up to 12 weeks
- Long-term: 60% of salary, after 12 weeks

## Other Benefits

### Professional Development
- Annual budget: $2,500 per employee
- Covers: Courses, conferences, certifications, books

### Wellness
- Gym membership reimbursement: $100/month
- Mental health: Free therapy sessions (up to 12/year)
- Wellness days: 2 per year (in addition to PTO)

### Perks
- Commuter benefits: Pre-tax transit/parking
- Cell phone: $75/month reimbursement
- Meals: Catered lunch 3x/week in office

## Enrollment

- New hires: Enroll within 30 days of start date
- Annual enrollment: November 1-15
- Qualifying life events: 30 days to make changes

Contact: benefits@acme.com
""",
    "company-docs/planning/q4-2024-okrs.md": """# Q4 2024 Company OKRs

## Company Mission
Make enterprise knowledge accessible and actionable.

## Objective 1: Accelerate Revenue Growth

**Key Results:**
1. Achieve $10M ARR by end of Q4 (currently $7.5M)
2. Close 15 new enterprise deals (>$100k ACV)
3. Reduce monthly churn to below 3% (currently 4.5%)
4. Expand 5 existing customers to >$500k ACV

**Owner:** Sales Team
**Status:** On Track

## Objective 2: Improve Product Quality

**Key Results:**
1. Achieve 99.9% uptime (currently 99.5%)
2. Reduce P0/P1 bugs to zero in production
3. Decrease average API response time to <200ms (currently 350ms)
4. Ship 3 major features from customer roadmap

**Owner:** Engineering Team
**Status:** At Risk (latency work behind schedule)

## Objective 3: Scale the Team

**Key Results:**
1. Hire 10 engineers (5 backend, 3 frontend, 2 platform)
2. Improve eNPS score to 70+ (currently 55)
3. Complete leadership training for all people managers
4. Launch engineering blog with 5 posts

**Owner:** People Team
**Status:** On Track

## Objective 4: Expand Market Presence

**Key Results:**
1. Launch in 2 new geographic markets (EU, APAC)
2. Achieve SOC 2 Type II certification
3. Present at 3 industry conferences
4. Increase website traffic by 50%

**Owner:** Marketing Team
**Status:** On Track

## Team-Level OKRs
See individual team pages for detailed breakdowns:
- Engineering OKRs
- Sales OKRs
- Marketing OKRs
- People OKRs
""",
    "engineering-docs/runbooks/deployment.md": """# Deployment Runbook

## Overview
This runbook covers deploying to production environments.

## Pre-Deployment Checklist

- [ ] All tests passing in CI
- [ ] Code review approved
- [ ] No blocking P0/P1 bugs
- [ ] Feature flags configured
- [ ] Monitoring dashboards ready
- [ ] Rollback plan documented

## Deployment Process

### 1. Prepare Release

```bash
# Create release branch
git checkout main
git pull origin main
git checkout -b release/v1.2.3

# Update version
./scripts/bump-version.sh 1.2.3

# Create release notes
./scripts/generate-changelog.sh
```

### 2. Deploy to Staging

```bash
# Deploy to staging
./scripts/deploy.sh staging

# Run smoke tests
./scripts/smoke-test.sh staging
```

Verify in staging:
- [ ] Core user flows work
- [ ] No error spikes in logs
- [ ] Performance acceptable

### 3. Deploy to Production

```bash
# Deploy to production (canary first)
./scripts/deploy.sh production --canary

# Monitor for 15 minutes
# Check: error rates, latency, CPU/memory

# If healthy, full rollout
./scripts/deploy.sh production --full
```

### 4. Post-Deployment

- [ ] Verify in production
- [ ] Update status page
- [ ] Notify in #deployments Slack channel
- [ ] Close deployment ticket

## Rollback Procedure

If issues detected:

```bash
# Immediate rollback
./scripts/rollback.sh production

# Or rollback to specific version
./scripts/rollback.sh production --version v1.2.2
```

After rollback:
1. Page on-call if not already engaged
2. Post incident in #incidents
3. Create post-mortem ticket

## Emergency Contacts

- On-call engineer: See PagerDuty
- Platform team: #platform-eng
- SRE: #sre-team

## Common Issues

### Database Migrations Failed
1. Check migration logs: `kubectl logs -l app=migrations`
2. Rollback migration: `./scripts/rollback-migration.sh`
3. Fix migration and retry

### High Error Rates Post-Deploy
1. Check error logs: `./scripts/tail-errors.sh production`
2. If related to new code, rollback immediately
3. If infrastructure, engage platform team

### Performance Degradation
1. Check APM dashboards
2. Look for N+1 queries or missing indexes
3. Consider feature flag to disable slow features
""",
    "engineering-docs/runbooks/incident-response.md": """# Incident Response Runbook

## Severity Levels

| Level | Description | Response Time | Examples |
|-------|-------------|---------------|----------|
| SEV-1 | Complete outage | 15 minutes | Site down, data loss |
| SEV-2 | Major degradation | 30 minutes | Core feature broken |
| SEV-3 | Minor issues | 4 hours | Non-critical bugs |
| SEV-4 | Low impact | Next business day | Cosmetic issues |

## Incident Response Process

### 1. DETECT

Incidents are detected via:
- Automated alerts (PagerDuty)
- Customer reports
- Internal reports
- Monitoring dashboards

### 2. ACKNOWLEDGE

Within SLA for severity level:
1. Acknowledge page in PagerDuty
2. Join #incidents Slack channel
3. Claim incident: "I'm on this"

### 3. ASSESS

Determine:
- Severity level (use definitions above)
- Impact scope (all users? some users? one customer?)
- Affected systems
- Likely cause (recent deploy? infrastructure? external?)

### 4. COMMUNICATE

**For SEV-1/SEV-2:**
- Post to #incidents with initial assessment
- Update status page
- Notify leadership (VP Eng, CTO)
- Set up bridge call if needed

**Template:**
```
🚨 INCIDENT: [Brief description]
Severity: SEV-X
Impact: [Who's affected]
Status: Investigating
IC: @[your name]
```

### 5. MITIGATE

Focus on restoring service, not root cause:

**Quick wins:**
- Rollback recent deployment
- Restart affected services
- Scale up resources
- Enable feature flags to disable broken features
- Failover to backup systems

**Document everything:**
- What you tried
- What worked/didn't work
- Timeline of events

### 6. RESOLVE

When service is restored:
1. Verify with monitoring
2. Update status page: "Resolved"
3. Send all-clear to #incidents
4. Keep bridge call open for 15 min observation

### 7. FOLLOW-UP

**Within 48 hours for SEV-1/SEV-2:**
- Schedule post-mortem
- Create follow-up tickets
- Update runbooks if needed

## Escalation Paths

| Need | Contact |
|------|---------|
| More engineers | Page backup on-call |
| Database help | #data-eng |
| Infrastructure | #platform-eng |
| Security issue | #security (page immediately) |
| Leadership | CTO: direct page for SEV-1 |

## Useful Commands

```bash
# Check service status
kubectl get pods -n production

# View recent logs
./scripts/tail-logs.sh production api

# Check error rates
./scripts/error-rates.sh --last 1h

# Recent deployments
./scripts/recent-deploys.sh
```

## Post-Mortem Template

See: /engineering-docs/templates/post-mortem-template.md

Key sections:
1. Summary
2. Timeline
3. Impact
4. Root cause
5. What went well
6. What went wrong
7. Action items
""",
    "engineering-docs/architecture/system-overview.md": """# System Architecture Overview

## High-Level Architecture

```
                    ┌─────────────────┐
                    │   Load Balancer │
                    │    (AWS ALB)    │
                    └────────┬────────┘
                             │
                    ┌────────┴────────┐
                    │   API Gateway   │
                    │     (Kong)      │
                    └────────┬────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
   ┌────┴────┐         ┌─────┴─────┐        ┌────┴────┐
   │  User   │         │   Core    │        │ Search  │
   │ Service │         │  Service  │        │ Service │
   └────┬────┘         └─────┬─────┘        └────┬────┘
        │                    │                    │
   ┌────┴────┐         ┌─────┴─────┐        ┌────┴────┐
   │PostgreSQL│        │ PostgreSQL │       │Elastic- │
   │ (Users) │         │  (Core)   │        │ search  │
   └─────────┘         └───────────┘        └─────────┘
```

## Core Services

### API Gateway (Kong)
- Routes requests to appropriate services
- Handles authentication/authorization
- Rate limiting and throttling
- Request/response transformation

### User Service
- User authentication (OAuth, SSO, API keys)
- User profiles and preferences
- Team and organization management
- Permission management (RBAC)

### Core Service
- Primary business logic
- CRUD operations for core entities
- Event emission for async processing
- Integration with external services

### Search Service
- Full-text search across all entities
- Powered by Elasticsearch
- Real-time indexing via event consumers
- Faceted search and filtering

## Infrastructure

### Compute
- **Kubernetes (EKS)** — Container orchestration
- **Node pools** — Separate pools for API, workers, and jobs
- **Auto-scaling** — Based on CPU/memory and custom metrics

### Data Stores
- **PostgreSQL (RDS)** — Primary data store
- **Redis (ElastiCache)** — Caching, sessions, rate limiting
- **Elasticsearch** — Search and analytics
- **S3** — File storage, backups, exports

### Messaging
- **SQS** — Task queues
- **SNS** — Event broadcasting
- **EventBridge** — Event routing

### Observability
- **DataDog** — Metrics, APM, logs
- **PagerDuty** — Alerting and on-call
- **Sentry** — Error tracking

## Key Design Decisions

### 1. Event-Driven Architecture
Services communicate primarily via events:
- Loose coupling between services
- Easy to add new consumers
- Built-in audit trail

### 2. CQRS for Search
Writes go to PostgreSQL, reads from Elasticsearch:
- Optimized for read-heavy workloads
- Near real-time search indexing
- Flexible query capabilities

### 3. Database Per Service
Each service owns its database:
- Clear ownership boundaries
- Independent scaling
- No cross-service joins (use events)

### 4. Feature Flags
All new features behind flags:
- Gradual rollouts
- Quick disable if issues
- A/B testing capability

## Security

### Authentication
- OAuth 2.0 / OIDC for user auth
- API keys for service-to-service
- JWT tokens with short expiry

### Authorization
- Role-based access control (RBAC)
- Resource-level permissions
- Audit logging for all actions

### Data Protection
- Encryption at rest (AES-256)
- Encryption in transit (TLS 1.3)
- PII handling per GDPR/CCPA

## Disaster Recovery

- **RPO:** 1 hour (point-in-time recovery)
- **RTO:** 4 hours (full recovery)
- **Multi-AZ:** All critical services
- **Cross-region:** Daily backups to us-west-2

## Further Reading

- [API Design Guide](/engineering-docs/architecture/api-design.md)
- [Database Schema](/engineering-docs/architecture/database-schema.md)
- [Security Architecture](/engineering-docs/architecture/security.md)
""",
    "engineering-docs/architecture/api-design.md": """# API Design Guide

## Overview
This document describes our API design standards and conventions.

## REST Principles

### Resource Naming
- Use plural nouns: `/users`, `/documents`, `/teams`
- Use kebab-case for multi-word resources: `/user-preferences`
- Nest resources logically: `/users/{id}/documents`

### HTTP Methods
| Method | Usage | Example |
|--------|-------|---------|
| GET | Read | `GET /users/123` |
| POST | Create | `POST /users` |
| PUT | Full update | `PUT /users/123` |
| PATCH | Partial update | `PATCH /users/123` |
| DELETE | Delete | `DELETE /users/123` |

### Status Codes
| Code | Usage |
|------|-------|
| 200 | Success |
| 201 | Created |
| 204 | No Content (DELETE) |
| 400 | Bad Request |
| 401 | Unauthorized |
| 403 | Forbidden |
| 404 | Not Found |
| 422 | Validation Error |
| 429 | Rate Limited |
| 500 | Server Error |

## Request/Response Format

### Request Headers
```
Content-Type: application/json
Authorization: Bearer <token>
X-Request-ID: <uuid>
```

### Response Format
```json
{
  "data": { ... },
  "meta": {
    "request_id": "uuid",
    "timestamp": "ISO8601"
  }
}
```

### Error Format
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Human readable message",
    "details": [
      {"field": "email", "message": "Invalid format"}
    ]
  },
  "meta": {
    "request_id": "uuid"
  }
}
```

## Pagination

### Request
```
GET /users?page=2&per_page=25
```

### Response
```json
{
  "data": [...],
  "meta": {
    "page": 2,
    "per_page": 25,
    "total": 100,
    "total_pages": 4
  }
}
```

## Filtering & Sorting

### Filtering
```
GET /users?status=active&role=admin
GET /users?created_after=2024-01-01
```

### Sorting
```
GET /users?sort=created_at&order=desc
GET /users?sort=-created_at  # shorthand
```

## Rate Limiting

- Default: 1000 requests/minute
- Auth endpoints: 10 requests/minute
- Headers returned:
  - `X-RateLimit-Limit`
  - `X-RateLimit-Remaining`
  - `X-RateLimit-Reset`

## Versioning

- Version in URL: `/api/v1/users`
- Major versions only
- Deprecation: 6 months notice

## Authentication

See [Security Architecture](/engineering-docs/architecture/security.md) for details.
""",
    "engineering-docs/guides/testing-guide.md": """# Testing Guide

## Overview
This guide covers our testing practices and standards.

## Test Pyramid

```
        ╱╲
       ╱  ╲       E2E Tests (10%)
      ╱────╲      - Critical user flows
     ╱      ╲
    ╱────────╲    Integration Tests (30%)
   ╱          ╲   - API endpoints, database
  ╱────────────╲
 ╱              ╲ Unit Tests (60%)
╱________________╲- Functions, classes, modules
```

## Unit Tests

### When to Write
- Every new function/method
- Bug fixes (test first!)
- Complex business logic

### Best Practices
```python
# Good: descriptive name, single assertion
def test_user_can_be_created_with_valid_email():
    user = User.create(email="test@example.com")
    assert user.email == "test@example.com"

# Bad: vague name, multiple unrelated assertions
def test_user():
    user = User.create(email="test@example.com")
    assert user.email == "test@example.com"
    assert user.is_active
    assert user.created_at is not None
```

### Coverage Requirements
- Minimum: 80% coverage
- Critical paths: 100% coverage
- New code: 90% coverage

## Integration Tests

### API Tests
```python
def test_create_user_endpoint():
    response = client.post("/api/v1/users", json={
        "email": "test@example.com",
        "name": "Test User"
    })
    assert response.status_code == 201
    assert response.json()["data"]["email"] == "test@example.com"
```

### Database Tests
- Use test database
- Rollback after each test
- Use factories for test data

## E2E Tests

### When to Write
- Critical user journeys
- Cross-service workflows
- Regression prevention

### Tools
- Playwright for UI
- pytest for API
- Custom fixtures for setup

## Running Tests

```bash
# All tests
pytest

# Unit tests only
pytest tests/unit/

# With coverage
pytest --cov=src --cov-report=html

# Specific file
pytest tests/test_users.py

# Watch mode
pytest-watch
```

## CI/CD Integration

Tests run on every PR:
1. Lint (ruff)
2. Type check (mypy)
3. Unit tests
4. Integration tests
5. E2E tests (main branch only)

## Test Data

### Factories
```python
class UserFactory:
    @staticmethod
    def create(**kwargs):
        defaults = {
            "email": f"user-{uuid4()}@test.com",
            "name": "Test User"
        }
        return User.create(**{**defaults, **kwargs})
```

### Fixtures
```python
@pytest.fixture
def authenticated_user():
    user = UserFactory.create()
    token = create_token(user)
    return user, token
```
""",
    "engineering-docs/rfcs/rfc-001-search-redesign.md": """# RFC-001: Search Redesign

## Metadata
- **Status:** Approved
- **Author:** Sarah Chen
- **Created:** 2024-05-01
- **Updated:** 2024-05-20
- **Decision:** Approved on 2024-05-20

## Summary
Redesign our search infrastructure to improve relevance and reduce latency.

## Problem Statement
Current search has several issues:
1. Average latency is 500ms (target: <200ms)
2. Relevance scores are inconsistent
3. No support for typo tolerance
4. Faceted search is slow

## Proposed Solution

### Architecture
Replace current Elasticsearch setup with a tiered approach:
1. **Hot tier:** Recent data (last 30 days) on SSD
2. **Warm tier:** Older data on HDD
3. **Cold tier:** Archive data in S3

### Improvements
1. Add typo tolerance using Elasticsearch fuzzy matching
2. Implement query caching with Redis
3. Add search analytics for relevance tuning
4. Pre-compute facet counts nightly

### Timeline
- Week 1-2: Infrastructure setup
- Week 3-4: Migration tooling
- Week 5-6: Gradual rollout
- Week 7-8: Monitoring and tuning

## Alternatives Considered

### Option A: Algolia
- Pros: Managed, fast, great relevance
- Cons: Expensive at scale, vendor lock-in

### Option B: Typesense
- Pros: Open source, fast
- Cons: Less mature, smaller community

### Option C: Elasticsearch optimization (chosen)
- Pros: Keep existing expertise, no migration risk
- Cons: More work, but better long-term control

## Decision
Approved Option C. The team has deep Elasticsearch expertise and the improvements are achievable within timeline.

## Success Metrics
- P50 latency < 100ms
- P99 latency < 300ms
- Relevance score (measured by CTR) +20%
- Zero downtime during migration
""",
}


class S3Connector(BaseConnector):
    """S3 connector with mock data for development/testing."""

    def __init__(self, bucket: str | None = None):
        self._authenticated = False
        self._default_bucket = bucket

    @property
    def source_type(self) -> str:
        return "s3"

    @property
    def source_name(self) -> str:
        return "S3"

    def authenticate(self) -> bool:
        """Simulate authentication (always succeeds in mock mode)."""
        self._authenticated = True
        return True

    def list_buckets(self) -> list[dict[str, Any]]:
        """List available S3 buckets."""
        return MOCK_BUCKETS

    def list_items(
        self,
        parent_id: str | None = None,
        item_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List files in a bucket or prefix."""
        bucket = parent_id or self._default_bucket
        if not bucket:
            # List buckets if no bucket specified
            return [
                {"id": b["name"], "name": b["name"], "type": "bucket"}
                for b in MOCK_BUCKETS
            ]

        # Parse bucket/prefix
        if "/" in bucket:
            bucket_name, prefix = bucket.split("/", 1)
        else:
            bucket_name = bucket
            prefix = ""

        files = MOCK_FILES.get(bucket_name, [])

        # Filter by prefix
        if prefix:
            files = [f for f in files if f["key"].startswith(prefix)]

        # Get unique directories at this level
        items: list[dict[str, Any]] = []
        seen_dirs: set[str] = set()

        for f in files:
            key = f["key"]
            if prefix:
                key = key[len(prefix) :].lstrip("/")

            if "/" in key:
                # This is a directory
                dir_name = key.split("/")[0]
                if dir_name not in seen_dirs:
                    seen_dirs.add(dir_name)
                    items.append(
                        {
                            "id": f"{bucket_name}/{prefix}{dir_name}".rstrip("/"),
                            "name": dir_name,
                            "type": "directory",
                        }
                    )
            else:
                # This is a file
                items.append(
                    {
                        "id": f"s3://{bucket_name}/{f['key']}",
                        "name": key,
                        "type": "file",
                        "size": f.get("size", 0),
                        "modified": f.get("modified", ""),
                    }
                )

        return items[:limit]

    def search(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search for files matching the query (grep-like search in content)."""
        query_lower = query.lower()
        results: list[dict[str, Any]] = []

        # Determine which buckets to search
        buckets = (
            [filters.get("bucket")]
            if filters and filters.get("bucket")
            else list(MOCK_FILES.keys())
        )

        for bucket in buckets:
            if bucket not in MOCK_FILES:
                continue

            for file in MOCK_FILES[bucket]:
                file_key = f"{bucket}/{file['key']}"
                content_key = file_key

                # Search in filename
                if query_lower in file["key"].lower():
                    results.append(
                        {
                            "id": f"s3://{file_key}",
                            "bucket": bucket,
                            "key": file["key"],
                            "name": file["key"].split("/")[-1],
                            "match_type": "filename",
                            "modified": file.get("modified", ""),
                        }
                    )
                    continue

                # Search in content
                if content_key in MOCK_CONTENTS:
                    content = MOCK_CONTENTS[content_key]
                    if query_lower in content.lower():
                        snippet = _extract_snippet_with_context(content, query)
                        results.append(
                            {
                                "id": f"s3://{file_key}",
                                "bucket": bucket,
                                "key": file["key"],
                                "name": file["key"].split("/")[-1],
                                "match_type": "content",
                                "snippet": snippet,
                                "modified": file.get("modified", ""),
                            }
                        )

        return results[:limit]

    def read(
        self,
        item_id: str,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Read file content from S3."""
        # Parse s3://bucket/key format
        if item_id.startswith("s3://"):
            item_id = item_id[5:]

        parts = item_id.split("/", 1)
        if len(parts) != 2:
            return {"error": f"Invalid S3 path: {item_id}"}

        bucket, key = parts
        content_key = f"{bucket}/{key}"

        if content_key not in MOCK_CONTENTS:
            return {"error": f"File not found: s3://{content_key}"}

        content = MOCK_CONTENTS[content_key]

        # Handle pagination for large files
        if options and options.get("offset"):
            lines = content.split("\n")
            offset = options.get("offset", 0)
            limit = options.get("limit", 100)
            content = "\n".join(lines[offset : offset + limit])

        return {
            "id": f"s3://{bucket}/{key}",
            "bucket": bucket,
            "key": key,
            "content": content,
            "metadata": {
                "size": len(content),
                "modified": _get_file_modified(bucket, key),
            },
        }

    def write(
        self,
        parent_id: str,
        title: str,
        content: str,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Write a file to S3 (mock - doesn't persist)."""
        # Parse bucket from parent_id
        if parent_id.startswith("s3://"):
            parent_id = parent_id[5:]

        bucket = parent_id.split("/")[0]
        key = f"{parent_id.split('/', 1)[1]}/{title}" if "/" in parent_id else title

        return {
            "id": f"s3://{bucket}/{key}",
            "bucket": bucket,
            "key": key,
            "message": "File written (mock mode - not persisted)",
        }

    def update(
        self,
        item_id: str,
        content: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update a file in S3 (mock - doesn't persist)."""
        return {
            "id": item_id,
            "message": "File updated (mock mode - not persisted)",
        }


def _get_file_modified(bucket: str, key: str) -> str:
    """Get file modified date from mock data."""
    files = MOCK_FILES.get(bucket, [])
    for f in files:
        if f["key"] == key:
            return f.get("modified", "")
    return ""


def _extract_snippet_with_context(
    content: str, query: str, context_lines: int = 2
) -> str:
    """Extract a snippet with surrounding context lines (grep-like)."""
    query_lower = query.lower()
    lines = content.split("\n")

    for i, line in enumerate(lines):
        if query_lower in line.lower():
            start = max(0, i - context_lines)
            end = min(len(lines), i + context_lines + 1)

            snippet_lines = []
            for j in range(start, end):
                prefix = ">" if j == i else " "
                snippet_lines.append(f"{prefix} {lines[j]}")

            return "\n".join(snippet_lines)

    return content[:200] + "..."
