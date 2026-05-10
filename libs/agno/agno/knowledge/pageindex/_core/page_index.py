import copy
import json
import math
import os
import random
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from .utils import *


################### check title in page #########################################################
async def check_title_appearance(item, page_list, start_index=1, model=None):
    title = item["title"]
    if "physical_index" not in item or item["physical_index"] is None:
        return {"list_index": item.get("list_index"), "answer": "no", "title": title, "page_number": None}

    page_number = item["physical_index"]
    page_text = page_list[page_number - start_index][0]

    prompt = f"""
    Your job is to check if the given section appears or starts in the given page_text.

    Note: do fuzzy matching, ignore any space inconsistency in the page_text.

    The given section title is {title}.
    The given page_text is {page_text}.
    
    Reply format:
    {{
        
        "thinking": <why do you think the section appears or starts in the page_text>
        "answer": "yes or no" (yes if the section appears or starts in the page_text, no otherwise)
    }}
    Directly return the final JSON structure. Do not output anything else."""

    response = await ChatGPT_API_async(model=model, prompt=prompt)
    response = extract_json(response)
    if "answer" in response:
        answer = response["answer"]
    else:
        answer = "no"
    return {"list_index": item["list_index"], "answer": answer, "title": title, "page_number": page_number}


async def check_title_appearance_in_start(title, page_text, model=None, logger=None):
    prompt = f"""
    You will be given the current section title and the current page_text.
    Your job is to check if the current section starts in the beginning of the given page_text.
    If there are other contents before the current section title, then the current section does not start in the beginning of the given page_text.
    If the current section title is the first content in the given page_text, then the current section starts in the beginning of the given page_text.

    Note: do fuzzy matching, ignore any space inconsistency in the page_text.

    The given section title is {title}.
    The given page_text is {page_text}.
    
    reply format:
    {{
        "thinking": <why do you think the section appears or starts in the page_text>
        "start_begin": "yes or no" (yes if the section starts in the beginning of the page_text, no otherwise)
    }}
    Directly return the final JSON structure. Do not output anything else."""

    response = await ChatGPT_API_async(model=model, prompt=prompt)
    response = extract_json(response)
    if logger:
        logger.info(f"Response: {response}")
    return response.get("start_begin", "no")


async def check_title_appearance_in_start_concurrent(structure, page_list, model=None, logger=None):
    if logger:
        logger.info("Checking title appearance in start concurrently")

    # skip items without physical_index
    for item in structure:
        if item.get("physical_index") is None:
            item["appear_start"] = "no"

    # only for items with valid physical_index
    tasks = []
    valid_items = []
    for item in structure:
        if item.get("physical_index") is not None:
            page_text = page_list[item["physical_index"] - 1][0]
            tasks.append(check_title_appearance_in_start(item["title"], page_text, model=model, logger=logger))
            valid_items.append(item)

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for item, result in zip(valid_items, results):
        if isinstance(result, Exception):
            if logger:
                logger.error(f"Error checking start for {item['title']}: {result}")
            item["appear_start"] = "no"
        else:
            item["appear_start"] = result

    return structure


def toc_detector_single_page(content, model=None):
    prompt = f"""
    Your job is to detect if there is a table of content provided in the given text.

    Given text: {content}

    return the following JSON format:
    {{
        "thinking": <why do you think there is a table of content in the given text>
        "toc_detected": "<yes or no>",
    }}

    Directly return the final JSON structure. Do not output anything else.
    Please note: abstract,summary, notation list, figure list, table list, etc. are not table of contents."""

    response = ChatGPT_API(model=model, prompt=prompt)
    # print('response', response)
    json_content = extract_json(response)
    detected = str(json_content.get("toc_detected", "")).strip().lower()
    if detected in {"yes", "no"}:
        return detected
    return "no"


def check_if_toc_extraction_is_complete(content, toc, model=None):
    prompt = f"""
    You are given a partial document  and a  table of contents.
    Your job is to check if the  table of contents is complete, which it contains all the main sections in the partial document.

    Reply format:
    {{
        "thinking": <why do you think the table of contents is complete or not>
        "completed": "yes" or "no"
    }}
    Directly return the final JSON structure. Do not output anything else."""

    prompt = prompt + "\n Document:\n" + content + "\n Table of contents:\n" + toc
    response = ChatGPT_API(model=model, prompt=prompt)
    json_content = extract_json(response)
    completed = str(json_content.get("completed", "")).strip().lower()
    if completed in {"yes", "no"}:
        return completed
    return "no"


def check_if_toc_transformation_is_complete(content, toc, model=None):
    prompt = f"""
    You are given a raw table of contents and a  table of contents.
    Your job is to check if the  table of contents is complete.

    Reply format:
    {{
        "thinking": <why do you think the cleaned table of contents is complete or not>
        "completed": "yes" or "no"
    }}
    Directly return the final JSON structure. Do not output anything else."""

    prompt = prompt + "\n Raw Table of contents:\n" + content + "\n Cleaned Table of contents:\n" + toc
    response = ChatGPT_API(model=model, prompt=prompt)
    json_content = extract_json(response)
    completed = str(json_content.get("completed", "")).strip().lower()
    if completed in {"yes", "no"}:
        return completed
    return "no"


