"""👨‍🍳 Recipe Creator - Your Personal AI Chef!

This example shows how to create an intelligent recipe recommendation system that provides
detailed, personalized recipes based on your ingredients, dietary preferences, and time constraints.
The agent combines culinary knowledge, nutritional data, and cooking techniques to deliver
comprehensive cooking instructions.

Example prompts to try:
- "I have chicken, rice, and vegetables. What can I make in 30 minutes?"
- "Create a vegetarian pasta recipe with mushrooms and spinach"
- "Suggest healthy breakfast options with oats and fruits"
- "What can I make with leftover turkey and potatoes?"
- "Need a quick dessert recipe using chocolate and bananas"

Run: `pip install openai exa_py agno` to install the dependencies
"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.exa import ExaTools

recipe_agent = Agent(
    name="ChefGenius",
    tools=[ExaTools()],
    model=OpenAIChat(id="gpt-4o"),
    description=dedent("""\
        You are ChefGenius, a passionate and knowledgeable culinary expert with expertise in global cuisine! 🍳

        Your mission is to help users create delicious meals by providing detailed,
        personalized recipes based on their available ingredients, dietary restrictions,
        and time constraints. You combine deep culinary knowledge with nutritional wisdom
        to suggest recipes that are both practical and enjoyable."""),
    instructions=dedent("""\
        Approach each recipe recommendation with these steps:

        1. Analysis Phase 📋
           - Understand available ingredients
           - Consider dietary restrictions
           - Note time constraints
           - Factor in cooking skill level
           - Check for kitchen equipment needs

        2. Recipe Selection 🔍
           - Use Exa to search for relevant recipes
           - Ensure ingredients match availability
           - Verify cooking times are appropriate
           - Consider seasonal ingredients
           - Check recipe ratings and reviews

        3. Detailed Information 📝
           - Recipe title and cuisine type
           - Preparation time and cooking time
           - Complete ingredient list with measurements
           - Step-by-step cooking instructions
           - Nutritional information per serving
           - Difficulty level
           - Serving size
           - Storage instructions

        4. Extra Features ✨
           - Ingredient substitution options
           - Common pitfalls to avoid
           - Plating suggestions
           - Wine pairing recommendations
           - Leftover usage tips
           - Meal prep possibilities

        Presentation Style:
        - Use clear markdown formatting
        - Present ingredients in a structured list
        - Number cooking steps clearly
        - Add emoji indicators for:
          🌱 Vegetarian
          🌿 Vegan
          🌾 Gluten-free
          🥜 Contains nuts
          ⏱️ Quick recipes
        - Include tips for scaling portions
        - Note allergen warnings
        - Highlight make-ahead steps
        - Suggest side dish pairings"""),
    markdown=True,
    add_datetime_to_context=True,
)

# Example usage with different types of recipe queries
recipe_agent.print_response(
    "I have chicken breast, broccoli, garlic, and rice. Need a healthy dinner recipe that takes less than 45 minutes.",
    stream=True,
)

# More example prompts to explore:
"""
Quick Meals:
1. "15-minute dinner ideas with pasta and vegetables"
2. "Quick healthy lunch recipes for meal prep"
3. "Easy breakfast recipes with eggs and avocado"
4. "No-cook dinner ideas for hot summer days"

Dietary Restrictions:
1. "Keto-friendly dinner recipes with salmon"
2. "Gluten-free breakfast options without eggs"
3. "High-protein vegetarian meals for athletes"
4. "Low-carb alternatives to pasta dishes"

Special Occasions:
1. "Impressive dinner party main course for 6 people"
2. "Romantic dinner recipes for two"
3. "Kid-friendly birthday party snacks"
4. "Holiday desserts that can be made ahead"

International Cuisine:
1. "Authentic Thai curry with available ingredients"
2. "Simple Japanese recipes for beginners"
3. "Mediterranean diet dinner ideas"
4. "Traditional Mexican recipes with modern twists"

Seasonal Cooking:
1. "Summer salad recipes with seasonal produce"
2. "Warming winter soups and stews"
3. "Fall harvest vegetable recipes"
4. "Spring picnic recipe ideas"

Batch Cooking:
1. "Freezer-friendly meal prep recipes"
2. "One-pot meals for busy weeknights"
3. "Make-ahead breakfast ideas"
4. "Bulk cooking recipes for large families"
"""
