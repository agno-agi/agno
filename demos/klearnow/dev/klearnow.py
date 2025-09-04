"""Minimal example for AgentOS."""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.models.mistral import MistralChat
from agno.os import AgentOS
from pydantic import BaseModel, Field
from typing import List
from pathlib import Path
from agno.media import Image as AgnoImage
from agno.media import File as AgnoFile

from pdf2image import convert_from_path
from PIL import Image
import io
import asyncio


debug_mode = True

async def process_page_async(page_num: int, jpg_bytes: bytes, pdf_filename: str) -> dict:
    """Process a single page asynchronously."""
    print(f"Processing page {page_num} of {pdf_filename}")
    
    # Create a new agent instance for this task
    invoice_agent = get_invoice_agent()
    
    try:
        response = await invoice_agent.arun(
            f"Can you extract the invoice information from this page of the document. If the document does not contain the word Invoice, then don't return anything and stop processing the image.",
            images=[AgnoImage(content=jpg_bytes, format="jpeg")]
        )
        
        result = {
            "page_num": page_num,
            "pdf_filename": pdf_filename,
            "response": response,
            "success": True
        }
        
        if response.content and response.content.header_invoice_number:
            print(f"Invoice number found on page {page_num} of {pdf_filename}: {response.content.header_invoice_number}")
            result["invoice_number"] = response.content.header_invoice_number
        else:
            print(f"No invoice information found on page {page_num} of {pdf_filename}")
            result["invoice_number"] = None
        
        if response.content and response.content.items:
            result["items"] = response.content.items
        else:
            result["items"] = []
            
        return result
        
    except Exception as e:
        print(f"Error processing page {page_num} of {pdf_filename}: {str(e)}")
        return {
            "page_num": page_num,
            "pdf_filename": pdf_filename,
            "response": None,
            "success": False,
            "error": str(e),
            "invoice_number": None,
            "items": []
        }
def pdf_to_jpg_bytes(pdf_path: Path) -> List[bytes]:
    """Convert each page of a PDF to JPG bytes in memory."""
    # Convert PDF pages to PIL Image objects
    pages = convert_from_path(pdf_path, dpi=200)  # Adjust DPI as needed
    
    jpg_images_bytes = []
    for i, page in enumerate(pages):
        # Convert PIL Image to JPG bytes in memory
        img_bytes = io.BytesIO()
        page.save(img_bytes, format='JPEG', quality=95)
        img_bytes.seek(0)  # Reset pointer to beginning
        jpg_images_bytes.append(img_bytes.getvalue())  # Get the actual bytes
    
    return jpg_images_bytes

def pdf_to_jpg_bytes_single(pdf_path: Path) -> bytes:
    """Convert all pages of a PDF to a single concatenated JPG image in memory."""
    # Convert PDF pages to PIL Image objects
    pages = convert_from_path(pdf_path, dpi=200)  # Adjust DPI as needed
    
    if not pages:
        raise ValueError("No pages found in PDF")
    
    # Calculate dimensions for the concatenated image
    # We'll stack all pages vertically
    total_width = max(page.width for page in pages)
    total_height = sum(page.height for page in pages)
    
    # Create a new blank image with the calculated dimensions
    concatenated_image = Image.new('RGB', (total_width, total_height), 'white')
    
    # Paste each page into the concatenated image
    y_offset = 0
    for page in pages:
        # Center the page horizontally if it's narrower than the total width
        x_offset = (total_width - page.width) // 2
        concatenated_image.paste(page, (x_offset, y_offset))
        y_offset += page.height
    
    # Convert concatenated image to bytes
    img_bytes = io.BytesIO()
    concatenated_image.save(img_bytes, format='JPEG', quality=95)
    img_bytes.seek(0)  # Reset pointer to beginning
    
    # Also save the concatenated image as a JPEG file in the same directory as the PDF
    jpg_path = pdf_path.with_suffix('.jpg')
    print(f"Saving all {len(pages)} pages concatenated to {jpg_path}")
    with open(jpg_path, 'wb') as f:
        f.write(img_bytes.getvalue())
    
    return img_bytes.getvalue()  # Get the actual bytes

class TrackingNumber(BaseModel):
    tracking_number: str = Field(..., description="The tracking number is a 12 digit number with TRK# close to it")


class InvoiceItem(BaseModel):
    material_number: int = Field(..., description="The Material Number")
    item_description: str = Field(..., description="The item description")
    item_country_of_origin: str = Field(..., description="The item country of origin")
    item_unit_price: float = Field(..., description="The item unit price")
    item_extended_price: float = Field(..., description="The item extended price")
    item_unit_of_measure: str = Field(..., description="The item unit of measure UOM")
   

class Invoice(BaseModel):
    header_invoice_number: str = Field(..., description="The invoice number")
    header_invoice_date: str = Field(..., description="The invoice date is a date in the format of MM/DD/YYYY")
    header_invoice_delivery_from: str = Field(..., description="The invoice Delivery From address")
    header_invoice_delivery_to: str = Field(..., description="The invoice Delivery To address")

    items: List[InvoiceItem] = Field(..., description="The invoice items")

    
