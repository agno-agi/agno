import asyncio
import json
import os
import re

try:
    from .utils import *
except:
    from utils import *


async def get_node_summary(node, summary_token_threshold=200, model=None):
    node_text = node.get("text")
    num_tokens = count_tokens(node_text, model=model)
    if num_tokens < summary_token_threshold:
        return node_text
    else:
        return await generate_node_summary(node, model=model)


async def generate_summaries_for_structure_md(structure, summary_token_threshold, model=None):
    nodes = structure_to_list(structure)
    tasks = [get_node_summary(node, summary_token_threshold=summary_token_threshold, model=model) for node in nodes]
    summaries = await asyncio.gather(*tasks)

    for node, summary in zip(nodes, summaries):
        if not node.get("nodes"):
            node["summary"] = summary
        else:
            node["prefix_summary"] = summary
    return structure


def extract_nodes_from_markdown(markdown_content):
    header_pattern = r"^(#{1,6})\s+(.+)$"
    code_block_pattern = r"^```"
    node_list = []

    lines = markdown_content.split("\n")
    in_code_block = False

    for line_num, line in enumerate(lines, 1):
        stripped_line = line.strip()

        # Check for code block delimiters (triple backticks)
        if re.match(code_block_pattern, stripped_line):
            in_code_block = not in_code_block
            continue

        # Skip empty lines
        if not stripped_line:
            continue

        # Only look for headers when not inside a code block
        if not in_code_block:
            match = re.match(header_pattern, stripped_line)
            if match:
                title = match.group(2).strip()
                node_list.append({"node_title": title, "line_num": line_num})

    return node_list, lines


def extract_node_text_content(node_list, markdown_lines):
    all_nodes = []
    for node in node_list:
        line_content = markdown_lines[node["line_num"] - 1]
        header_match = re.match(r"^(#{1,6})", line_content)

        if header_match is None:
            print(f"Warning: Line {node['line_num']} does not contain a valid header: '{line_content}'")
            continue

        processed_node = {
            "title": node["node_title"],
            "line_num": node["line_num"],
            "level": len(header_match.group(1)),
        }
        all_nodes.append(processed_node)

    for i, node in enumerate(all_nodes):
        start_line = node["line_num"] - 1
        if i + 1 < len(all_nodes):
            end_line = all_nodes[i + 1]["line_num"] - 1
        else:
            end_line = len(markdown_lines)

        node["text"] = "\n".join(markdown_lines[start_line:end_line]).strip()
    return all_nodes


def update_node_list_with_text_token_count(node_list, model=None):
    def find_all_children(parent_index, parent_level, node_list):
        """Find all direct and indirect children of a parent node"""
        children_indices = []

        # Look for children after the parent
        for i in range(parent_index + 1, len(node_list)):
            current_level = node_list[i]["level"]

            # If we hit a node at same or higher level than parent, stop
            if current_level <= parent_level:
                break

            # This is a descendant
            children_indices.append(i)

        return children_indices

    # Make a copy to avoid modifying the original
    result_list = node_list.copy()

    # Process nodes from end to beginning to ensure children are processed before parents
    for i in range(len(result_list) - 1, -1, -1):
        current_node = result_list[i]
        current_level = current_node["level"]

        # Get all children of this node
        children_indices = find_all_children(i, current_level, result_list)

        # Start with the node's own text
        node_text = current_node.get("text", "")
        total_text = node_text

        # Add all children's text
        for child_index in children_indices:
            child_text = result_list[child_index].get("text", "")
            if child_text:
                total_text += "\n" + child_text

        # Calculate token count for combined text
        result_list[i]["text_token_count"] = count_tokens(total_text, model=model)

    return result_list


def tree_thinning_for_index(node_list, min_node_token=None, model=None):
    def find_all_children(parent_index, parent_level, node_list):
        children_indices = []

        for i in range(parent_index + 1, len(node_list)):
            current_level = node_list[i]["level"]

            if current_level <= parent_level:
                break

            children_indices.append(i)

        return children_indices

    result_list = node_list.copy()
    nodes_to_remove = set()

    for i in range(len(result_list) - 1, -1, -1):
        if i in nodes_to_remove:
            continue

        current_node = result_list[i]
        current_level = current_node["level"]

        total_tokens = current_node.get("text_token_count", 0)

        if total_tokens < min_node_token:
            children_indices = find_all_children(i, current_level, result_list)

            children_texts = []
            for child_index in sorted(children_indices):
                if child_index not in nodes_to_remove:
                    child_text = result_list[child_index].get("text", "")
                    if child_text.strip():
                        children_texts.append(child_text)
                    nodes_to_remove.add(child_index)

            if children_texts:
                parent_text = current_node.get("text", "")
                merged_text = parent_text
                for child_text in children_texts:
                    if merged_text and not merged_text.endswith("\n"):
                        merged_text += "\n\n"
                    merged_text += child_text

                result_list[i]["text"] = merged_text

                result_list[i]["text_token_count"] = count_tokens(merged_text, model=model)

    for index in sorted(nodes_to_remove, reverse=True):
        result_list.pop(index)

    return result_list