def extract_toc_content(content, model=None):
    prompt = f"""
    Your job is to extract the full table of contents from the given text, replace ... with :

    Given text: {content}

    Directly return the full table of contents content. Do not output anything else."""

    response, finish_reason = ChatGPT_API_with_finish_reason(model=model, prompt=prompt)

    if_complete = check_if_toc_transformation_is_complete(content, response, model)
    if if_complete == "yes" and finish_reason == "finished":
        return response

    chat_history = [
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": response},
    ]
    prompt = (
        f"""please continue the generation of table of contents , directly output the remaining part of the structure"""
    )
    new_response, finish_reason = ChatGPT_API_with_finish_reason(model=model, prompt=prompt, chat_history=chat_history)
    response = response + new_response
    if_complete = check_if_toc_transformation_is_complete(content, response, model)

    attempts = 0
    max_attempts = 5
    while not (if_complete == "yes" and finish_reason == "finished"):
        attempts += 1
        chat_history = [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": response},
        ]
        prompt = f"""please continue the generation of table of contents , directly output the remaining part of the structure"""
        new_response, finish_reason = ChatGPT_API_with_finish_reason(
            model=model, prompt=prompt, chat_history=chat_history
        )
        response = response + new_response
        if_complete = check_if_toc_transformation_is_complete(content, response, model)

        # Avoid infinite loops when model output never reaches valid completion.
        if attempts >= max_attempts:
            raise Exception("Failed to complete table of contents after maximum retries")

    return response


def detect_page_index(toc_content, model=None):
    print("start detect_page_index")
    prompt = f"""
    You will be given a table of contents.

    Your job is to detect if there are page numbers/indices given within the table of contents.

    Given text: {toc_content}

    Reply format:
    {{
        "thinking": <why do you think there are page numbers/indices given within the table of contents>
        "page_index_given_in_toc": "<yes or no>"
    }}
    Directly return the final JSON structure. Do not output anything else."""

    response = ChatGPT_API(model=model, prompt=prompt)
    json_content = extract_json(response)
    detected = str(json_content.get("page_index_given_in_toc", "")).strip().lower()
    if detected in {"yes", "no"}:
        return detected
    return "no"


def toc_extractor(page_list, toc_page_list, model):
    def transform_dots_to_colon(text):
        text = re.sub(r"\.{5,}", ": ", text)
        # Handle dots separated by spaces
        text = re.sub(r"(?:\. ){5,}\.?", ": ", text)
        return text

    toc_content = ""
    for page_index in toc_page_list:
        toc_content += page_list[page_index][0]
    toc_content = transform_dots_to_colon(toc_content)
    has_page_index = detect_page_index(toc_content, model=model)

    return {"toc_content": toc_content, "page_index_given_in_toc": has_page_index}


def toc_index_extractor(toc, content, model=None):
    print("start toc_index_extractor")
    toc_extractor_prompt = """
    You are given a table of contents in a json format and several pages of a document, your job is to add the physical_index to the table of contents in the json format.

    The provided pages contains tags like <physical_index_X> and <physical_index_X> to indicate the physical location of the page X.

    The structure variable is the numeric system which represents the index of the hierarchy section in the table of contents. For example, the first section has structure index 1, the first subsection has structure index 1.1, the second subsection has structure index 1.2, etc.

    The response should be in the following JSON format: 
    [
        {
            "structure": <structure index, "x.x.x" or None> (string),
            "title": <title of the section>,
            "physical_index": "<physical_index_X>" (keep the format)
        },
        ...
    ]

    Only add the physical_index to the sections that are in the provided pages.
    If the section is not in the provided pages, do not add the physical_index to it.
    Directly return the final JSON structure. Do not output anything else."""

    prompt = toc_extractor_prompt + "\nTable of contents:\n" + str(toc) + "\nDocument pages:\n" + content
    response = ChatGPT_API(model=model, prompt=prompt)
    json_content = extract_json(response)
    return json_content


def toc_transformer(toc_content, model=None):
    print("start toc_transformer")
    init_prompt = """
    You are given a table of contents, You job is to transform the whole table of content into a JSON format included table_of_contents.

    structure is the numeric system which represents the index of the hierarchy section in the table of contents. For example, the first section has structure index 1, the first subsection has structure index 1.1, the second subsection has structure index 1.2, etc.

    The response should be in the following JSON format: 
    {
    table_of_contents: [
        {
            "structure": <structure index, "x.x.x" or None> (string),
            "title": <title of the section>,
            "page": <page number or None>,
        },
        ...
        ],
    }
    You should transform the full table of contents in one go.
    Directly return the final JSON structure, do not output anything else. """

    prompt = init_prompt + "\n Given table of contents\n:" + toc_content
    last_complete, finish_reason = ChatGPT_API_with_finish_reason(model=model, prompt=prompt)
    if_complete = check_if_toc_transformation_is_complete(toc_content, last_complete, model)
    if if_complete == "yes" and finish_reason == "finished":
        last_complete = extract_json(last_complete)
        cleaned_response = convert_page_to_int(last_complete["table_of_contents"])
        return cleaned_response

    last_complete = get_json_content(last_complete)
    while not (if_complete == "yes" and finish_reason == "finished"):
        position = last_complete.rfind("}")
        if position != -1:
            last_complete = last_complete[: position + 2]
        prompt = f"""
        Your task is to continue the table of contents json structure, directly output the remaining part of the json structure.
        The response should be in the following JSON format: 

        The raw table of contents json structure is:
        {toc_content}

        The incomplete transformed table of contents json structure is:
        {last_complete}

        Please continue the json structure, directly output the remaining part of the json structure."""

        new_complete, finish_reason = ChatGPT_API_with_finish_reason(model=model, prompt=prompt)

        if new_complete.startswith("```json"):
            new_complete = get_json_content(new_complete)
            last_complete = last_complete + new_complete

        if_complete = check_if_toc_transformation_is_complete(toc_content, last_complete, model)

    last_complete = json.loads(last_complete)

    cleaned_response = convert_page_to_int(last_complete["table_of_contents"])
    return cleaned_response