# Setup the database
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

def get_invoice_agent() -> Agent:
    invoice_agent = Agent(
    # model=MistralChat(id="mistral-small-latest"),
    model=OpenAIChat(id="gpt-4o"),
    name="Invoice analyst Agent",
    db=db,
    enable_session_summaries=True,
    enable_user_memories=True,
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
    instructions=[
        "You are an invoice analyst. You are given an invoice and you need to analyze it and provide a summary of the invoice.",
        # "You are given and image of one page of a document at a time, so all the information won't neccesarily be on the same page.",
        # "Not all pages you see are neccesarily invoices, so you should not assume that the page you see is an invoice.",
        "You are given a concatenated image of all the pages of the invoice, so be sure to look at all the pages.",
        "When you can not find the information requested, you should cleary state that you can not find the information.",
        "You should return the invoice number, date, delivery from, delivery to, and items if they are available on the page.",
        "When searching for the invoice number, you should look for the page with the words 'Invoice Number' or 'Invoice' in the page. and the invoice number should be close to it.",
    ],
    output_schema=Invoice,
    debug_mode=debug_mode,
)
    return invoice_agent

# Setup basic agents, teams and workflows


shipping_agent = Agent(
    name="Shipping Label Agent",
    db=db,
    enable_session_summaries=True,
    enable_user_memories=True,
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
    instructions=[
        "You are a shipping label analyst. You are given a shipping label and you need to analyze it and provide the tracking number.",
    ],
    output_schema=TrackingNumber,
    debug_mode=debug_mode,
)


shipping_label_path = Path(__file__).parent.joinpath("shipping.jpg")
invoice_path = Path(__file__).parent.joinpath("invoice.jpg")


# response = shipping_agent.print_response(
#     "Can you extract the tracking number from the image. The tracking number is a 12 digit number with TRK# close to it",
#     images=[Image(filepath=shipping_label_path)],
#     stream=True,
# )




# response = invoice_agent.print_response(
#     "Can you extract the invoice information from the image",
#     images=[Image(filepath=invoice_path)],
#     stream=True,
# )




async def process_all_pdfs():
    """Process all PDF files asynchronously."""
    data = Path(__file__).parent.joinpath("data/12 883197726334 Medtronic/")
    
    # Collect all tasks for concurrent execution
    tasks = []
    
    for pdf_file in data.iterdir():
        if pdf_file.is_file():
            if pdf_file.name.startswith("CI"):
                print(f"Converting {pdf_file.name} to JPG pages...")
                # Convert PDF pages to JPG bytes in memory
                # jpg_pages = pdf_to_jpg_bytes(pdf_file)
                jpg_page = pdf_to_jpg_bytes_single(pdf_file)
                invoice_agent = get_invoice_agent()
                response = invoice_agent.run(
                    f"Can you extract the invoice information from this page of the document.",
                    images=[AgnoImage(content=jpg_page, format="jpeg")]
                )
                print(response.content)
                # # Create async tasks for each page
                # for page_num, jpg_bytes in enumerate(jpg_pages, 1):
                #     task = process_page_async(page_num, jpg_bytes, pdf_file.name)
                #     tasks.append(task)
    
    # if not tasks:
    #     print("No PDF files found to process.")
    #     return []
    
    print(f"Processing {len(tasks)} pages concurrently...")
    
    # Execute all tasks concurrently
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Collect all invoice items from successful results
    invoice_items = []
    successful_results = []
    
    for result in results:
        if isinstance(result, Exception):
            print(f"Task failed with exception: {result}")
        elif result["success"]:
            successful_results.append(result)
            invoice_items.extend(result["items"])
        else:
            print(f"Task failed: {result.get('error', 'Unknown error')}")
    
    print(f"\nProcessing complete! Found {len(invoice_items)} invoice items across {len(successful_results)} pages.")
    return invoice_items

# Run the async function
if __name__ == "__main__":
    invoice_items = asyncio.run(process_all_pdfs())
    print(f"\nAll invoice items: {invoice_items}")



# for pdf_file in data.iterdir():
#     if pdf_file.is_file():
#         if pdf_file.name.startswith("CI"):
#             # Convert PDF pages to JPG bytes in memory
#             jpg_pages = pdf_to_jpg_bytes_single(pdf_file)
#             invoice_agent = get_invoice_agent()
#             # Process each page separately
#             response = invoice_agent.run(
#                 f"Can you extract the invoice information from this page of the document.",
#                 images=[AgnoImage(content=jpg_pages, format="jpeg")]
#             )
                
#             print(response.content)



# Setup our AgentOS app
# agent_os = AgentOS(
#     description="Demo app for klearnow",
#     os_id="klearnow-app",
#     agents=[invoice_agent, shipping_agent],
# )
# app = agent_os.get_app()


# if __name__ == "__main__":
#     """Run our AgentOS.

#     You can see the configuration and available apps at:
#     http://localhost:7777/config

#     """
#     agent_os.serve(app="klearnow:app", reload=True)
