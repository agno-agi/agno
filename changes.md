# PubMed Tool Enhancement for Agno AI Agents

## Recent Improvements to the PubMed Tool

The `PubmedTools` class has been significantly enhanced to provide richer data extraction from PubMed articles, improving its utility for AI agents requiring scientific and medical information.

### Key Improvements

#### 1. Enhanced Metadata Extraction

The updated tool now extracts a comprehensive set of metadata for each article:

- **Author Information**: First author details are now properly formatted
- **DOI and URLs**: Direct links to both PubMed entries and full-text articles
- **Richer Context**: Journal names, publication types, keywords, and MeSH terms
- **Publication Details**: Year of publication and article type classification

```python
articles.append({
    "Published": pub_date.text if pub_date is not None else "No date available",
    "Title": title.text if title is not None else "No title available",
    "Summary": abstract_text,
    "First_Author": first_author,  # New field
    "DOI": doi,  # New field
    "PubMed_URL": pubmed_url,  # New field
    "Full_Text_URL": full_text_url,  # New field
    "Keywords": ", ".join(keywords) if keywords else "No keywords available",  # New field
    "MeSH_Terms": ", ".join(mesh_terms) if mesh_terms else "No MeSH terms available",  # New field
    "Journal": journal,  # New field
    "Publication_Type": ", ".join(pub_types) if pub_types else "Not specified"  # New field
})
```

#### 2. Improved Abstract Handling

The tool now intelligently processes structured abstracts, preserving section labels (Methods, Results, Conclusions) for more organized content:

```python
# Handle abstract sections with labels (methods, results, etc.)
abstract_sections = article.findall(".//AbstractText")
abstract_text = ""
if abstract_sections:
    for section in abstract_sections:
        label = section.get("Label", "")
        if label:
            abstract_text += f"{label}: {section.text}\n\n"
        else:
            abstract_text += f"{section.text}\n\n"
    abstract_text = abstract_text.strip()
```

#### 3. Rich Search Results Formatting

Search results now include all extracted metadata in a readable format:

```python
article_text = (
    f"Published: {article.get('Published')}\n"
    f"Title: {article.get('Title')}\n"
    f"First Author: {article.get('First_Author')}\n"
    f"Journal: {article.get('Journal')}\n"
    f"Publication Type: {article.get('Publication_Type')}\n"
    f"DOI: {article.get('DOI')}\n"
    f"PubMed URL: {article.get('PubMed_URL')}\n"
    f"Full Text URL: {article.get('Full_Text_URL')}\n"
    f"Keywords: {article.get('Keywords')}\n"
    f"MeSH Terms: {article.get('MeSH_Terms')}\n"
    f"Summary:\n{article.get('Summary')}"
)
```

## Benefits for Agno AI Agents

### Enhanced Information Retrieval

These improvements make Agno a more capable platform for building multimodal agents by:

1. **Providing Direct Access to Sources**: Agents can now reference original publications via PubMed URLs and DOI links
2. **Enabling Domain-Specific Context**: MeSH terms and keywords allow agents to better understand medical/scientific context
3. **Supporting Evidence-Based Responses**: Structured abstracts help agents distinguish between methods, results, and conclusions
4. **Facilitating Literature Analysis**: Comprehensive metadata enables better filtering and aggregation of research findings

### Use Case Examples

- **Medical Research Assistants**: Agents can quickly gather and summarize recent research on specific medical conditions
- **Scientific Literature Review**: Agents can process large volumes of publications to identify trends and consensus
- **Clinical Decision Support**: Agents can find relevant evidence-based guidelines and recent studies

## Documentation and Examples

### Example 1: Creating a PubMed-powered Research Assistant

```python
from agno.agent import Agent
from agno.tools.pubmed import PubmedTools

# Create a research agent with PubMed capabilities
researcher = Agent(
    name="MedicalResearcher",
    description="I help researchers find and summarize the latest medical research",
    tools=[PubmedTools(email="your_email@example.com", max_results=5)]
)

# Example query to research recent findings
response = researcher.run(
    "What are the latest findings on the effectiveness of mRNA vaccines?"
)
print(response)
```

### Example 2: Comparing Multiple Research Topics

```python
from agno.agent import Agent
from agno.tools.pubmed import PubmedTools
from agno.memory import ConversationMemory

# Create a comparative research agent
comparative_researcher = Agent(
    name="ComparativeAnalysis",
    description="I help compare research findings across different medical topics",
    tools=[PubmedTools(email="your_email@example.com", max_results=3)],
    memory=ConversationMemory()
)

# Compare research on different treatment approaches
result = comparative_researcher.run("""
Please compare the latest research on:
1. Cognitive behavioral therapy for anxiety
2. SSRI medications for anxiety
Focus on effectiveness, side effects, and long-term outcomes.
""")
```

### Example 3: Specialized Medical Literature Bot

```python
from agno.agent import Agent
from agno.tools.pubmed import PubmedTools
from agno.llms import OpenAI

# Create a specialized oncology research agent
oncology_researcher = Agent(
    name="OncologyResearcher",
    llm=OpenAI(model="gpt-4o"),
    tools=[PubmedTools(email="your_email@example.com", max_results=10)],
    system_prompt="""
    You are an expert oncology researcher. Use the PubMed tool to find relevant 
    research on cancer treatments, diagnostics, and outcomes. When analyzing 
    studies, consider:
    
    1. Study design and sample size
    2. Statistical significance of findings
    3. Potential conflicts of interest
    4. Applicability to different patient populations
    
    Present your findings in a clear, structured format with citations.
    """
)

# Research immunotherapy effectiveness
response = oncology_researcher.run(
    "What are the latest advances in CAR-T cell therapy for solid tumors?"
)
```

## Recommended Cookbook Examples

- **Scientific Research Assistant**: Building an agent that can search and summarize scientific literature
- **Medical Question Answering**: Creating an agent that can answer medical questions with evidence from PubMed
- **Literature Review Bot**: Automating systematic literature reviews across multiple database sources
- **Clinical Trial Finder**: Helping researchers identify relevant clinical trials based on specific criteria
- **Medical Education Support**: Creating agents that can provide medical students with latest research on topics they're studying

## Future Improvements

- Integration with other scientific databases (e.g., arXiv, EMBASE)
- Full-text retrieval for open-access articles
- Citation network analysis to identify seminal papers
- Automated evidence grading and quality assessment
- Meta-analysis capabilities to synthesize findings across multiple studies
- Integration with medical knowledge graphs for enhanced context

By enhancing the PubMed tool, Agno has significantly improved its capabilities for building AI agents that can browser and analyze scientific literature in a more informed and context-aware manner.