def find_toc_pages(start_page_index, page_list, opt, logger=None):
    print("start find_toc_pages")
    last_page_is_yes = False
    toc_page_list = []
    i = start_page_index

    while i < len(page_list):
        # Only check beyond max_pages if we're still finding TOC pages
        if i >= opt.toc_check_page_num and not last_page_is_yes:
            break
        detected_result = toc_detector_single_page(page_list[i][0], model=opt.model)
        if detected_result == "yes":
            if logger:
                logger.info(f"Page {i} has toc")
            toc_page_list.append(i)
            last_page_is_yes = True
        elif detected_result == "no" and last_page_is_yes:
            if logger:
                logger.info(f"Found the last page with toc: {i - 1}")
            break
        i += 1

    if not toc_page_list and logger:
        logger.info("No toc found")

    return toc_page_list


def remove_page_number(data):
    if isinstance(data, dict):
        data.pop("page_number", None)
        for key in list(data.keys()):
            if "nodes" in key:
                remove_page_number(data[key])
    elif isinstance(data, list):
        for item in data:
            remove_page_number(item)
    return data


def extract_matching_page_pairs(toc_page, toc_physical_index, start_page_index):
    pairs = []
    for phy_item in toc_physical_index:
        for page_item in toc_page:
            if phy_item.get("title") == page_item.get("title"):
                physical_index = phy_item.get("physical_index")
                if physical_index is not None and int(physical_index) >= start_page_index:
                    pairs.append(
                        {
                            "title": phy_item.get("title"),
                            "page": page_item.get("page"),
                            "physical_index": physical_index,
                        }
                    )
    return pairs


def calculate_page_offset(pairs):
    differences = []
    for pair in pairs:
        try:
            physical_index = pair["physical_index"]
            page_number = pair["page"]
            difference = physical_index - page_number
            differences.append(difference)
        except (KeyError, TypeError):
            continue

    if not differences:
        return None

    difference_counts = {}
    for diff in differences:
        difference_counts[diff] = difference_counts.get(diff, 0) + 1

    most_common = max(difference_counts.items(), key=lambda x: x[1])[0]

    return most_common


def add_page_offset_to_toc_json(data, offset):
    for i in range(len(data)):
        if data[i].get("page") is not None and isinstance(data[i]["page"], int):
            data[i]["physical_index"] = data[i]["page"] + offset
            del data[i]["page"]

    return data


def page_list_to_group_text(page_contents, token_lengths, max_tokens=20000, overlap_page=1):
    num_tokens = sum(token_lengths)

    if num_tokens <= max_tokens:
        # merge all pages into one text
        page_text = "".join(page_contents)
        return [page_text]

    subsets = []
    current_subset = []
    current_token_count = 0

    expected_parts_num = math.ceil(num_tokens / max_tokens)
    average_tokens_per_part = math.ceil(((num_tokens / expected_parts_num) + max_tokens) / 2)

    for i, (page_content, page_tokens) in enumerate(zip(page_contents, token_lengths)):
        if current_token_count + page_tokens > average_tokens_per_part:
            subsets.append("".join(current_subset))
            # Start new subset from overlap if specified
            overlap_start = max(i - overlap_page, 0)
            current_subset = page_contents[overlap_start:i]
            current_token_count = sum(token_lengths[overlap_start:i])

        # Add current page to the subset
        current_subset.append(page_content)
        current_token_count += page_tokens

    # Add the last subset if it contains any pages
    if current_subset:
        subsets.append("".join(current_subset))

    print("divide page_list to groups", len(subsets))
    return subsets


def add_page_number_to_toc(part, structure, model=None):
    fill_prompt_seq = """
    You are given an JSON structure of a document and a partial part of the document. Your task is to check if the title that is described in the structure is started in the partial given document.

    The provided text contains tags like <physical_index_X> and <physical_index_X> to indicate the physical location of the page X. 

    If the full target section starts in the partial given document, insert the given JSON structure with the "start": "yes", and "start_index": "<physical_index_X>".

    If the full target section does not start in the partial given document, insert "start": "no",  "start_index": None.

    The response should be in the following format. 
        [
            {
                "structure": <structure index, "x.x.x" or None> (string),
                "title": <title of the section>,
                "start": "<yes or no>",
                "physical_index": "<physical_index_X> (keep the format)" or None
            },
            ...
        ]    
    The given structure contains the result of the previous part, you need to fill the result of the current part, do not change the previous result.
    Directly return the final JSON structure. Do not output anything else."""

    prompt = (
        fill_prompt_seq
        + f"\n\nCurrent Partial Document:\n{part}\n\nGiven Structure\n{json.dumps(structure, indent=2)}\n"
    )
    current_json_raw = ChatGPT_API(model=model, prompt=prompt)
    json_result = extract_json(current_json_raw)

    for item in json_result:
        if "start" in item:
            del item["start"]
    return json_result


