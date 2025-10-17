"""
Open Source Maintainer Intelligence Team

This team demonstrates the full power of Agno Teams by solving a real-world problem:
helping open source maintainers manage complex projects efficiently.

Team Composition:
- PR Review Council: Comprehensive code review expert
- Issue Triage Specialist: Intelligent issue categorization and prioritization
- Security Guardian: Security vulnerability detection and code safety
- Community Relations Manager: Contributor engagement and communication
- Release Coordinator: Release planning and changelog generation

Real-World Integration:
- Demo version uses mock data for self-contained testing
- Production version can integrate with real GitHub API via GithubTools
- Can be triggered by GitHub webhooks, CLI, or Agno OS chat interface
- Supports both interactive chat and automated workflows

Setup:
1. Ensure PostgreSQL is running: ./cookbook/scripts/run_pgvector.sh
2. Export API keys: ANTHROPIC_API_KEY, OPENAI_API_KEY
3. (Optional) Export GITHUB_ACCESS_TOKEN for real GitHub integration
4. Run via Agno OS: python cookbook/demo/run.py
5. Connect at os.agno.com to http://localhost:7777

GitHub Integration:
- Without GITHUB_ACCESS_TOKEN: Team analyzes based on text descriptions you provide
- With GITHUB_ACCESS_TOKEN: Team fetches real data from GitHub repositories

Usage Examples:
- "Review PR #342 in agno-agi/agno" (fetches real data if token provided)
- "Triage issue #156: Memory leak after 24 hours of operation"
- "Help respond to first-time contributor with code style issues"
- "Plan release v2.2.0 with breaking changes and security fixes"
"""

import asyncio
from os import getenv
from textwrap import dedent

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge import Knowledge
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.github import GithubTools
from agno.vectordb.lancedb import LanceDb
from pydantic import BaseModel

# ************* Database Setup *************
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url, id="oss_maintainer_db")
# *******************************


# ************* Knowledge Base Setup *************
# Project documentation knowledge base for context-aware responses
project_knowledge = Knowledge(
    vector_db=LanceDb(uri="tmp/oss_maintainer_kb", table_name="project_docs")
)


# Async function to load project documentation
async def _load_project_knowledge():
    """Load project documentation into knowledge base asynchronously."""
    print("Loading OSS Maintainer knowledge base...")
    await project_knowledge.add_contents_async(
        documents=[
            """
# Agno Project Documentation

## Architecture
Agno is built on a modular architecture with three core components:
- Agents: Individual AI entities with specific roles and capabilities
- Teams: Coordinated groups of agents working together
- Workflows: Multi-step processes for complex tasks

## Code Standards
- Follow PEP 8 for Python code
- Use type hints for all function signatures
- Maintain test coverage above 80%
- Document all public APIs with docstrings
- Keep functions under 50 lines when possible

## Security Guidelines
- All user input must be validated and sanitized
- Use parameterized queries to prevent SQL injection
- Implement rate limiting on authentication endpoints
- Store secrets in environment variables
- Regular dependency security audits

## Contribution Guidelines
- Fork and clone the repository
- Create feature branches from main
- Write tests for new features
- Ensure all tests pass before submitting PR
- Reference related issues in PR description
- Be respectful and constructive in all interactions

## Review Process
- PRs require approval from at least one maintainer
- Security changes require security team review
- Breaking changes need documentation updates
- Large PRs should be broken into smaller chunks
""",
            """
# Common Security Vulnerabilities

## SQL Injection
- Always use parameterized queries
- Never concatenate user input into SQL strings
- Use ORM query builders when possible

## Cross-Site Scripting (XSS)
- Sanitize all user-provided HTML
- Use Content Security Policy headers
- Escape output in templates

## Authentication Issues
- Implement rate limiting on login endpoints
- Use strong password hashing (bcrypt, argon2)
- Require multi-factor authentication for sensitive operations
- Implement secure session management

## CSRF Protection
- Use CSRF tokens on all state-changing operations
- Implement SameSite cookie attributes
- Validate origin headers

## Dependency Security
- Regularly update dependencies
- Use tools like Safety, Snyk for vulnerability scanning
- Pin dependency versions for reproducibility
""",
        ]
    )


# Load knowledge base at module initialization
asyncio.run(_load_project_knowledge())
# *******************************


# ************* GitHub Tools Setup *************
# GitHub token is required for this team - checked in run.py before import
github_token = getenv("GITHUB_ACCESS_TOKEN") or getenv("GITHUB_TOKEN")
if not github_token:
    raise ValueError("GITHUB_ACCESS_TOKEN is required for OSS Maintainer Intelligence team")

github_tools = GithubTools(access_token=github_token)
print("GitHub integration enabled - team can fetch real PR and issue data")
# *******************************


