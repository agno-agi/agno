from textwrap import dedent
from agno.agent.agent import Agent
from agno.models.google import Gemini
from agno.media import File
from pathlib import Path
from typing import List
import asyncio
from file_utils import get_all_pdfs_in_directory, split_pdf_pages, write_line_items_to_json, write_line_items_to_csv
from models import LineItem, LineItems


async def process_pdf_page(pdf_bytes: bytes, page_number: int, original_document_name: str) -> tuple[List[LineItem], str]:
    """
    Process a single PDF page from in-memory data and extract line items.
    
    Args:
        pdf_bytes: PDF page data as bytes
        page_number: Page number for logging and data
        original_document_name: Name of the original document
        
    Returns:
        Tuple of (list of line items, page identifier)
    """
    page_identifier = f"{original_document_name}_page_{page_number}"
    print(f"\n🔄 Processing {original_document_name} - Page {page_number}")
    
    # Create a new agent for this task (agents are lightweight and can be created per task)
    agent = Agent(
        name="Klearnow Import Data Extractor",
        session_id=f"{original_document_name}_page_{page_number}",
        model=Gemini(id="gemini-2.0-flash"),
        description="You are a helpful assistant that extracts line items from a PDF file.",
        instructions="Extract ALL line items from the attached file. If you don't find any line items, return an empty list.",
        output_schema=LineItems,
    )
    
    try:
        # Enhanced prompt with page and document information
        prompt = dedent(f"""\
            Extract line items from the attached file.

                IMPORTANT: For each line item extracted, set:
                - page_number: {page_number}
                - document_name: {original_document_name}

                Extract all product line items with their complete details including part numbers, descriptions, prices, weights, values, and country information.
            """)
                        
        # Create File object from bytes data
        file_obj = File(
            content=pdf_bytes, 
            filename=f"{page_identifier}.pdf", 
            mime_type="application/pdf"
        )
        
        response = await agent.arun(
            prompt,
            files=[file_obj],
        )
        
        if response.content and hasattr(response.content, 'line_items'):
            page_line_items = response.content.line_items
            print(f"✅ {original_document_name} Page {page_number}: Found {len(page_line_items)} line items")
            return page_line_items, page_identifier
        else:
            print(f"⚠️  {original_document_name} Page {page_number}: No line items found")
            return [], page_identifier
            
    except Exception as e:
        print(f"❌ {original_document_name} Page {page_number}: Error processing - {str(e)}")
        return [], page_identifier


async def process_all_documents(pdf_files: List[Path]) -> List[LineItem]:
    """
    Process all PDF documents and their pages concurrently using asyncio.gather.
    
    Args:
        pdf_files: List of PDF file paths
        
    Returns:
        List of all extracted line items from all documents
    """
    print(f"\n🚀 Starting processing of {len(pdf_files)} document(s)...")
    
    # Collect all page processing tasks from all documents
    all_tasks = []
    
    for pdf_file in pdf_files:
        # Split each PDF into in-memory page data
        page_data_list = split_pdf_pages(pdf_file)
        
        # Create tasks for each page of this document
        for pdf_bytes, page_number, original_document_name in page_data_list:
            task = process_pdf_page(pdf_bytes, page_number, original_document_name)
            all_tasks.append(task)
    
    print(f"📄 Processing {len(all_tasks)} total page(s) across all documents...")
    
    # Run all tasks concurrently
    results = await asyncio.gather(*all_tasks, return_exceptions=True)
    
    # Aggregate results
    all_line_items = []
    successful_pages = 0
    
    for i, result in enumerate(results):
        if isinstance(result, tuple):
            line_items, page_identifier = result
            all_line_items.extend(line_items)
            if line_items:  # Only count pages with actual line items
                successful_pages += 1
        else:
            print(f"❌ Page {i + 1}: Exception occurred - {result}")
    
    print(f"\n📊 Processing Complete:")
    print(f"   • Total documents processed: {len(pdf_files)}")
    print(f"   • Total pages processed: {len(all_tasks)}")
    print(f"   • Pages with line items: {successful_pages}")
    print(f"   • Total line items found: {len(all_line_items)}")
    
    return all_line_items


# Main execution function
async def main(directory_path: Path):
    # Get all PDF files in the directory
    pdf_files = get_all_pdfs_in_directory(directory_path)
    
    # Process all documents concurrently
    all_line_items = await process_all_documents(pdf_files)
    
    # Print summary
    print(f"\n{'=' * 60}")
    print(f"SUMMARY: Found {len(all_line_items)} total line items across {len(pdf_files)} document(s)")
    print(f"{'=' * 60}")
    
    json_output_path = write_line_items_to_json(all_line_items, directory_path, pdf_files)
    csv_output_path = write_line_items_to_csv(all_line_items, directory_path)
    
    
    
    print(f"\n{'=' * 60}")
    print(f"✅ Exported {len(all_line_items)} line items to: {json_output_path}")
    print(f"✅ Exported {len(all_line_items)} line items to: {csv_output_path}")
    print(f"📋 Processed documents: {', '.join([pdf_file.name for pdf_file in pdf_files])}")
    print(f"{'=' * 60}")


# Run the async main function
if __name__ == "__main__":

    directory_path = Path(__file__).parent.joinpath("klearnow-importer-data")
    print(f"Processing documents in: {directory_path}")
    asyncio.run(main(directory_path))