def remove_first_physical_index_section(text):
    """
    Removes the first section between <physical_index_X> and <physical_index_X> tags,
    and returns the remaining text.
    """
    pattern = r"<physical_index_\d+>.*?<physical_index_\d+>"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        # Remove the first matched section
        return text.replace(match.group(0), "", 1)
    return text


### add verify completeness
def generate_toc_continue(toc_content, part, model="gpt-4o-2024-11-20"):
    print("start generate_toc_continue")
    prompt = """
    You are an expert in extracting hierarchical tree structure.
    You are given a tree structure of the previous part and the text of the current part.
    Your task is to continue the tree structure from the previous part to include the current part.

    The structure variable is the numeric system which represents the index of the hierarchy section in the table of contents. For example, the first section has structure index 1, the first subsection has structure index 1.1, the second subsection has structure index 1.2, etc.

    For the title, you need to extract the original title from the text, only fix the space inconsistency.

    The provided text contains tags like <physical_index_X> and <physical_index_X> to indicate the start and end of page X. \
    
    For the physical_index, you need to extract the physical index of the start of the section from the text. Keep the <physical_index_X> format.

    The response should be in the following format. 
        [
            {
                "structure": <structure index, "x.x.x"> (string),
                "title": <title of the section, keep the original title>,
                "physical_index": "<physical_index_X> (keep the format)"
            },
            ...
        ]    

    Directly return the additional part of the final JSON structure. Do not output anything else."""

    prompt = prompt + "\nGiven text\n:" + part + "\nPrevious tree structure\n:" + json.dumps(toc_content, indent=2)
    response, finish_reason = ChatGPT_API_with_finish_reason(model=model, prompt=prompt)
    if finish_reason == "finished":
        result = extract_json(response)
        if isinstance(result, dict):
            result = [result]
        return result if isinstance(result, list) else []
    else:
        raise Exception(f"finish reason: {finish_reason}")


### add verify completeness
def generate_toc_init(part, model=None):
    print("start generate_toc_init")
    prompt = """
    You are an expert in extracting hierarchical tree structure, your task is to generate the tree structure of the document.

    The structure variable is the numeric system which represents the index of the hierarchy section in the table of contents. For example, the first section has structure index 1, the first subsection has structure index 1.1, the second subsection has structure index 1.2, etc.

    For the title, you need to extract the original title from the text, only fix the space inconsistency.

    The provided text contains tags like <physical_index_X> and <physical_index_X> to indicate the start and end of page X. 

    For the physical_index, you need to extract the physical index of the start of the section from the text. Keep the <physical_index_X> format.

    The response should be in the following format. 
        [
            {{
                "structure": <structure index, "x.x.x"> (string),
                "title": <title of the section, keep the original title>,
                "physical_index": "<physical_index_X> (keep the format)"
            }},
            
        ],


    Directly return the final JSON structure. Do not output anything else."""

    prompt = prompt + "\nGiven text\n:" + part
    response, finish_reason = ChatGPT_API_with_finish_reason(model=model, prompt=prompt)

    if finish_reason == "finished":
        result = extract_json(response)
        # Ensure we always return a list of items
        if isinstance(result, dict):
            result = [result]
        return result if isinstance(result, list) else []
    else:
        raise Exception(f"finish reason: {finish_reason}")


def process_no_toc(page_list, start_index=1, model=None, logger=None):
    page_contents = []
    token_lengths = []
    for page_index in range(start_index, start_index + len(page_list)):
        page_text = f"<physical_index_{page_index}>\n{page_list[page_index - start_index][0]}\n<physical_index_{page_index}>\n\n"
        page_contents.append(page_text)
        token_lengths.append(count_tokens(page_text, model))
    group_texts = page_list_to_group_text(page_contents, token_lengths)
    logger.info(f"len(group_texts): {len(group_texts)}")

    toc_with_page_number = generate_toc_init(group_texts[0], model)
    for group_text in group_texts[1:]:
        toc_with_page_number_additional = generate_toc_continue(toc_with_page_number, group_text, model)
        toc_with_page_number.extend(toc_with_page_number_additional)
    logger.info(f"generate_toc: {toc_with_page_number}")

    toc_with_page_number = convert_physical_index_to_int(toc_with_page_number)
    logger.info(f"convert_physical_index_to_int: {toc_with_page_number}")

    return toc_with_page_number


def process_toc_no_page_numbers(toc_content, toc_page_list, page_list, start_index=1, model=None, logger=None):
    page_contents = []
    token_lengths = []
    toc_content = toc_transformer(toc_content, model)
    logger.info(f"toc_transformer: {toc_content}")
    for page_index in range(start_index, start_index + len(page_list)):
        page_text = f"<physical_index_{page_index}>\n{page_list[page_index - start_index][0]}\n<physical_index_{page_index}>\n\n"
        page_contents.append(page_text)
        token_lengths.append(count_tokens(page_text, model))

    group_texts = page_list_to_group_text(page_contents, token_lengths)
    logger.info(f"len(group_texts): {len(group_texts)}")

    toc_with_page_number = copy.deepcopy(toc_content)
    for group_text in group_texts:
        toc_with_page_number = add_page_number_to_toc(group_text, toc_with_page_number, model)
    logger.info(f"add_page_number_to_toc: {toc_with_page_number}")

    toc_with_page_number = convert_physical_index_to_int(toc_with_page_number)
    logger.info(f"convert_physical_index_to_int: {toc_with_page_number}")

    return toc_with_page_number


