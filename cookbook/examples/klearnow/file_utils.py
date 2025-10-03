from pathlib import Path
from typing import List

try:
    import PyPDF2
except ImportError:
    raise ImportError("PyPDF2 is required for PDF splitting. Install with: pip install PyPDF2")


from models import LineItem


def get_all_pdfs_in_directory(directory_path: Path) -> List[Path]:
    """
    Get all PDF files in the specified directory.
    
    Args:
        directory_path: Path to the directory containing PDFs
        
    Returns:
        List of PDF file paths
    """
    if not directory_path.exists():
        raise FileNotFoundError(f"Directory not found: {directory_path}")
    
    if not directory_path.is_dir():
        raise ValueError(f"Path is not a directory: {directory_path}")
    
    pdf_files = list(directory_path.glob("*.pdf"))
    if not pdf_files:
        raise ValueError(f"No PDF files found in directory: {directory_path}")
    
    print(f"Found {len(pdf_files)} PDF file(s) in {directory_path}")
    for pdf_file in pdf_files:
        print(f"  • {pdf_file.name}")
    
    return pdf_files


def split_pdf_pages(pdf_path: Path) -> List[tuple[bytes, int, str]]:
    """
    Split a multi-page PDF into separate single-page PDF data in memory.
    
    Args:
        pdf_path: Path to the source PDF file
        
    Returns:
        List of tuples containing (pdf_bytes, page_number, original_filename)
    """
    output_data = []
    
    with open(pdf_path, 'rb') as input_file:
        pdf_reader = PyPDF2.PdfReader(input_file)
        total_pages = len(pdf_reader.pages)
        
        # If only one page, return original file data
        if total_pages <= 1:
            input_file.seek(0)
            pdf_bytes = input_file.read()
            return [(pdf_bytes, 1, pdf_path.stem)]
        
        print(f"Splitting {pdf_path.name} ({total_pages} pages) in memory...")
        
        for page_num in range(total_pages):
            pdf_writer = PyPDF2.PdfWriter()
            pdf_writer.add_page(pdf_reader.pages[page_num])
            
            # Write PDF data to bytes buffer
            from io import BytesIO
            pdf_buffer = BytesIO()
            pdf_writer.write(pdf_buffer)
            pdf_bytes = pdf_buffer.getvalue()
            pdf_buffer.close()
            
            page_number = page_num + 1
            output_data.append((pdf_bytes, page_number, pdf_path.stem))
            print(f"Created in-memory page {page_number} of {pdf_path.name}")
    
    return output_data


def write_line_items_to_json(all_line_items: List[LineItem], directory_path: Path, pdf_files: List[Path]):
    """
    Write the line items to a JSON file.
    """
    import json
    from datetime import datetime
    
    output_data = {
        "extraction_timestamp": datetime.now().isoformat(),
        "source_directory": str(directory_path),
        "total_documents_processed": len(pdf_files),
        "total_line_items": len(all_line_items),
        "documents_processed": [pdf_file.name for pdf_file in pdf_files],
        "line_items": [
            {
                "document_name": item.document_name,
                "page_number": item.page_number,
                "part_number": item.part_number,
                "country_of_origin": item.coo,
                "description": item.description,
                "price": item.price,
                "country_of_melting": item.country_of_melting,
                "country_of_poor": item.country_of_poor,
                "weight": item.weight,
                "value": item.value,
                "document_name": item.document_name,
                "page_number": item.page_number
            }
            for item in all_line_items
        ]
    }
    
    # Create output filename based on timestamp
    output_filename = f"extracted_line_items.json"
    output_path = directory_path / output_filename
    
    with open(output_path, 'w', encoding='utf-8') as json_file:
        json.dump(output_data, json_file, indent=2, ensure_ascii=False)
    
    print(f"\n{'=' * 60}")
    print(f"✅ Exported {len(all_line_items)} line items to: {output_filename}")
    print(f"📁 Full path: {output_path}")
    print(f"📋 Processed documents: {', '.join([pdf_file.name for pdf_file in pdf_files])}")
    print(f"{'=' * 60}")
    return output_path


def write_line_items_to_csv(all_line_items: List[LineItem], directory_path: Path) -> Path:
    """
    Write the line items to a CSV file.
    
    Args:
        all_line_items: List of extracted line items
        directory_path: Directory to save the CSV file
        
    Returns:
        Path to the created CSV file
    """
    import csv
    
    # Create output filename
    csv_filename = f"extracted_line_items.csv"
    csv_path = directory_path / csv_filename
    
    # Define CSV headers - order matters for readability
    headers = [
        "part_number",
        "description",
        "price",
        "value",
        "weight",
        "country_of_origin",
        "country_of_melting",
        "country_of_poor",
        "document_name",
        "page_number"
    ]
    
    with open(csv_path, 'w', newline='', encoding='utf-8') as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=headers)
        
        # Write header row
        writer.writeheader()
        
        # Write data rows
        for item in all_line_items:
            writer.writerow({
                "part_number": item.part_number,
                "description": item.description,
                "price": item.price,
                "value": item.value,
                "weight": item.weight,
                "country_of_origin": item.coo,
                "country_of_melting": item.country_of_melting,
                "country_of_poor": item.country_of_poor,
                "document_name": item.document_name,
                "page_number": item.page_number
            })
    
    return csv_path