def build_tree_from_nodes(node_list):
    if not node_list:
        return []

    stack = []
    root_nodes = []
    node_counter = 1

    for node in node_list:
        current_level = node["level"]

        tree_node = {
            "title": node["title"],
            "node_id": str(node_counter).zfill(4),
            "text": node["text"],
            "line_num": node["line_num"],
            "nodes": [],
        }
        node_counter += 1

        while stack and stack[-1][1] >= current_level:
            stack.pop()

        if not stack:
            root_nodes.append(tree_node)
        else:
            parent_node, parent_level = stack[-1]
            parent_node["nodes"].append(tree_node)

        stack.append((tree_node, current_level))

    return root_nodes


def clean_tree_for_output(tree_nodes):
    cleaned_nodes = []

    for node in tree_nodes:
        cleaned_node = {
            "title": node["title"],
            "node_id": node["node_id"],
            "text": node["text"],
            "line_num": node["line_num"],
        }

        if node["nodes"]:
            cleaned_node["nodes"] = clean_tree_for_output(node["nodes"])

        cleaned_nodes.append(cleaned_node)

    return cleaned_nodes


async def md_to_tree(
    md_path,
    if_thinning=False,
    min_token_threshold=None,
    if_add_node_summary="no",
    summary_token_threshold=None,
    model=None,
    if_add_doc_description="no",
    if_add_node_text="no",
    if_add_node_id="yes",
):
    with open(md_path, "r", encoding="utf-8") as f:
        markdown_content = f.read()

    print(f"Extracting nodes from markdown...")
    node_list, markdown_lines = extract_nodes_from_markdown(markdown_content)

    print(f"Extracting text content from nodes...")
    nodes_with_content = extract_node_text_content(node_list, markdown_lines)

    if if_thinning:
        nodes_with_content = update_node_list_with_text_token_count(nodes_with_content, model=model)
        print(f"Thinning nodes...")
        nodes_with_content = tree_thinning_for_index(nodes_with_content, min_token_threshold, model=model)

    print(f"Building tree from nodes...")
    tree_structure = build_tree_from_nodes(nodes_with_content)

    if if_add_node_id == "yes":
        write_node_id(tree_structure)

    print(f"Formatting tree structure...")

    if if_add_node_summary == "yes":
        # Always include text for summary generation
        tree_structure = format_structure(
            tree_structure, order=["title", "node_id", "summary", "prefix_summary", "text", "line_num", "nodes"]
        )

        print(f"Generating summaries for each node...")
        tree_structure = await generate_summaries_for_structure_md(
            tree_structure, summary_token_threshold=summary_token_threshold, model=model
        )

        if if_add_node_text == "no":
            # Remove text after summary generation if not requested
            tree_structure = format_structure(
                tree_structure, order=["title", "node_id", "summary", "prefix_summary", "line_num", "nodes"]
            )

        if if_add_doc_description == "yes":
            print(f"Generating document description...")
            # Create a clean structure without unnecessary fields for description generation
            clean_structure = create_clean_structure_for_description(tree_structure)
            doc_description = generate_doc_description(clean_structure, model=model)
            return {
                "doc_name": os.path.splitext(os.path.basename(md_path))[0],
                "doc_description": doc_description,
                "structure": tree_structure,
            }
    else:
        # No summaries needed, format based on text preference
        if if_add_node_text == "yes":
            tree_structure = format_structure(
                tree_structure, order=["title", "node_id", "summary", "prefix_summary", "text", "line_num", "nodes"]
            )
        else:
            tree_structure = format_structure(
                tree_structure, order=["title", "node_id", "summary", "prefix_summary", "line_num", "nodes"]
            )

    return {
        "doc_name": os.path.splitext(os.path.basename(md_path))[0],
        "structure": tree_structure,
    }


if __name__ == "__main__":
    import json
    import os

    # MD_NAME = 'Detect-Order-Construct'
    MD_NAME = "cognitive-load"
    MD_PATH = os.path.join(os.path.dirname(__file__), "..", "tests/markdowns/", f"{MD_NAME}.md")

    MODEL = "gpt-4.1"
    IF_THINNING = False
    THINNING_THRESHOLD = 5000
    SUMMARY_TOKEN_THRESHOLD = 200
    IF_SUMMARY = True

    tree_structure = asyncio.run(
        md_to_tree(
            md_path=MD_PATH,
            if_thinning=IF_THINNING,
            min_token_threshold=THINNING_THRESHOLD,
            if_add_node_summary="yes" if IF_SUMMARY else "no",
            summary_token_threshold=SUMMARY_TOKEN_THRESHOLD,
            model=MODEL,
        )
    )

    print("\n" + "=" * 60)
    print("TREE STRUCTURE")
    print("=" * 60)
    print_json(tree_structure)

    print("\n" + "=" * 60)
    print("TABLE OF CONTENTS")
    print("=" * 60)
    print_toc(tree_structure["structure"])

    output_path = os.path.join(os.path.dirname(__file__), "..", "results", f"{MD_NAME}_structure.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(tree_structure, f, indent=2, ensure_ascii=False)

    print(f"\nTree structure saved to: {output_path}")