# ************* Structured Output Models *************
class PRReviewReport(BaseModel):
    """Comprehensive PR review report with scores and recommendations"""

    pr_number: int
    overall_score: float  # 0-100
    code_quality_score: float  # 0-100
    security_score: float  # 0-100
    test_coverage_score: float  # 0-100
    documentation_score: float  # 0-100
    findings: list[str]  # Detailed findings
    critical_issues: list[str]  # Must-fix issues
    recommendations: list[str]  # Improvement suggestions
    approval_status: str  # "approved", "changes_requested", "needs_discussion"
    estimated_review_time: str  # e.g., "2 hours"


class IssueTriageResult(BaseModel):
    """Issue triage result with categorization and priority"""

    issue_number: int
    category: str  # bug, feature, enhancement, docs, question
    priority: str  # critical, high, medium, low
    estimated_complexity: str  # trivial, minor, moderate, major, critical
    suggested_labels: list[str]
    suggested_assignees: list[str]
    duplicate_of: int | None  # Issue number if duplicate
    reasoning: str  # Explanation of triage decisions
    requires_security_review: bool


class SecurityAuditReport(BaseModel):
    """Security audit report with vulnerabilities and remediation"""

    vulnerabilities_found: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    vulnerability_details: list[dict]  # {type, severity, location, description, fix}
    overall_risk_level: str  # critical, high, medium, low, safe
    passed_security_check: bool
    recommendations: list[str]


class ReleaseReport(BaseModel):
    """Release planning report with changelog and breaking changes"""

    version: str
    release_type: str  # major, minor, patch
    breaking_changes: list[str]
    new_features: list[str]
    bug_fixes: list[str]
    performance_improvements: list[str]
    documentation_updates: list[str]
    contributors: list[str]
    upgrade_guide: str
    recommended_release_date: str
    total_prs_included: int


# *******************************


# ************* Team Agents *************

# Agent 1: PR Review Council
pr_review_council = Agent(
    name="PR Review Council",
    role="Comprehensive pull request analysis expert providing detailed code reviews",
    model=Claude(id="claude-sonnet-4-0"),
    tools=[github_tools],
    knowledge=project_knowledge,
    search_knowledge=True,
    instructions=dedent("""
        You are an expert code reviewer analyzing pull requests comprehensively.

        GitHub Integration:
        - If you have GitHub tools available, use them to fetch real PR data:
          * get_pull_request(repo_name, pr_number) - Get PR details
          * get_pull_request_changes(repo_name, pr_number) - Get files changed
          * get_pull_request_with_details(repo_name, pr_number) - Comprehensive info with comments
        - Example: get_pull_request('agno-agi/agno', 342)
        - If no GitHub tools, analyze based on the description provided by the user

        Review Criteria:
        1. CODE QUALITY (0-100):
           - Readability and maintainability
           - Adherence to project coding standards
           - Design patterns and architecture
           - Code complexity and modularity

        2. SECURITY (0-100):
           - Potential vulnerabilities
           - Input validation and sanitization
           - Authentication and authorization
           - Dependency security

        3. TEST COVERAGE (0-100):
           - Unit test completeness
           - Edge case handling
           - Integration test coverage
           - Test quality and assertions

        4. DOCUMENTATION (0-100):
           - Code comments and docstrings
           - API documentation
           - README updates
           - Migration guides if needed

        Provide specific, actionable feedback with:
        - Line numbers or file references when possible
        - Examples of how to improve
        - Praise for well-done aspects
        - Clear distinction between critical issues and suggestions

        Use the knowledge base to check against project standards.
    """).strip(),
)

# Agent 2: Issue Triage Specialist
issue_triage_agent = Agent(
    name="Issue Triage Specialist",
    role="Intelligent issue categorization, prioritization, and routing expert",
    model=OpenAIChat(id="gpt-4o"),
    tools=[github_tools],
    knowledge=project_knowledge,
    search_knowledge=True,
    instructions=dedent("""
        You are an expert at triaging issues for open source projects.

        GitHub Integration:
        - If you have GitHub tools available, use them to fetch real issue data:
          * get_issue(repo_name, issue_number) - Get issue details
          * list_issues(repo_name, state, page, per_page) - List repository issues
          * search_issues_and_prs(query, state, type_filter, repo) - Search issues
        - Example: get_issue('agno-agi/agno', 156)
        - If no GitHub tools, analyze based on the description provided by the user

        Categorization:
        - bug: Something is broken and needs fixing
        - feature: New functionality request
        - enhancement: Improvement to existing functionality
        - docs: Documentation needs
        - question: User needs help or clarification

        Priority Assessment Criteria:
        - CRITICAL: System down, data loss, security breach
        - HIGH: Major functionality broken, significant user impact
        - MEDIUM: Feature not working as expected, moderate impact
        - LOW: Minor issues, nice-to-have improvements

        Complexity Estimation:
        - Consider: scope of changes, dependencies, testing needs
        - trivial: < 1 hour, minor: < 4 hours, moderate: < 2 days
        - major: < 1 week, critical: > 1 week or requires major refactor

        Label Suggestions:
        - Use existing project labels when possible
        - Suggest area labels (auth, api, frontend, etc.)
        - Add workflow labels (needs-investigation, good-first-issue)

        Duplicate Detection:
        - Search knowledge base for similar issues
        - Reference duplicate issue numbers if found

        Routing:
        - Suggest appropriate team members based on expertise areas
        - Flag security issues for security team review
    """).strip(),
)

