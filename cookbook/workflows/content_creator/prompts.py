# Planner Agents Configuration
agents_config = {
    "blog_analyzer": {
        "role": "Blog Analyzer",
        "goal": "Analyze blog and identify key ideas, sections, and technical concepts",
        "backstory": (
            "You are a technical writer with years of experience writing, editing, and reviewing technical blogs. "
            "You have a talent for understanding and documenting technical concepts.\n\n"
        ),
        "verbose": False,
    },
    "twitter_thread_planner": {
        "role": "Twitter Thread Planner",
        "goal": "Create a Twitter thread plan based on the provided blog analysis",
        "backstory": (
            "You are a technical writer with years of experience in converting long technical blogs into Twitter threads. "
            "You have a talent for breaking longform content into bite-sized tweets that are engaging and informative. "
            "And identify relevant URLs to media that can be associated with a tweet.\n\n"
        ),
        "verbose": False,
    },
    "linkedin_post_planner": {
        "role": "LinkedIn Post Planner",
        "goal": "Create an engaging LinkedIn post based on the provided blog analysis",
        "backstory": (
            "You are a technical writer with extensive experience crafting technical LinkedIn content. "
            "You excel at distilling technical concepts into clear, authoritative posts that resonate with a professional audience "
            "while maintaining technical accuracy. You know how to balance technical depth with accessibility and incorporate "
            "relevant hashtags and mentions to maximize engagement.\n\n"
        ),
        "verbose": False,
    },
}

# Planner Tasks Configuration
tasks_config = {
    "analyze_blog": {
        "description": (
            "Analyze the markdown file at {blog_path} to create a developer-focused technical overview\n\n"
            "1. Map out the core idea that the blog discusses\n"
            "2. Identify key sections and what each section is about\n"
            "3. For each section, extract all URLs that appear inside image markdown syntax ![](image_url)\n"
            "4. You must associate these identified image URLs to their corresponding sections, so that we can use them with the tweets as media pieces\n\n"
            "Focus on details that are important for a comprehensive understanding of the blog.\n\n"
        ),
        "expected_output": (
            "A technical analysis containing:\n"
            "- Blog title and core concept/idea\n"
            "- Key technical sections identified with their main points\n"
            "- Important code examples or technical concepts covered\n"
            "- Key takeaways for developers\n"
            "- Relevant URLs to media that are associated with the key sections and can be associated with a tweet, this must be done.\n\n"
        ),
    },
    "create_twitter_thread_plan": {
        "description": (
            "Develop an engaging Twitter thread based on the blog analysis provided and closely follow the writing style provided in the {path_to_example_threads}\n\n"
            "The thread should break down complex technical concepts into digestible, tweet-sized chunks "
            "that maintain technical accuracy while being accessible.\n\n"
            "Plan should include:\n"
            "- A strong hook tweet that captures attention, it should be under 10 words, it must be the same as the title of the blog\n"
            "- Logical flow from basic to advanced concepts\n"
            "- Code snippets or key technical highlights that fit Twitter's format\n"
            "- Relevant URLs to media that are associated with the key sections and must be associated with their corresponding tweets\n"
            "- Clear takeaways for engineering audience\n\n"
            "Make sure to cover:\n"
            "- The core problem being solved\n"
            "- Key technical innovations or approaches\n"
            "- Interesting implementation details\n"
            "- Real-world applications or benefits\n"
            "- Call to action for the conclusion\n"
            "- Add relevant URLs to each tweet that can be associated with a tweet\n\n"
            "Focus on creating a narrative that technical audiences will find valuable "
            "while keeping each tweet concise, accessible, and impactful.\n\n"
        ),
        "expected_output": (
            "A Twitter thread with a list of tweets, where each tweet has the following:\n"
            "- content\n"
            "- URLs to media that are associated with the tweet, whenever possible\n"
            "- is_hook: true if the tweet is a hook tweet, false otherwise\n\n"
        ),
    },
    "create_linkedin_post_plan": {
        "description": (
            "Develop a comprehensive LinkedIn post based on the blog analysis provided\n\n"
            "The post should present technical content in a professional, long-form format "
            "while maintaining engagement and readability.\n\n"
            "Plan should include:\n"
            "- An attention-grabbing opening statement, it should be the same as the title of the blog\n"
            "- Well-structured body that breaks down the technical content\n"
            "- Professional tone suitable for LinkedIn's business audience\n"
            "- One main blog URL placed strategically at the end of the post\n"
            "- Strategic use of line breaks and formatting\n"
            "- Relevant hashtags (3-5 maximum)\n\n"
            "Make sure to cover:\n"
            "- The core technical problem and its business impact\n"
            "- Key solutions and technical approaches\n"
            "- Real-world applications and benefits\n"
            "- Professional insights or lessons learned\n"
            "- Clear call to action\n\n"
            "Focus on creating content that resonates with both technical professionals "
            "and business leaders while maintaining technical accuracy.\n\n"
        ),
        "expected_output": (
            "A LinkedIn post plan containing:\n- content\n- a main blog URL that is associated with the post\n\n"
        ),
    },
}
