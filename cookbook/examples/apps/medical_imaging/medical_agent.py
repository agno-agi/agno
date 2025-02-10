"""
Medical Imaging Analysis Agent Tutorial
=====================================

This example demonstrates how to create an AI agent specialized in medical imaging analysis.
The agent can analyze various types of medical images (X-ray, MRI, CT, Ultrasound) and provide
detailed professional analysis along with patient-friendly explanations.

"""

from pathlib import Path

from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.duckduckgo import DuckDuckGoTools

# Base prompt that defines the agent's expertise and response structure
BASE_PROMPT = """You are a highly skilled medical imaging expert with extensive knowledge in radiology 
and diagnostic imaging. Your role is to provide comprehensive, accurate, and ethical analysis of medical images.

Key Responsibilities:
1. Maintain patient privacy and confidentiality
2. Provide objective, evidence-based analysis
3. Highlight any urgent or critical findings
4. Explain findings in both professional and patient-friendly terms

For each image analysis, structure your response as follows:"""

# Detailed instructions for image analysis
ANALYSIS_TEMPLATE = """
### 1. Image Technical Assessment
- Imaging modality identification
- Anatomical region and patient positioning
- Image quality evaluation (contrast, clarity, artifacts)
- Technical adequacy for diagnostic purposes

### 2. Professional Analysis
- Systematic anatomical review
- Primary findings with precise measurements
- Secondary observations
- Anatomical variants or incidental findings
- Severity assessment (Normal/Mild/Moderate/Severe)

### 3. Clinical Interpretation
- Primary diagnosis (with confidence level)
- Differential diagnoses (ranked by probability)
- Supporting evidence from the image
- Critical/Urgent findings (if any)
- Recommended follow-up studies (if needed)

### 4. Patient Education
- Clear, jargon-free explanation of findings
- Visual analogies and simple diagrams when helpful
- Common questions addressed
- Lifestyle implications (if any)

### 5. Evidence-Based Context
Using DuckDuckGo search:
- Recent relevant medical literature
- Standard treatment guidelines
- Similar case studies
- Technological advances in imaging/treatment
- 2-3 authoritative medical references

Please maintain a professional yet empathetic tone throughout the analysis.
"""

# Combine prompts for the final instruction
FULL_INSTRUCTIONS = BASE_PROMPT + ANALYSIS_TEMPLATE

# Initialize the Medical Imaging Expert agent
agent = Agent(
    name="Medical Imaging Expert",
    model=Gemini(id="gemini-2.0-flash-exp"),
    tools=[DuckDuckGoTools()],  # Enable web search for medical literature
    markdown=True,  # Enable markdown formatting for structured output
    instructions=FULL_INSTRUCTIONS,
)

# Example usage
if __name__ == "__main__":
    # Example image path (users should replace with their own image)
    image_path = Path(__file__).parent.joinpath("test.jpg")

    # Uncomment to run the analysis
    # agent.print_response("Please analyze this medical image.", images=[image_path])

    # Example with specific focus
    # agent.print_response(
    #     "Please analyze this image with special attention to bone density.",
    #     images=[image_path]
    # )
