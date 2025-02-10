from typing import List, Dict
from dataclasses import dataclass
from agno.agent import Agent, RunResponse
from agno.models.openai import OpenAIChat
from agno.tools.dalle import DalleTools


@dataclass
class InfographicSection:
    text: str
    style: Dict
    position: Dict[str, int]


class InfographicAgent():
    def __init__(self):
        self.agent = Agent(
            model=OpenAIChat(id="gpt-4"),
            tools=[DalleTools()],
            description="Agent that converts text into presentation-ready infographics",
            instructions=[
                "Create a visually appealing infographic image",
                "Use a clean, modern design with good contrast",
                "Include appropriate icons or visual elements for each point",
                "Ensure text is readable and well-organized",
                "Use a consistent color scheme throughout",
                "Make the infographic suitable for presentation slides"
            ]
        )

    def process_text(self, text: str) -> List[InfographicSection]:
        sections = []
        paragraphs = text.split('\n\n')

        for i, para in enumerate(paragraphs):
            sections.append(InfographicSection(
                text=para,
                style={
                    "font_size": 16,  # Increased for better readability
                    "color": "#2C3E50",  # Dark blue for better contrast
                    "background": "#FFFFFF",
                    "border_radius": "8px",
                    "padding": "15px",
                    "box_shadow": "0 2px 4px rgba(0,0,0,0.1)"
                },
                position={"x": 50 + (i * 250), "y": 50 + (i * 150)}  # More spread out layout
            ))
        return sections

    def create_infographic(self, text: str) -> RunResponse:
        sections = self.process_text(text)
        image_prompt = self._generate_image_prompt(sections)
        result = self.agent.run(image_prompt)
        return result

    def _generate_image_prompt(self, sections: List[InfographicSection]) -> str:
        prompt = "Create a modern, professional infographic with these specifications:\n"
        prompt += "- Use a 16:9 aspect ratio suitable for presentation slides\n"
        prompt += "- Apply a clean, minimalist design with subtle gradients\n"
        prompt += "- Include relevant icons for each section\n"
        prompt += "- Use a cohesive color palette with good contrast\n\n"
        
        for i, section in enumerate(sections):
            prompt += f"Section {i+1}:\n"
            prompt += f"Content: {section.text}\n"
            prompt += "Visual style: Modern, clean layout with icons and data visualization where appropriate\n"
            prompt += f"Position: At {section.position['x']},{section.position['y']}\n\n"
        
        prompt += "Important requirements:\n"
        prompt += "- Ensure all text is clearly readable\n"
        prompt += "- Use professional fonts\n"
        prompt += "- Include smooth transitions between sections\n"
        prompt += "- Add subtle visual elements to enhance engagement"
        return prompt


infographic_agent = InfographicAgent()
response = infographic_agent.create_infographic(
    "World is going through a fat pandemic. The number of obese people is increasing. " +
    "In USA, 42.4% of adults are obese. In Europe, it is 21.6%. In China, it is 18.5%. In India, it is 13.5%."
)
print(response)