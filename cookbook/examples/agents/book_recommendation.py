"""📚 Book Recommendation Agent - Your Personal Literary Curator!

This example shows how to create an intelligent book recommendation system that provides
comprehensive literary suggestions based on your preferences. The agent combines book databases,
ratings, reviews, and upcoming releases to deliver personalized reading recommendations.

Example prompts to try:
- "I loved 'The Seven Husbands of Evelyn Hugo' and 'Daisy Jones & The Six', what should I read next?"
- "Recommend me some psychological thrillers like 'Gone Girl' and 'The Silent Patient'"
- "What are the best fantasy books released in the last 2 years?"
- "I enjoy historical fiction with strong female leads, any suggestions?"
- "Looking for science books that read like novels, similar to 'The Immortal Life of Henrietta Lacks'"

Run: `pip install openai exa_py agno` to install the dependencies
"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.exa import ExaTools

book_recommendation_agent = Agent(
    name="Shelfie",
    tools=[ExaTools()],
    model=OpenAIChat(id="gpt-4o"),
    description=dedent("""\
        You are Shelfie, a passionate and knowledgeable literary curator with expertise in books worldwide! 📚

        Your mission is to help readers discover their next favorite books by providing detailed,
        personalized recommendations based on their preferences, reading history, and the latest
        in literature. You combine deep literary knowledge with current ratings and reviews to suggest
        books that will truly resonate with each reader."""),
    instructions=dedent("""\
        Approach each recommendation with these steps:

        1. Analysis Phase 📖
           - Understand reader preferences from their input
           - Consider mentioned favorite books' themes and styles
           - Factor in any specific requirements (genre, length, content warnings)

        2. Search & Curate 🔍
           - Use Exa to search for relevant books
           - Ensure diversity in recommendations
           - Verify all book data is current and accurate

        3. Detailed Information 📝
           - Book title and author
           - Publication year
           - Genre and subgenres
           - Goodreads/StoryGraph rating
           - Page count
           - Brief, engaging plot summary
           - Content advisories
           - Awards and recognition

        4. Extra Features ✨
           - Include series information if applicable
           - Suggest similar authors
           - Mention audiobook availability
           - Note any upcoming adaptations

        Presentation Style:
        - Use clear markdown formatting
        - Present main recommendations in a structured table
        - Group similar books together
        - Add emoji indicators for genres (📚 🔮 💕 🔪)
        - Minimum 5 recommendations per query
        - Include a brief explanation for each recommendation
        - Highlight diversity in authors and perspectives
        - Note trigger warnings when relevant"""),
    markdown=True,
    add_datetime_to_instructions=True,
    show_tool_calls=True,
)

# Example usage with different types of book queries
book_recommendation_agent.print_response(
    "I really enjoyed 'Anxious People' and 'Lessons in Chemistry', can you suggest similar books?",
    stream=True,
)

# More example prompts to explore:
"""
Genre-specific queries:
1. "Recommend contemporary literary fiction like 'Beautiful World, Where Are You'"
2. "What are the best fantasy series completed in the last 5 years?"
3. "Find me atmospheric gothic novels like 'Mexican Gothic' and 'Ninth House'"
4. "What are the most acclaimed debut novels from this year?"

Contemporary Issues:
1. "Suggest books about climate change that aren't too depressing"
2. "What are the best books about artificial intelligence for non-technical readers?"
3. "Recommend memoirs about immigrant experiences"
4. "Find me books about mental health with hopeful endings"

Book Club Selections:
1. "What are good book club picks that spark discussion?"
2. "Suggest literary fiction under 350 pages"
3. "Find thought-provoking novels that tackle current social issues"
4. "Recommend books with multiple perspectives/narratives"

Upcoming Releases:
1. "What are the most anticipated literary releases next month?"
2. "Show me upcoming releases from my favorite authors"
3. "What debut novels are getting buzz this season?"
4. "List upcoming books being adapted for screen"
"""
