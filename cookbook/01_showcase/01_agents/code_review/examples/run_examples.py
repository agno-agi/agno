"""
Code Review Agent Examples
==========================

Examples demonstrating different ways to use the Code Review Agent.

Run this script to see the agent in action:
    python examples/run_examples.py
"""

import sys
import webbrowser
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import code_review_agent
# ============================================================================
# Sample Code Snippets for Review
# ============================================================================

SAMPLE_PYTHON_CODE = '''
def calculate_average(numbers):
    total = 0
    for n in numbers:
        total += n
    return total / len(numbers)

def get_user_data(user_id):
    query = f"SELECT * FROM users WHERE id = {user_id}"
    return db.execute(query)

def process_file(filename):
    f = open(filename, 'r')
    data = f.read()
    # Process data
    result = data.upper()
    return result

class UserManager:
    def __init__(self):
        self.users = {}
    
    def add_user(self, id, name, password):
        self.users[id] = {"name": name, "password": password}
    
    def authenticate(self, id, password):
        if self.users[id]["password"] == password:
            return True
        return False
'''

SAMPLE_JAVASCRIPT_CODE = '''
async function fetchUserData(userId) {
    const response = await fetch(`/api/users/${userId}`);
    const data = response.json();
    return data;
}

function validateEmail(email) {
    if (email.includes('@')) {
        return true;
    }
}

function processItems(items) {
    for (var i = 0; i <= items.length; i++) {
        console.log(items[i].name);
    }
}

const config = {
    apiKey: "sk-1234567890abcdef",
    dbPassword: "admin123",
    secretToken: "super-secret-token"
};
'''

SAMPLE_DIFF = '''
diff --git a/auth.py b/auth.py
index 1234567..abcdefg 100644
--- a/auth.py
+++ b/auth.py
@@ -10,8 +10,12 @@ class AuthService:
     def __init__(self, db):
         self.db = db
 
-    def login(self, username, password):
-        user = self.db.get_user(username)
+    def login(self, username, password, remember_me=False):
+        # Get user from database
+        query = f"SELECT * FROM users WHERE username = '{username}'"
+        user = self.db.execute(query)
+        if not user:
+            return None
         if user and user.password == password:
             return self.create_session(user)
         return None
@@ -25,3 +29,8 @@ class AuthService:
     def logout(self, session_id):
         del self.sessions[session_id]
         return True
+
+    def reset_password(self, email):
+        # TODO: implement password reset
+        pass
'''


# ============================================================================
# Example Functions
# ============================================================================

def example_review_python_code():
    """Review a Python code snippet."""
    print("\n" + "=" * 60)
    print("Example 1: Review Python Code")
    print("=" * 60)

    code_review_agent.print_response(
        f"Review this Python code for bugs, security issues, and improvements:\n\n```python\n{SAMPLE_PYTHON_CODE}\n```",
        stream=True,
        show_full_thinking=True,
    )


def example_review_javascript_code():
    """Review a JavaScript code snippet."""
    print("\n" + "=" * 60)
    print("Example 2: Review JavaScript Code")
    print("=" * 60)

    code_review_agent.print_response(
        f"Review this JavaScript code for issues:\n\n```javascript\n{SAMPLE_JAVASCRIPT_CODE}\n```",
        stream=True,
        show_full_thinking=True,
    )


def example_review_diff():
    """Review a code diff."""
    print("\n" + "=" * 60)
    print("Example 3: Review Code Diff")
    print("=" * 60)

    code_review_agent.print_response(
        f"Review these code changes:\n\n```diff\n{SAMPLE_DIFF}\n```",
        stream=True,
        show_full_thinking=True,
    )


def example_review_github_pr():
    """Review a GitHub pull request (requires GITHUB_TOKEN)."""
    print("\n" + "=" * 60)
    print("Example 4: Review GitHub PR")
    print("=" * 60)

    # Example PR URL - replace with a real PR you want to review
    pr_url = "https://github.com/agno-agi/agno/pull/1"

    print(f"Reviewing: {pr_url}")
    print("(Note: This requires GITHUB_TOKEN environment variable)")
    print()

    code_review_agent.print_response(
        f"Review this pull request and provide feedback: {pr_url}",
        stream=True,
        show_full_thinking=True,
    )


def example_security_focused_review():
    """Review code with a focus on security."""
    print("\n" + "=" * 60)
    print("Example 5: Security-Focused Review")
    print("=" * 60)

    code_review_agent.print_response(
        f"Perform a security-focused code review. Look specifically for vulnerabilities, "
        f"injection risks, authentication issues, and sensitive data exposure:\n\n"
        f"```python\n{SAMPLE_PYTHON_CODE}\n```",
        stream=True,
        show_full_thinking=True,
    )




def interactive_mode():
    """Run the agent in interactive CLI mode."""
    print("\n" + "=" * 60)
    print("Interactive Mode")
    print("=" * 60)
    print("Starting interactive CLI...")
    print("Type 'exit' or 'quit' to stop\n")

    code_review_agent.cli_app(stream=True, show_reasoning=True)