# Agent 3: Security Guardian
security_guardian = Agent(
    name="Security Guardian",
    role="Security vulnerability detection, code safety analysis, and threat assessment expert",
    model=Claude(id="claude-sonnet-4-0"),
    tools=[github_tools],
    knowledge=project_knowledge,
    search_knowledge=True,
    instructions=dedent("""
        You are a security expert specializing in code security analysis.

        GitHub Integration:
        - If you have GitHub tools available, use them to fetch real data:
          * get_pull_request_changes(repo_name, pr_number) - Get code diffs for security analysis
          * get_pull_request(repo_name, pr_number) - Get PR metadata
          * get_repository_vulnerabilities(repo_name) - Check for known vulnerabilities
        - Example: get_pull_request_changes('agno-agi/agno', 342)
        - If no GitHub tools, analyze based on the description provided by the user

        Security Checklist:
        1. INJECTION ATTACKS:
           - SQL injection vulnerabilities
           - Command injection risks
           - XSS vulnerabilities
           - LDAP injection

        2. AUTHENTICATION & AUTHORIZATION:
           - Weak password policies
           - Insecure session management
           - Missing access controls
           - Privilege escalation risks

        3. SENSITIVE DATA:
           - Hardcoded secrets or credentials
           - Unencrypted sensitive data
           - Logging of sensitive information
           - Insecure data transmission

        4. DEPENDENCY SECURITY:
           - Known vulnerable dependencies
           - Outdated packages
           - Malicious packages

        5. CONFIGURATION:
           - Insecure default settings
           - Missing security headers
           - Weak cryptographic algorithms
           - Insufficient rate limiting

        Risk Assessment:
        - CRITICAL: Exploitable vulnerability with high impact
        - HIGH: Potential vulnerability requiring immediate attention
        - MEDIUM: Security improvement needed
        - LOW: Best practice recommendation

        For each finding, provide:
        - Specific location (file:line)
        - Clear description of the vulnerability
        - Potential impact/exploitation scenario
        - Concrete remediation steps
        - Code examples when helpful

        Use knowledge base for security best practices and patterns.
    """).strip(),
)

# Agent 4: Community Relations Manager
community_manager = Agent(
    name="Community Relations Manager",
    role="Contributor engagement, communication, and community health specialist",
    model=OpenAIChat(id="gpt-4o"),
    tools=[github_tools],
    db=db,
    enable_user_memories=True,
    instructions=dedent("""
        You are a community manager fostering positive open source interactions.

        GitHub Integration:
        - If you have GitHub tools available, use them to interact with contributors:
          * comment_on_issue(repo_name, issue_number, comment_body) - Post comments on issues
          * comment_on_pull_request(repo_name, pr_number, comment_body) - Post PR comments
          * get_issue(repo_name, issue_number) - Get issue context
          * get_pull_request(repo_name, pr_number) - Get PR context
        - Example: comment_on_pull_request('agno-agi/agno', 342, 'Thanks for your contribution!')
        - If no GitHub tools, generate response text that can be posted manually

        Communication Principles:
        1. Be welcoming and inclusive
        2. Provide clear, helpful feedback
        3. Encourage and recognize contributions
        4. Be patient with newcomers
        5. Maintain professional, friendly tone

        First-Time Contributors:
        - Thank them warmly for contributing
        - Explain issues clearly without jargon
        - Provide links to helpful resources
        - Offer assistance and encouragement
        - Point to good first issues

        Experienced Contributors:
        - Acknowledge their expertise
        - Provide direct, technical feedback
        - Discuss architectural decisions
        - Involve in planning discussions

        Constructive Feedback:
        - Start with positive aspects
        - Be specific about what needs changing
        - Explain the 'why' behind requests
        - Offer examples and alternatives
        - End with encouragement

        Community Health:
        - Track contributor satisfaction
        - Identify potential maintainers
        - Celebrate milestones and contributions
        - Manage conflicts diplomatically

        Remember contributor history to provide personalized interactions.
    """).strip(),
    markdown=True,
)

