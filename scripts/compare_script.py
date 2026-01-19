
import os
import re
from pathlib import Path

AGNO_REPO = "/Users/docx/shaloo/agno/lab/agno"
AGNO_DOCS = "/Users/docx/shaloo/agno/lab/agno-docs"

REPO_COOKBOOK = os.path.join(AGNO_REPO, "cookbook")
DOCS_COOKBOOK = os.path.join(AGNO_DOCS, "cookbook")

def get_files(directory, extensions):
    files_map = {}
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(extensions) and not file.startswith("__"):
                path = os.path.join(root, file)
                basename = os.path.splitext(file)[0]
                if basename not in files_map:
                    files_map[basename] = []
                files_map[basename].append(path)
    return files_map

def check_broken_links(docs_map):
    broken_links = []
    # Match github blob links
    link_pattern = re.compile(r'https://github\.com/agno-agi/agno/blob/[^/]+/cookbook/([^ )"\']+)')
    
    for basename, paths in docs_map.items():
        for path in paths:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    matches = link_pattern.findall(content)
                    for match in matches:
                        # match might contain anchors #L10
                        clean_match = match.split('#')[0]
                        target_path = os.path.join(REPO_COOKBOOK, clean_match)
                        if not os.path.exists(target_path):
                            broken_links.append({
                                "source": path,
                                "link": match,
                                "expected_loc": target_path
                            })
            except Exception as e:
                print(f"Error reading {path}: {e}")
    return broken_links

def main():
    print("Scanning Repositories...")
    code_files = get_files(REPO_COOKBOOK, ('.py',))
    doc_files = get_files(DOCS_COOKBOOK, ('.mdx',))

    print(f"Found {len(code_files)} unique code basenames.")
    print(f"Found {len(doc_files)} unique doc basenames.")

    missing_docs = {}
    for base, paths in code_files.items():
        if base not in doc_files:
            missing_docs[base] = paths

    print("\n--- Gaps: Missing Documentation for Code Examples ---")
    count = 0
    for base in sorted(missing_docs.keys()):
        paths = missing_docs[base]
        # Clean paths for display
        rel_paths = [p.replace(REPO_COOKBOOK + '/', '') for p in paths]
        print(f"{base}: {', '.join(rel_paths)}")
        count += 1
    print(f"Total Missing: {count}")

    print("\n--- Checking Broken Links in Docs ---")
    broken = check_broken_links(doc_files)
    if broken:
        for item in broken:
            source = item['source'].replace(DOCS_COOKBOOK + '/', '')
            print(f"File: {source}")
            print(f"  Broken Link: {item['link']}")
            print(f"  Expected: {item['expected_loc']}")
    else:
        print("No broken links found pointing to cookbook files.")

if __name__ == "__main__":
    main()
