# Research Agent Workflow in OSOP Format
# OSOP = Open Standard Operating Process
# Spec: https://github.com/Archie0125/osop-spec
#
# This is the PORTABLE definition of the workflow. It describes WHAT should
# happen, step by step, in a tool-agnostic way. The same .osop file can be
# understood by any compatible runtime (Agno, LangChain, CrewAI, ...).
# The runnable Agno implementation lives in research_workflow.py.

osop_version: "1.0"
id: agno-research-agent
name: Agno Research Agent Workflow
description: A multi-step research agent — web search, analysis, and report generation — expressed as a portable OSOP workflow.
tags: [agno, agent, research, web-search, osop]

nodes:
  - id: user-request
    type: human
    name: User Request
    description: User provides a research topic or question.

  - id: web-search
    type: agent
    name: Web Search Agent
    description: Search the web for relevant, up-to-date information on the topic.
    runtime:
      provider: openai
      model: gpt-4o
      config:
        tools: [duckduckgo_search]

  - id: analyze
    type: agent
    name: Analysis Agent
    description: Analyze the search results and extract the key insights.
    runtime:
      provider: openai
      model: gpt-4o
      config:
        temperature: 0.2

  - id: generate-report
    type: agent
    name: Report Generator
    description: Compile the findings into a structured research report.
    runtime:
      provider: openai
      model: gpt-4o
      config:
        temperature: 0.5

  - id: deliver
    type: api
    name: Deliver Report
    description: Return the final report to the user.

edges:
  - from: user-request
    to: web-search
    mode: sequential
  - from: web-search
    to: analyze
    mode: sequential
  - from: analyze
    to: generate-report
    mode: sequential
  - from: generate-report
    to: deliver
    mode: sequential