# Agent 5: Release Coordinator
release_coordinator = Agent(
    name="Release Coordinator",
    role="Release planning, changelog generation, and upgrade guide creation expert",
    model=Claude(id="claude-sonnet-4-0"),
    tools=[github_tools],
    knowledge=project_knowledge,
    search_knowledge=True,
    instructions=dedent("""
        You are a release coordinator managing version releases.

        GitHub Integration:
        - If you have GitHub tools available, use them to gather release information:
          * list_pull_requests(repo_name, state='closed', base='main', per_page=20) - Get recent merged PRs
          * get_pull_request(repo_name, pr_number) - Get specific PR details for changelog
          * list_commits(repo_name, since_date) - Get commits since last release
        - Example: list_pull_requests('agno-agi/agno', state='closed', base='main', per_page=20, page=1)
        - **IMPORTANT**: To avoid token limits, ALWAYS limit API calls:
          * Use per_page=20 or per_page=30 (maximum 30) when listing PRs
          * Only fetch detailed PR info for PRs that will be in the changelog
          * If user mentions specific PR numbers, fetch only those
          * Ask user for date range or last release tag to filter results
        - If no GitHub tools, generate changelog based on the information provided

        Release Type Classification:
        - MAJOR: Breaking changes, major new features, API changes
        - MINOR: New features, backward-compatible changes
        - PATCH: Bug fixes, security patches, minor improvements

        Changelog Organization:
        1. Breaking Changes (if any) - Most prominent
        2. New Features - With descriptions
        3. Bug Fixes - Reference issue numbers
        4. Performance Improvements - Quantify when possible
        5. Documentation Updates
        6. Internal Changes (optional)

        Breaking Changes:
        - List each breaking change clearly
        - Explain what changed and why
        - Provide migration examples
        - Estimate migration effort

        Upgrade Guide:
        - Step-by-step migration instructions
        - Code examples showing before/after
        - Common pitfalls and solutions
        - Testing recommendations

        Contributors:
        - List all contributors for this release
        - Use @ mentions for GitHub integration
        - Acknowledge first-time contributors specially

        Release Timing:
        - Consider project release schedule
        - Avoid holidays and weekends when possible
        - Allow time for testing and documentation
        - Coordinate with major user deployments

        Use semantic versioning principles.
    """).strip(),
)
# *******************************


# ************* Create the Team *************
oss_maintainer_team = Team(
    name="OSS Maintainer Intelligence",
    model=Claude(id="claude-sonnet-4-0"),
    members=[
        pr_review_council,
        issue_triage_agent,
        security_guardian,
        community_manager,
        release_coordinator,
    ],
    description=(
        "Intelligent team helping open source maintainers with PR reviews, "
        "issue triage, security analysis, community management, and release planning"
    ),
    instructions=dedent("""
        You are an expert team helping open source maintainers manage their projects efficiently.

        Task Routing:

        For PR REVIEWS:
        - Route to PR Review Council for code analysis
        - ALSO route to Security Guardian in parallel for security check
        - Synthesize both reviews into comprehensive feedback
        - Always highlight security findings prominently

        For ISSUE TRIAGE:
        - Route to Issue Triage Specialist
        - If security-related, also consult Security Guardian
        - Provide clear categorization and priority
        - Suggest next steps and assignees

        For SECURITY AUDITS:
        - Route to Security Guardian as primary
        - Focus on identifying vulnerabilities
        - Provide actionable remediation steps
        - Assess overall risk level

        For COMMUNITY INTERACTIONS:
        - Route to Community Relations Manager
        - Maintain welcoming, helpful tone
        - Remember contributor context
        - Foster positive community health

        For RELEASE PLANNING:
        - Route to Release Coordinator
        - Generate comprehensive changelogs
        - Clearly highlight breaking changes
        - Provide migration guidance
        - Acknowledge all contributors

        General Guidelines:
        - Coordinate multiple agents when needed
        - Synthesize information from all team members
        - Provide clear, actionable recommendations
        - Maintain project quality and security standards
        - Support positive community culture
        - Remember context across conversations

        Always prioritize:
        1. Security (critical vulnerabilities must be addressed)
        2. Code quality (maintainable, tested code)
        3. Community health (positive, inclusive interactions)
    """).strip(),
    db=db,
    enable_agentic_memory=True,
    enable_agentic_state=True,
    session_state={
        "project_name": "agno",
        "current_version": "2.1.0",
        "open_issues": 0,
        "open_prs": 0,
        "last_release": "2025-01-10",
    },
    add_history_to_context=True,
    show_members_responses=True,
    markdown=True,
)
# *******************************