def process_toc_with_page_numbers(
    toc_content, toc_page_list, page_list, toc_check_page_num=None, model=None, logger=None
):
    toc_with_page_number = toc_transformer(toc_content, model)
    logger.info(f"toc_with_page_number: {toc_with_page_number}")

    toc_no_page_number = remove_page_number(copy.deepcopy(toc_with_page_number))

    start_page_index = toc_page_list[-1] + 1
    main_content = ""
    for page_index in range(start_page_index, min(start_page_index + toc_check_page_num, len(page_list))):
        main_content += (
            f"<physical_index_{page_index + 1}>\n{page_list[page_index][0]}\n<physical_index_{page_index + 1}>\n\n"
        )

    toc_with_physical_index = toc_index_extractor(toc_no_page_number, main_content, model)
    logger.info(f"toc_with_physical_index: {toc_with_physical_index}")

    toc_with_physical_index = convert_physical_index_to_int(toc_with_physical_index)
    logger.info(f"toc_with_physical_index: {toc_with_physical_index}")

    matching_pairs = extract_matching_page_pairs(toc_with_page_number, toc_with_physical_index, start_page_index)
    logger.info(f"matching_pairs: {matching_pairs}")

    offset = calculate_page_offset(matching_pairs)
    logger.info(f"offset: {offset}")

    toc_with_page_number = add_page_offset_to_toc_json(toc_with_page_number, offset)
    logger.info(f"toc_with_page_number: {toc_with_page_number}")

    toc_with_page_number = process_none_page_numbers(toc_with_page_number, page_list, model=model)
    logger.info(f"toc_with_page_number: {toc_with_page_number}")

    return toc_with_page_number


##check if needed to process none page numbers
def process_none_page_numbers(toc_items, page_list, start_index=1, model=None):
    for i, item in enumerate(toc_items):
        if "physical_index" not in item:
            # logger.info(f"fix item: {item}")
            # Find previous physical_index
            prev_physical_index = 0  # Default if no previous item exists
            for j in range(i - 1, -1, -1):
                if toc_items[j].get("physical_index") is not None:
                    prev_physical_index = toc_items[j]["physical_index"]
                    break

            # Find next physical_index
            next_physical_index = -1  # Default if no next item exists
            for j in range(i + 1, len(toc_items)):
                if toc_items[j].get("physical_index") is not None:
                    next_physical_index = toc_items[j]["physical_index"]
                    break

            page_contents = []
            for page_index in range(prev_physical_index, next_physical_index + 1):
                # Add bounds checking to prevent IndexError
                list_index = page_index - start_index
                if list_index >= 0 and list_index < len(page_list):
                    page_text = (
                        f"<physical_index_{page_index}>\n{page_list[list_index][0]}\n<physical_index_{page_index}>\n\n"
                    )
                    page_contents.append(page_text)
                else:
                    continue

            item_copy = copy.deepcopy(item)
            del item_copy["page"]
            result = add_page_number_to_toc(page_contents, item_copy, model)
            if isinstance(result[0]["physical_index"], str) and result[0]["physical_index"].startswith(
                "<physical_index"
            ):
                item["physical_index"] = int(result[0]["physical_index"].split("_")[-1].rstrip(">").strip())
                del item["page"]

    return toc_items


def check_toc(page_list, opt=None):
    toc_page_list = find_toc_pages(start_page_index=0, page_list=page_list, opt=opt)
    if len(toc_page_list) == 0:
        print("no toc found")
        return {"toc_content": None, "toc_page_list": [], "page_index_given_in_toc": "no"}
    else:
        print("toc found")
        toc_json = toc_extractor(page_list, toc_page_list, opt.model)

        if toc_json["page_index_given_in_toc"] == "yes":
            print("index found")
            return {
                "toc_content": toc_json["toc_content"],
                "toc_page_list": toc_page_list,
                "page_index_given_in_toc": "yes",
            }
        else:
            current_start_index = toc_page_list[-1] + 1

            while (
                toc_json["page_index_given_in_toc"] == "no"
                and current_start_index < len(page_list)
                and current_start_index < opt.toc_check_page_num
            ):
                additional_toc_pages = find_toc_pages(
                    start_page_index=current_start_index, page_list=page_list, opt=opt
                )

                if len(additional_toc_pages) == 0:
                    break

                additional_toc_json = toc_extractor(page_list, additional_toc_pages, opt.model)
                if additional_toc_json["page_index_given_in_toc"] == "yes":
                    print("index found")
                    return {
                        "toc_content": additional_toc_json["toc_content"],
                        "toc_page_list": additional_toc_pages,
                        "page_index_given_in_toc": "yes",
                    }

                else:
                    current_start_index = additional_toc_pages[-1] + 1
            print("index not found")
            return {
                "toc_content": toc_json["toc_content"],
                "toc_page_list": toc_page_list,
                "page_index_given_in_toc": "no",
            }


################### fix incorrect toc #########################################################
def single_toc_item_index_fixer(section_title, content, model="gpt-4o-2024-11-20"):
    toc_extractor_prompt = """
    You are given a section title and several pages of a document, your job is to find the physical index of the start page of the section in the partial document.

    The provided pages contains tags like <physical_index_X> and <physical_index_X> to indicate the physical location of the page X.

    Reply in a JSON format:
    {
        "thinking": <explain which page, started and closed by <physical_index_X>, contains the start of this section>,
        "physical_index": "<physical_index_X>" (keep the format)
    }
    Directly return the final JSON structure. Do not output anything else."""

    prompt = toc_extractor_prompt + "\nSection Title:\n" + str(section_title) + "\nDocument pages:\n" + content
    response = ChatGPT_API(model=model, prompt=prompt)
    json_content = extract_json(response)
    return convert_physical_index_to_int(json_content.get("physical_index"))


