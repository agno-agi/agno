"""
Simple example showing Morph Fast Apply with file creation and editing.
"""

from pathlib import Path
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.models.morph import MorphTools

def create_sample_file():
    """Create a simple Python file in tmp directory for testing"""
    # Create tmp directory if it doesn't exist
    tmp_dir = Path("tmp")
    tmp_dir.mkdir(exist_ok=True)
    
    # Create a simple Python file
    sample_file = tmp_dir / "calculator.py"
    
    sample_code = """
def add(a, b):
    return a + b

def multiply(x, y):
    result = x * y
    return result

class Calculator:
    def __init__(self):
        self.history = []
    
    def calculate(self, operation, a, b):
        if operation == "add":
            result = add(a, b)
        elif operation == "multiply":
            result = multiply(a, b)
        else:
            result = None
        
        self.history.append(f"{operation}({a}, {b}) = {result}")
        return result
"""
        
    with open(sample_file, 'w') as f:
        f.write(sample_code)
    
    return str(sample_file)

def main():
    target_file = create_sample_file()
    
    code_editor = Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[MorphTools(model="morph-v3-large")],
        debug_mode=True,
        markdown=True,
        description="""I am a code improvement assistant. When asked to edit files, I:
            1. Read the existing file content automatically
            2. Generate appropriate edit instructions and code changes
            3. Use Morph Fast Apply for precise, high-speed edits
            4. Write results back to files when requested

            I follow best practices for code editing and always provide clear, minimal edits.
        """
    )
    
    # Request to improve the code
    improvement_request = f"""
        Please improve the Python code in "{target_file}" by adding:

        1. Type hints for all functions and methods
        2. Error handling and input validation
        3. Docstrings for better documentation
        4. A divide method to the Calculator class
        5. Better error messages

        Make the code more robust and professional while maintaining its functionality.
    """
    
    code_editor.print_response(improvement_request)

if __name__ == "__main__":
    main()