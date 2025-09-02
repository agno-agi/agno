# 🚀 Investment Analysis Workflow

A sophisticated investment analysis system for advanced research capabilities using workflows.

## 📋 **Overview**

This workflow demonstrates how to build a comprehensive investment analysis workflow. It combines 8 specialized agents in an adaptive and intelligent analysis workflow that can handle everything from simple stock evaluations to complex multi-company investment decisions.

## 🚀 **Getting Started**

### **Prerequisites**
- A Supabase API key. You can get one from https://supabase.com/dashboard/account/tokens.
- OpenAI API key

### **Setup**
```bash
export SUPABASE_ACCESS_TOKEN="your-supabase-token"
export OPENAI_API_KEY="your-openai-key"
```

Install packages
```
pip install agno mcp openai
```


## 🏗️ **Analysis Flow**

This workflow is designed like a sophisticated investment firm's research process. Here are the steps:

```
Investment Analysis Journey
├── 🗄️  Database Setup (Always first)
│   └── Creates Supabase project & schema
├── 🔍 Company Research (Foundation)
│   └── Gathers basic company data
├── 🔀 Multi-Company Smart Pipeline
│   └── If analyzing multiple companies:
│       ├── 🔄 Iterative Company Loop (up to 5 rounds)
│       └── ⚡ Parallel Comparative Analysis
├── 🎯 Risk Assessment Routing
│   └── Picks specialized risk framework
├── 💰 Valuation Strategy Selection
│   └── Chooses valuation approach by investment type
├── ⚠️  High-Risk Deep Dive
│   └── If high-risk investment detected:
│       ├── ⚡ Parallel Risk Modeling
│       └── 🔄 Risk Refinement Loop (up to 3 rounds)
├── 🏢 Large Investment Due Diligence
│   └── If $50M+ investment:
│       └── ⚡ Parallel regulatory, market & management analysis
├── 🌱 ESG Analysis Pipeline
│   └── If ESG analysis requested:
│       └── Sequential ESG assessment & integration
├── 📊 Market Context Analysis
│   └── If market analysis needed:
│       └── ⚡ Parallel market & sector analysis
└── 📝 Investment Decision & Reporting
    ├── 🔄 Consensus Building Loop (up to 2 rounds)
    └── 📊 Final Report Synthesis
```

The workflow is adaptive. For e.g when Analyzing a single blue-chip stock a simple streamlined path is followed but for complex evaluations involving multiple companies the workflow automatically triggers deeper analysis.