async def fix_incorrect_toc(toc_with_page_number, page_list, incorrect_results, start_index=1, model=None, logger=None):
    print(f"start fix_incorrect_toc with {len(incorrect_results)} incorrect results")
    incorrect_indices = {result["list_index"] for result in incorrect_results}

    end_index = len(page_list) + start_index - 1

    incorrect_results_and_range_logs = []

    # Helper function to process and check a single incorrect item
    async def process_and_check_item(incorrect_item):
        list_index = incorrect_item["list_index"]

        # Check if list_index is valid
        if list_index < 0 or list_index >= len(toc_with_page_number):
            # Return an invalid result for out-of-bounds indices
            return {
                "list_index": list_index,
                "title": incorrect_item["title"],
                "physical_index": incorrect_item.get("physical_index"),
                "is_valid": False,
            }

        # Find the previous correct item
        prev_correct = None
        for i in range(list_index - 1, -1, -1):
            if i not in incorrect_indices and i >= 0 and i < len(toc_with_page_number):
                physical_index = toc_with_page_number[i].get("physical_index")
                if physical_index is not None:
                    prev_correct = physical_index
                    break
        # If no previous correct item found, use start_index
        if prev_correct is None:
            prev_correct = start_index - 1

        # Find the next correct item
        next_correct = None
        for i in range(list_index + 1, len(toc_with_page_number)):
            if i not in incorrect_indices and i >= 0 and i < len(toc_with_page_number):
                physical_index = toc_with_page_number[i].get("physical_index")
                if physical_index is not None:
                    next_correct = physical_index
                    break
        # If no next correct item found, use end_index
        if next_correct is None:
            next_correct = end_index

        incorrect_results_and_range_logs.append(
            {
                "list_index": list_index,
                "title": incorrect_item["title"],
                "prev_correct": prev_correct,
                "next_correct": next_correct,
            }
        )

        page_contents = []
        for page_index in range(prev_correct, next_correct + 1):
            # Add bounds checking to prevent IndexError
            list_index = page_index - start_index
            if list_index >= 0 and list_index < len(page_list):
                page_text = (
                    f"<physical_index_{page_index}>\n{page_list[list_index][0]}\n<physical_index_{page_index}>\n\n"
                )
                page_contents.append(page_text)
            else:
                continue
        content_range = "".join(page_contents)

        physical_index_int = single_toc_item_index_fixer(incorrect_item["title"], content_range, model)

        # Check if the result is correct
        check_item = incorrect_item.copy()
        check_item["physical_index"] = physical_index_int
        check_result = await check_title_appearance(check_item, page_list, start_index, model)

        return {
            "list_index": list_index,
            "title": incorrect_item["title"],
            "physical_index": physical_index_int,
            "is_valid": check_result["answer"] == "yes",
        }

    # Process incorrect items concurrently
    tasks = [process_and_check_item(item) for item in incorrect_results]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for item, result in zip(incorrect_results, results):
        if isinstance(result, Exception):
            print(f"Processing item {item} generated an exception: {result}")
            continue
    results = [result for result in results if not isinstance(result, Exception)]

    # Update the toc_with_page_number with the fixed indices and check for any invalid results
    invalid_results = []
    for result in results:
        if result["is_valid"]:
            # Add bounds checking to prevent IndexError
            list_idx = result["list_index"]
            if 0 <= list_idx < len(toc_with_page_number):
                toc_with_page_number[list_idx]["physical_index"] = result["physical_index"]
            else:
                # Index is out of bounds, treat as invalid
                invalid_results.append(
                    {
                        "list_index": result["list_index"],
                        "title": result["title"],
                        "physical_index": result["physical_index"],
                    }
                )
        else:
            invalid_results.append(
                {
                    "list_index": result["list_index"],
                    "title": result["title"],
                    "physical_index": result["physical_index"],
                }
            )

    logger.info(f"incorrect_results_and_range_logs: {incorrect_results_and_range_logs}")
    logger.info(f"invalid_results: {invalid_results}")

    return toc_with_page_number, invalid_results


async def fix_incorrect_toc_with_retries(
    toc_with_page_number, page_list, incorrect_results, start_index=1, max_attempts=3, model=None, logger=None
):
    print("start fix_incorrect_toc")
    fix_attempt = 0
    current_toc = toc_with_page_number
    current_incorrect = incorrect_results

    while current_incorrect:
        print(f"Fixing {len(current_incorrect)} incorrect results")

        current_toc, current_incorrect = await fix_incorrect_toc(
            current_toc, page_list, current_incorrect, start_index, model, logger
        )

        fix_attempt += 1
        if fix_attempt >= max_attempts:
            logger.info("Maximum fix attempts reached")
            break

    return current_toc, current_incorrect


