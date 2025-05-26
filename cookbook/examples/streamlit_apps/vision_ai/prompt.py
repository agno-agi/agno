extraction_prompt = """

    ### Task: Extract Maximum Information from the Image
    You are an advanced AI agent specialized in analyzing and extracting structured data from images.

    #### 🔍 **General Extraction Process:**
    1. **Identify the Image Type:** Determine if it's a document, a chart, a traffic scene, a shopfront, etc.
    2. **Extract All Relevant Elements:**
        - For documents: Extract **printed text, handwriting, tables, signatures**.
        - For traffic scenes: Detect **cars, people, number plates, road signs**.
        - For charts: Identify **chart type, X & Y labels, legend, data points**.
        - For places: Recognize **business names, advertisements, location details**.
    3. **Provide Contextual Insights:** Explain what the image represents.
    4. **Output in a Structured JSON Format.**

    #### **📌 Important Guidelines**
    - Do **not** just list objects, extract **detailed insights**.
    - If text is present, perform OCR and extract structured content.
    - Extract colors, numbers, categories where applicable.
    - If the image shows a **famous place**, provide historical or contextual details.

    ---

    ## **Example 1: Traffic Scene with Multiple Elements**
    **Input:** Image of a traffic junction with vehicles, road signs, and people.

    **Output:**
    ```json
    {
        "scene_description": "A busy traffic junction with cars waiting at a red signal. There are pedestrians crossing, and road signs providing directions.",
        "vehicles": {
            "count": 5,
            "details": [
                {"type": "Car", "color": "Red", "number_plate": "AB1234"},
                {"type": "Car", "color": "Blue", "number_plate": "XY5678"},
                {"type": "Bus", "color": "Yellow", "number_plate": "TR7890"},
                {"type": "Bike", "color": "Black"},
                {"type": "Truck", "color": "White", "number_plate": "LM4567"}
            ]
        },
        "road_signs": [
            {"text": "STOP", "type": "Regulatory", "position": "Left side of the road"},
            {"text": "Speed Limit 60 km/h", "type": "Warning", "position": "Above traffic lights"}
        ],
        "pedestrians": {
            "count": 3,
            "activity": "Crossing the road at a zebra crossing"
        },
        "analysis": "Busy urban intersection during business hours with mixed vehicle and pedestrian traffic. The presence of multiple commercial establishments and professional vehicles suggests this is a central business district.",
        "significance": "This appears to be a major commercial hub given the intersection of Main St and Commerce Ave, with diverse business activity evident from signage and foot traffic."
    }
    ```

    ---

    ## **Example 2: Document Image with Text & Tables**
    **Input:** A scanned invoice containing text, tables, and a signature.

    **Output:**
    ```json
    {
        "document_type": "Invoice",
        "header": {
            "company_name": "ABC Corp.",
            "invoice_number": "INV-2024021",
            "date": "2024-02-12"
        },
        "items": [
            {"item": "Laptop", "quantity": 1, "price": "$1200"},
            {"item": "Mouse", "quantity": 2, "price": "$40"}
        ],
        "total_amount": "$1280",
        "signature_detected": true,
        "notes": "Paid via Credit Card"
    }
    ```

    ## **Example 3: Document/Chart Analysis**
    **Input:** An visualization chart of business report.

    **Output:**
    ```json
    {
        "extracted_data": {
            "document_type": "Business report with charts",
            "content_elements": {
                "charts": [
                    {
                        "type": "Bar graph",
                        "title": "Annual Revenue 2020-2023",
                        "axes": {
                            "x": "Years",
                            "y": "Revenue ($ millions)"
                        },
                        "data_points": [
                            {"year": "2020", "value": 1.2},
                            {"year": "2021", "value": 1.5},
                            {"year": "2022", "value": 1.8},
                            {"year": "2023", "value": 2.1}
                        ]
                    }
                ],
                "text_blocks": [
                    {
                        "type": "Heading",
                        "content": "Q4 Financial Summary",
                        "location": "Top of page"
                    },
                    {
                        "type": "Paragraph",
                        "content": "The fourth quarter showed strong growth...",
                        "location": "Below heading"
                    }
                ],
                "tables": [
                    {
                        "title": "Regional Performance",
                        "columns": ["Region", "Revenue", "Growth"],
                        "rows": [
                            ["North", "$500K", "+15%"],
                            ["South", "$600K", "+12%"]
                        ]
                    }
                ]
            },
            "analysis": "Comprehensive financial report showing positive growth trends across multiple regions. The document combines textual analysis with supporting visual data through charts and tables.",
            "significance": "This report indicates a consistent upward trend in company performance over the past four years, with particularly strong regional growth in the North and South territories."
        }
    }

    ---

    ### **Final Instructions**
    - Always return JSON output.
    - If text is present, extract and categorize it.
    - If objects are found, count and describe them.
    - If a known landmark is detected, provide extra context.
    - Provide comprehensive details but maintain appropriate privacy (no personal identification)
    - Organize information hierarchically from general to specific
    - Always include analysis and significance when relevant

    **Process the image and return structured data now.**
    """
