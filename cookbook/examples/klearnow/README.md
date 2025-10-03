# Klearnow PDF Line Item Extractor

An AI-powered system that extracts line items from PDF documents (invoices, purchase orders, etc.) using the Agno framework with concurrent processing for maximum performance.

## Features

- 🚀 **Concurrent Processing**: Process multiple PDFs and pages simultaneously
- 📄 **Multi-page Support**: Automatically splits and processes multi-page PDFs in memory
- 🧠 **AI Extraction**: Uses OpenAI GPT-4o-mini to extract structured line item data
- 📊 **Dual Export**: Outputs both JSON and CSV formats
- 🔍 **Complete Traceability**: Tracks document name and page number for each line item
- 💾 **Memory Efficient**: No temporary files created during processing

## Installation

1. Install required dependencies:
```bash
pip install agno PyPDF2
```

2. Set up your OpenAI API key:
```bash
export GOOGLE_API_KEY="your-api-key-here"
```

## Project Structure

```
klearnow/
├── README.md                    # This file
├── klearnow_agent.py           # Main processing script
├── models.py                   # Pydantic data models
├── file_utils.py              # PDF processing and export utilities
└── klearnow-importer-data/    # Directory containing PDF files to process
    ├── invoice_001.pdf
    ├── purchase_order_002.pdf
    └── ...
```

## Usage

### Basic Usage

1. Place your PDF files in the `klearnow-importer-data/` directory
2. Run the extraction:
```bash
python klearnow_agent.py
```

### What Gets Extracted

The system extracts the following information from each line item:

- **Document Info**: Document name, page number
- **Product Details**: Part number, description
- **Pricing**: Price per unit, total value
- **Physical**: Weight in kilograms
- **Origin**: Country of origin, country of melting, country of poor

### Example Output

**Console Output:**
```
Found 3 PDF file(s) in klearnow-importer-data
  • invoice_001.pdf
  • purchase_order_002.pdf
  • shipping_manifest_003.pdf

🚀 Starting processing of 3 document(s)...
📄 Processing 8 total page(s) across all documents...

✅ invoice_001 Page 1: Found 5 line items
✅ invoice_001 Page 2: Found 3 line items
✅ purchase_order_002 Page 1: Found 7 line items
...

📊 Processing Complete:
   • Total documents processed: 3
   • Total pages processed: 8
   • Pages with line items: 6
   • Total line items found: 23

✅ Exported 23 line items to:
   📄 JSON: extracted_line_items.json
   📊 CSV:  extracted_line_items.csv
```

## Output Formats

### JSON Output
```json
{
  "extraction_timestamp": "2024-01-15T10:30:45.123456",
  "source_directory": "/path/to/klearnow-importer-data",
  "total_documents_processed": 3,
  "total_line_items": 23,
  "documents_processed": ["invoice_001.pdf", "purchase_order_002.pdf"],
  "line_items": [
    {
      "document_name": "invoice_001",
      "page_number": 1,
      "part_number": "ABC123",
      "description": "Steel Widget Components",
      "price": 25.50,
      "value": 25.50,
      "weight": 1.2,
      "country_of_origin": "USA",
      "country_of_melting": "USA",
      "country_of_poor": "USA"
    }
  ]
}
```

### CSV Output
```csv
document_name,page_number,part_number,description,price,value,weight,country_of_origin,country_of_melting,country_of_poor
invoice_001,1,ABC123,"Steel Widget Components",25.50,25.50,1.2,USA,USA,USA
invoice_001,2,DEF456,"Aluminum Housing",15.75,15.75,0.8,China,China,China
```

## Configuration

### Customizing the Agent

You can modify the agent configuration in `klearnow_agent.py`:

```python
agent = Agent(
    name="Klearnow Import Data Extractor",
    model=Gemini(id="gemini-2.0-flash"),
    description="You are a helpful assistant that extracts line items from a PDF file.",
    instructions="Extract ALL line items from the attached file. If you don't find any line items, return an empty list.",
    output_schema=LineItems,
)
```

### Modifying Data Fields

To add or modify extracted fields, update the `LineItem` model in `models.py`:

```python
class LineItem(BaseModel):
    part_number: str = Field(description="The part number of the product")
    # Add your custom fields here
    custom_field: str = Field(description="Your custom field description")
```

## Performance

- **Concurrent Processing**: All pages are processed simultaneously using `asyncio.gather`
- **Memory Efficient**: PDF splitting happens in memory without temporary files
- **Scalable**: Handles 1 document or 100+ documents with the same efficiency

**Example Performance:**
- Single 10-page PDF: ~15-20 seconds
- 5 PDFs (20 pages total): ~20-25 seconds (concurrent processing)
- 10 PDFs (50 pages total): ~30-40 seconds

### Debug Mode

Enable debug mode for detailed logging:

```python
response = await agent.arun(
    prompt,
    files=[file_obj],
    debug_mode=True,  # Add this line
)
```