################### verify toc #########################################################
async def verify_toc(page_list, list_result, start_index=1, N=None, model=None):
    print("start verify_toc")
    # Find the last non-None physical_index
    last_physical_index = None
    for item in reversed(list_result):
        if item.get("physical_index") is not None:
            last_physical_index = item["physical_index"]
            break

    # Early return if we don't have valid physical indices
    if last_physical_index is None or last_physical_index < len(page_list) / 2:
        # Return all items as incorrect so the caller can attempt fixes
        all_incorrect = [
            {**item, "list_index": idx, "answer": "no"}
            for idx, item in enumerate(list_result)
            if item.get("physical_index") is not None
        ]
        return 0, all_incorrect

    # Determine which items to check
    if N is None:
        print("check all items")
        sample_indices = range(0, len(list_result))
    else:
        N = min(N, len(list_result))
        print(f"check {N} items")
        sample_indices = random.sample(range(0, len(list_result)), N)

    # Prepare items with their list indices
    indexed_sample_list = []
    for idx in sample_indices:
        item = list_result[idx]
        # Skip items with None physical_index (these were invalidated by validate_and_truncate_physical_indices)
        if item.get("physical_index") is not None:
            item_with_index = item.copy()
            item_with_index["list_index"] = idx  # Add the original index in list_result
            indexed_sample_list.append(item_with_index)

    # Run checks concurrently
    tasks = [check_title_appearance(item, page_list, start_index, model) for item in indexed_sample_list]
    results = await asyncio.gather(*tasks)

    # Process results
    correct_count = 0
    incorrect_results = []
    for result in results:
        if result["answer"] == "yes":
            correct_count += 1
        else:
            incorrect_results.append(result)

    # Calculate accuracy
    checked_count = len(results)
    accuracy = correct_count / checked_count if checked_count > 0 else 0
    print(f"accuracy: {accuracy * 100:.2f}%")
    return accuracy, incorrect_results


################### main process #########################################################
async def meta_processor(
    page_list, mode=None, toc_content=None, toc_page_list=None, start_index=1, opt=None, logger=None
):
    print(mode)
    print(f"start_index: {start_index}")

    if mode == "process_toc_with_page_numbers":
        toc_with_page_number = process_toc_with_page_numbers(
            toc_content,
            toc_page_list,
            page_list,
            toc_check_page_num=opt.toc_check_page_num,
            model=opt.model,
            logger=logger,
        )
    elif mode == "process_toc_no_page_numbers":
        toc_with_page_number = process_toc_no_page_numbers(
            toc_content, toc_page_list, page_list, model=opt.model, logger=logger
        )
    else:
        toc_with_page_number = process_no_toc(page_list, start_index=start_index, model=opt.model, logger=logger)

    toc_with_page_number = [
        item for item in toc_with_page_number if isinstance(item, dict) and item.get("physical_index") is not None
    ]

    toc_with_page_number = validate_and_truncate_physical_indices(
        toc_with_page_number, len(page_list), start_index=start_index, logger=logger
    )

    accuracy, incorrect_results = await verify_toc(
        page_list, toc_with_page_number, start_index=start_index, model=opt.model
    )

    logger.info({"mode": "process_toc_with_page_numbers", "accuracy": accuracy, "incorrect_results": incorrect_results})
    if accuracy == 1.0 and len(incorrect_results) == 0:
        return toc_with_page_number
    if len(incorrect_results) > 0 and accuracy > 0.6:
        toc_with_page_number, incorrect_results = await fix_incorrect_toc_with_retries(
            toc_with_page_number,
            page_list,
            incorrect_results,
            start_index=start_index,
            max_attempts=3,
            model=opt.model,
            logger=logger,
        )
        return toc_with_page_number

    # Fallback cascade: try progressively simpler methods
    if mode == "process_toc_with_page_numbers":
        return await meta_processor(
            page_list,
            mode="process_toc_no_page_numbers",
            toc_content=toc_content,
            toc_page_list=toc_page_list,
            start_index=start_index,
            opt=opt,
            logger=logger,
        )
    elif mode == "process_toc_no_page_numbers":
        return await meta_processor(page_list, mode="process_no_toc", start_index=start_index, opt=opt, logger=logger)
    else:
        # process_no_toc is the last resort.
        # Try to fix incorrect items if we have any.
        if len(incorrect_results) > 0 and toc_with_page_number:
            logger.info({"mode": mode, "note": "Attempting fixes on low-accuracy TOC", "accuracy": accuracy})
            toc_with_page_number, _ = await fix_incorrect_toc_with_retries(
                toc_with_page_number,
                page_list,
                incorrect_results,
                start_index=start_index,
                max_attempts=3,
                model=opt.model,
                logger=logger,
            )
            return toc_with_page_number
        # Return whatever we have rather than crashing
        if toc_with_page_number:
            logger.info({"mode": mode, "note": "Returning best-effort TOC despite low accuracy", "accuracy": accuracy})
            return toc_with_page_number
        raise Exception("Processing failed: no TOC entries could be extracted")


async def process_large_node_recursively(node, page_list, opt=None, logger=None):
    node_page_list = page_list[node["start_index"] - 1 : node["end_index"]]
    token_num = sum([page[1] for page in node_page_list])

    if (
        node["end_index"] - node["start_index"] > opt.max_page_num_each_node
        and token_num >= opt.max_token_num_each_node
    ):
        print(
            "large node:",
            node["title"],
            "start_index:",
            node["start_index"],
            "end_index:",
            node["end_index"],
            "token_num:",
            token_num,
        )

        node_toc_tree = await meta_processor(
            node_page_list, mode="process_no_toc", start_index=node["start_index"], opt=opt, logger=logger
        )
        node_toc_tree = await check_title_appearance_in_start_concurrent(
            node_toc_tree, page_list, model=opt.model, logger=logger
        )

        # Filter out items with None physical_index before post_processing
        valid_node_toc_items = [item for item in node_toc_tree if item.get("physical_index") is not None]

        if valid_node_toc_items and node["title"].strip() == valid_node_toc_items[0]["title"].strip():
            node["nodes"] = post_processing(valid_node_toc_items[1:], node["end_index"])
            node["end_index"] = (
                valid_node_toc_items[1]["start_index"] if len(valid_node_toc_items) > 1 else node["end_index"]
            )
        else:
            node["nodes"] = post_processing(valid_node_toc_items, node["end_index"])
            node["end_index"] = valid_node_toc_items[0]["start_index"] if valid_node_toc_items else node["end_index"]

    if "nodes" in node and node["nodes"]:
        tasks = [
            process_large_node_recursively(child_node, page_list, opt, logger=logger) for child_node in node["nodes"]
        ]
        await asyncio.gather(*tasks)

    return node