def example_review_single_file():
    """Review a single file selected by user."""
    print("\n" + "=" * 60)
    print("Review Single File")
    print("=" * 60)
    
    examples_dir = Path(__file__).parent
    print(f"Available sample files in {examples_dir}:")
    print("  1. sample_calculator.py")
    print("  2. sample_calculator.html")
    print()
    
    choice = input("Select file (1 or 2): ").strip()
    
    if choice == "1":
        filename = "sample_calculator.py"
    elif choice == "2":
        filename = "sample_calculator.html"
    else:
        print("Invalid choice.")
        return
    
    filepath = examples_dir / filename
    
    code_review_agent.print_response(
        f"""Review the file at: {filepath}

Use the file tools to:
1. Read the file contents
2. Identify all bugs, security issues, and code quality problems
3. Provide a detailed review with specific line numbers and fixes
4. Create a new file named fixed_{filename} with fixed code
""",
        stream=True,
        show_full_thinking=True,
    )


def create_html_page():
    """Create an HTML page based on user description."""
    print("\n" + "=" * 60)
    print("Create HTML Page")
    print("=" * 60)
    print()
    
    # Get user input
    print("Describe the HTML page you want to create.")
    print("(Enter a blank line when done)")
    print()
    
    title = input("Page title: ").strip()
    if not title:
        title = "My Page"
    
    print("\nDescription (what should the page contain/do):")
    lines = []
    while True:
        line = input()
        if line == "":
            break
        lines.append(line)
    description = "\n".join(lines)
    
    if not description:
        description = "A simple webpage"
    
    # Generate filename from title
    filename = title.lower().replace(" ", "_").replace("-", "_")
    filename = "".join(c for c in filename if c.isalnum() or c == "_")
    filename = f"{filename}.html"

    # Save to tmp folder
    tmp_dir = Path(__file__).parent / "tmp"
    tmp_dir.mkdir(exist_ok=True)
    filepath = tmp_dir / filename
    
    print(f"\nCreating: {filepath}")
    print("=" * 60)
    
    code_review_agent.print_response(
        f"""Create an HTML page and save it to: {filepath}

**Page Title:** {title}

**Description:**
{description}

Requirements:
1. Use the file tools to create and save the HTML file
2. Create a complete, well-structured HTML5 document
3. Include inline CSS for styling (make it look modern and clean)
4. Add any necessary JavaScript if the description requires interactivity
5. Make sure the page is responsive and mobile-friendly
6. Use semantic HTML elements where appropriate
7. Save the file to the exact path specified above

After creating the file, confirm the file was saved successfully.
""",
        stream=True,
        show_full_thinking=True,
    )
    
    # Open the HTML file in browser after agent completes
    if filepath.exists():
        print("\n" + "=" * 60)
        print("Opening page in browser...")
        webbrowser.open(filepath.as_uri())
    else:
        print("\n[Warning] File was not created. Check agent output for errors.")
    while True:
        user_input = input("\nAsk further fixes (or 'quit'/'exit' to return): ").strip()
        if user_input.lower() in ("quit", "exit"):
            break
        if user_input:
            code_review_agent.print_response(user_input, stream=True, show_full_thinking=True)


# ============================================================================
# Main
# ============================================================================

def show_menu():
    """Display the main menu."""
    print("\n" + "=" * 60)
    print("  Code Review Agent - Examples")
    print("=" * 60)
    print()
    print("  1. Review Python Code")
    print("  2. Review JavaScript Code")
    print("  3. Review Code Diff")
    print("  4. Review GitHub PR (enter URL)")
    print("  5. Security-Focused Review")
    print("  6. Review Single File")
    print("  7. Create HTML Page")
    print("  8. Interactive Mode")
    print()
    print("  0. Exit")
    print()


def example_review_github_pr_interactive():
    """Review a GitHub pull request with user-provided URL."""
    print("\n" + "=" * 60)
    print("Review GitHub PR")
    print("=" * 60)
    print("(Note: This requires GITHUB_TOKEN environment variable)")
    print()
    
    pr_url = input("Enter PR URL (or press Enter for demo): ").strip()
    
    if not pr_url:
        pr_url = "https://github.com/agno-agi/agno/pull/1"
        print(f"Using demo URL: {pr_url}")
    
    print()
    code_review_agent.print_response(
        f"Review this pull request and provide feedback: {pr_url}",
        stream=True,
        show_full_thinking=True,
    )


def main():
    """Run the CLI menu."""
    while True:
        show_menu()
        
        choice = input("Select an option: ").strip()
        
        if choice == "1":
            example_review_python_code()
        elif choice == "2":
            example_review_javascript_code()
        elif choice == "3":
            example_review_diff()
        elif choice == "4":
            example_review_github_pr_interactive()
        elif choice == "5":
            example_security_focused_review()
        elif choice == "6":
            example_review_single_file()
        elif choice == "7":
            create_html_page()
        elif choice == "8":
            interactive_mode()
        elif choice == "0":
            print("\nGoodbye!")
            break
        else:
            print("\nInvalid option. Please try again.")
        
        input("\nPress Enter to continue...")


if __name__ == "__main__":
    main()
