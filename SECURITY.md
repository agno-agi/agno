# Security Policy

Agno helps developers build agents, teams, and workflows and run them through AgentOS. We welcome reports of vulnerabilities that could compromise the confidentiality, integrity, or availability of Agno applications or their data.

## Report a vulnerability privately

Please report suspected vulnerabilities through **GitHub's private vulnerability reporting for this repository (GHSA)**:

**[Report a vulnerability](https://github.com/agno-agi/agno/security/advisories/new)**

Sign in to GitHub, open the reporting form, and submit your findings privately to the maintainers. Use the private report for follow-up information and disclosure coordination.

**Do not disclose suspected vulnerabilities in public issues, discussions, pull requests, or community channels.** Ordinary bugs and feature requests that do not expose a security issue can use the public issue tracker. If you are unsure whether a finding is security-sensitive, report it privately.

## Scope

This policy covers code maintained in `agno-agi/agno`, including:

- The Agno Python SDK and its agents, teams, workflows, memory, knowledge, and storage integrations.
- The AgentOS runtime and its APIs, MCP server, interfaces, authentication, authorization, and run lifecycle.
- Agno-maintained toolkits, connectors, file handling, and examples in this repository where a defect introduces a security risk.

Reports of particular interest include:

- Bypasses of authentication, permissions, token validation, or configured user isolation.
- Unauthorized access to another user's sessions, memory, knowledge, files, traces, or runs, including concurrency-related data leakage.
- Bypasses of configured tool permissions, confirmation requirements, or administrator approvals, including during run continuation or resumption.
- Unintended code execution, injection, unsafe file access, or server-side requests caused by Agno's handling of untrusted input.
- Exposure of credentials or sensitive data through Agno-controlled APIs, logs, traces, or telemetry.
- Availability defects with practical security impact under realistic deployment conditions.

This repository policy does not grant permission to test Agno-hosted services, the hosted Control Plane, other repositories, or third-party deployments. Follow the affected project's reporting policy where available. If ownership is unclear and Agno code may be involved, submit a private report here so maintainers can assess where it belongs.

## Agent-specific security boundaries

Agents may consume untrusted prompts, retrieved documents, tool responses, and MCP content. Explain how your finding turns that input into unauthorized access, execution, disclosure, modification, or a bypass of an enforced control.

**Prompt injection is not automatically out of scope.** Reports demonstrating a defect in Agno's enforcement of permissions, approvals, isolation, or data boundaries are security-relevant, even when prompt injection is the entry point.

Unexpected model output, hallucinations, or instruction-following failures without security impact are generally model-quality issues. Likewise, an intentionally enabled execution tool performing its documented function does not, by itself, establish an Agno vulnerability. These distinctions do not exclude reports about unsafe defaults, misleading security guarantees, or defects in Agno-provided protections.

Python and shell execution tools must not be treated as security sandboxes. Deployers remain responsible for selecting trusted integrations, limiting tool privileges and credentials, isolating execution, and configuring authentication, user isolation, database access, and network controls for their deployment.

## What to include

Please provide as much of the following as you can:

- A concise description of the issue and its security impact.
- The affected Agno version or commit, Python version, and relevant dependencies.
- The affected component and deployment configuration, including authentication mode, permissions, user-isolation settings, enabled tools, and approval requirements where relevant.
- The attacker's starting access, the input they control, and the security boundary affected.
- A minimal reproduction in an isolated environment, with expected and observed behavior. For model-dependent findings, include the model/provider and whether the behavior is repeatable.
- Sanitized logs or supporting evidence, and any known mitigation.
- Whether the issue is already public or known to be actively exploited, and any disclosure timing constraints.
- Your preferred attribution, or a request to remain anonymous.

Do not include live credentials, private keys, or other people's personal or confidential data. Use synthetic data and redact sensitive material. Incomplete reports are welcome; you do not need to identify a fix or assign a severity score before reporting.

## Versions and fixes

Use the latest stable Agno release and keep dependencies updated. Where practical, check whether the issue is present in the latest stable release, but do not delay a report to do so.

Reports affecting older releases are welcome. Fix availability and any backports will be assessed during triage; this policy does not promise security maintenance for every historical release. Published advisories will identify known affected versions, patched versions, and available mitigations.

## Coordinated disclosure

Maintainers will use the private GitHub report to discuss impact, request additional information, and coordinate remediation and publication. Please allow a reasonable opportunity to investigate and address the issue before publishing technical details, and discuss proposed disclosure dates in the report.

For confirmed vulnerabilities, the aim is to publish a GitHub Security Advisory describing the impact, affected versions, fixes or mitigations, and reporter credit where requested. Response and remediation times depend on severity, complexity, and maintainer availability; this policy does not guarantee a fixed timeline or payment.

## Responsible research

Test only systems you own or have explicit permission to assess. Prefer local, isolated environments and synthetic data. Avoid service disruption, bulk data access, persistence, social engineering, and changes to other people's data. If you encounter data that is not yours, stop testing and report the exposure privately without accessing or retaining more than necessary.

This policy is a reporting and disclosure process, not authorization to access systems or a grant of legal safe harbor.

## Security updates

Review [Agno security advisories](https://github.com/agno-agi/agno/security/advisories) and [release notes](https://github.com/agno-agi/agno/releases) for published fixes and upgrade guidance.