async def tree_parser(page_list, opt, doc=None, logger=None):
    check_toc_result = check_toc(page_list, opt)
    logger.info(check_toc_result)

    if (
        check_toc_result.get("toc_content")
        and check_toc_result["toc_content"].strip()
        and check_toc_result["page_index_given_in_toc"] == "yes"
    ):
        toc_with_page_number = await meta_processor(
            page_list,
            mode="process_toc_with_page_numbers",
            start_index=1,
            toc_content=check_toc_result["toc_content"],
            toc_page_list=check_toc_result["toc_page_list"],
            opt=opt,
            logger=logger,
        )
    else:
        toc_with_page_number = await meta_processor(
            page_list, mode="process_no_toc", start_index=1, opt=opt, logger=logger
        )

    toc_with_page_number = add_preface_if_needed(toc_with_page_number)
    toc_with_page_number = await check_title_appearance_in_start_concurrent(
        toc_with_page_number, page_list, model=opt.model, logger=logger
    )

    # Filter out items with None physical_index before post_processings
    valid_toc_items = [item for item in toc_with_page_number if item.get("physical_index") is not None]

    toc_tree = post_processing(valid_toc_items, len(page_list))
    tasks = [process_large_node_recursively(node, page_list, opt, logger=logger) for node in toc_tree]
    await asyncio.gather(*tasks)

    return toc_tree


def page_index_main(doc, opt=None):
    logger = JsonLogger(doc)

    is_valid_pdf = (isinstance(doc, str) and os.path.isfile(doc) and doc.lower().endswith(".pdf")) or isinstance(
        doc, BytesIO
    )
    if not is_valid_pdf:
        raise ValueError("Unsupported input type. Expected a PDF file path or BytesIO object.")

    print("Parsing PDF...")
    page_list = get_page_tokens(doc)

    logger.info({"total_page_number": len(page_list)})
    logger.info({"total_token": sum([page[1] for page in page_list])})

    async def page_index_builder():
        structure = await tree_parser(page_list, opt, doc=doc, logger=logger)
        if opt.if_add_node_id == "yes":
            write_node_id(structure)
        if opt.if_add_node_text == "yes":
            add_node_text(structure, page_list)
        if opt.if_add_node_summary == "yes":
            if opt.if_add_node_text == "no":
                add_node_text(structure, page_list)
            await generate_summaries_for_structure(structure, model=opt.model)
            if opt.if_add_node_text == "no":
                remove_structure_text(structure)
            if opt.if_add_doc_description == "yes":
                # Create a clean structure without unnecessary fields for description generation
                clean_structure = create_clean_structure_for_description(structure)
                doc_description = generate_doc_description(clean_structure, model=opt.model)
                return {
                    "doc_name": get_pdf_name(doc),
                    "doc_description": doc_description,
                    "structure": structure,
                }
        return {
            "doc_name": get_pdf_name(doc),
            "structure": structure,
        }

    return asyncio.run(page_index_builder())


def page_index(
    doc,
    model=None,
    toc_check_page_num=None,
    max_page_num_each_node=None,
    max_token_num_each_node=None,
    if_add_node_id=None,
    if_add_node_summary=None,
    if_add_doc_description=None,
    if_add_node_text=None,
):
    user_opt = {arg: value for arg, value in locals().items() if arg != "doc" and value is not None}
    opt = ConfigLoader().load(user_opt)
    return page_index_main(doc, opt)


def validate_and_truncate_physical_indices(toc_with_page_number, page_list_length, start_index=1, logger=None):
    """
    Validates and truncates physical indices that exceed the actual document length.
    This prevents errors when TOC references pages that don't exist in the document (e.g. the file is broken or incomplete).
    """
    if not toc_with_page_number:
        return toc_with_page_number

    max_allowed_page = page_list_length + start_index - 1
    truncated_items = []

    for i, item in enumerate(toc_with_page_number):
        if item.get("physical_index") is not None:
            original_index = item["physical_index"]
            if original_index > max_allowed_page:
                item["physical_index"] = None
                truncated_items.append({"title": item.get("title", "Unknown"), "original_index": original_index})
                if logger:
                    logger.info(
                        f"Removed physical_index for '{item.get('title', 'Unknown')}' (was {original_index}, too far beyond document)"
                    )

    if truncated_items and logger:
        logger.info(f"Total removed items: {len(truncated_items)}")

    print(f"Document validation: {page_list_length} pages, max allowed index: {max_allowed_page}")
    if truncated_items:
        print(f"Truncated {len(truncated_items)} TOC items that exceeded document length")

    return toc_with_page_number
