
import os
import re
from pathlib import Path

COOKBOOK_DIR = "cookbook"
OUTPUT_FILE = "COOKBOOK_INDEX.md"
REPO_URL_BASE = "https://github.com/agno-agi/agno/blob/main/cookbook"

def extract_description(file_path):
    """Extracts the first line of the docstring or header comment."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            # Look for docstring """ ... """
            docstring_match = re.search(r'"""(.*?)"""', content, re.DOTALL)
            if docstring_match:
                return docstring_match.group(1).strip().split('\n')[0]
            
            # Look for first comment # ...
            lines = content.split('\n')
            for line in lines:
                if line.strip().startswith('#'):
                    return line.strip().lstrip('#').strip()
    except Exception:
        pass
    return ""

def generate_index():
    print(f"Generating index for {COOKBOOK_DIR}...")
    
    entries = []
    for root, _, files in os.walk(COOKBOOK_DIR):
        for file in files:
            if file.endswith(".py") and not file.startswith("__"):
                path = os.path.join(root, file)
                rel_path = os.path.relpath(path, COOKBOOK_DIR)
                name = os.path.basename(file)
                description = extract_description(path) or "No description available."
                
                # Create category from directory structure
                category = os.path.dirname(rel_path).replace(os.path.sep, " / ")
                
                # Escape pipe | to prevent table breakage
                description = description.replace("|", "\\|")
                # Escape < and > to prevent MDX tag parsing errors
                description = description.replace("<", "&lt;").replace(">", "&gt;")

                link = f"{REPO_URL_BASE}/{rel_path}"
                entries.append({
                    "category": category,
                    "name": name,
                    "description": description,
                    "link": link
                })

    # Sort by category then name
    entries.sort(key=lambda x: (x['category'], x['name']))

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("# Cookbook Index\n\n")
        f.write("| Category | Example | Description |\n")
        f.write("| :--- | :--- | :--- |\n")
        
        for entry in entries:
            f.write(f"| {entry['category']} | [{entry['name']}]({entry['link']}) | {entry['description']} |\n")

    print(f"Generated {len(entries)} entries in {OUTPUT_FILE}")

if __name__ == "__main__":
    generate_index()
