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

#### 3. Configurable Results Format

A new `results_expanded` parameter has been added to allow users to choose between comprehensive and concise output formats:

```python
def __init__(
    self,
    email: str = "your_email@example.com",
    max_results: Optional[int] = None,
    results_expanded: bool = True,  # New parameter
):
    super().__init__(name="pubmed")
    self.max_results: Optional[int] = max_results
    self.email: str = email
    self.results_expanded: bool = results_expanded  # Store the parameter
```

The search method now uses this parameter to format results appropriately:

```python
# Create result strings based on configured detail level
results = []
for article in articles:
    if self.results_expanded:
        # Comprehensive format with all metadata
        article_text = (
            f"Published: {article.get('Published')}\n"
            f"Title: {article.get('Title')}\n"
            # ... full detailed format
        )
    else:
        # Concise format with just essential information
        article_text = (
            f"Title: {article.get('Title')}\n"
            f"Published: {article.get('Published')}\n"
            f"Summary: {article.get('Summary')[:200]}..." if len(article.get('Summary', '')) > 200 
            else f"Summary: {article.get('Summary')}"
        )
```

## Benefits for Agno AI Agents

### Enhanced Information Retrieval

These improvements make Agno a more capable platform for building multimodal agents by:

1. **Providing Direct Access to Sources**: Agents can now reference original publications via PubMed URLs and DOI links
2. **Enabling Domain-Specific Context**: MeSH terms and keywords allow agents to better understand medical/scientific context
3. **Supporting Evidence-Based Responses**: Structured abstracts help agents distinguish between methods, results, and conclusions
4. **Facilitating Literature Analysis**: Comprehensive metadata enables better filtering and aggregation of research findings
5. **Flexible Output Formats**: The configurable output allows for both detailed analysis and concise summaries depending on the agent's needs

### Use Case Examples

- **Medical Research Assistants**: Agents can quickly gather and summarize recent research on specific medical conditions
- **Scientific Literature Review**: Agents can process large volumes of publications to identify trends and consensus
- **Clinical Decision Support**: Agents can find relevant evidence-based guidelines and recent studies
- **Quick Reference Tools**: Using the concise format for rapid information retrieval when complete details aren't needed

## Documentation and Examples

### Example 1: Creating a PubMed-powered Research Assistant (Expanded Results)

```python
from agno.agent import Agent
from agno.tools.pubmed import PubmedTools

# Create a research agent with detailed PubMed results (default behavior)
researcher = Agent(
    name="MedicalResearcher",
    description="I help researchers find and summarize the latest medical research",
    tools=[PubmedTools(
        email="your_email@example.com", 
        max_results=5,
        results_expanded=True  # Default setting - comprehensive output
    )]
)

# Example query to research recent findings
response = researcher.run(
    "What are the latest findings on the effectiveness of mRNA vaccines?"
)
print(response)
```

### Example 2: Concise Research Results

```python
from agno.agent import Agent
from agno.tools.pubmed import PubmedTools
from agno.memory import ConversationMemory

# Create a comparative research agent with concise output
comparative_researcher = Agent(
    name="QuickResearcher",
    description="I provide quick research summaries on medical topics",
    tools=[PubmedTools(
        email="your_email@example.com", 
        max_results=3,
        results_expanded=False  # Use concise format for simpler output
    )],
    memory=ConversationMemory()
)

# Get brief overview of research
result = comparative_researcher.run(
    "Give me a quick overview of recent diabetes research"
)
```

### Example 3: Specialized Medical Literature Bot

```python
from agno.agent import Agent
from agno.tools.pubmed import PubmedTools
from agno.llms import OpenAI

# Create a specialized oncology research agent with detailed output
oncology_researcher = Agent(
    name="OncologyResearcher",
    llm=OpenAI(model="gpt-4o"),
    tools=[PubmedTools(
        email="your_email@example.com", 
        max_results=10,
        results_expanded=True  # Comprehensive output for detailed analysis
    )],
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
- **Quick Research Briefing**: Using the concise format for rapid information scanning across multiple topics

## Future Improvements

- Integration with other scientific databases (e.g., arXiv, EMBASE)
- Full-text retrieval for open-access articles
- Citation network analysis to identify seminal papers
- Automated evidence grading and quality assessment
- Meta-analysis capabilities to synthesize findings across multiple studies
- Integration with medical knowledge graphs for enhanced context
- Additional output format options for specific use cases

By enhancing the PubMed tool, Agno has significantly improved its capabilities for building AI agents that can navigate and leverage scientific literature in a more informed and context-aware manner, with flexible output options to suit different needs.