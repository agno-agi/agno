from typing import Optional

from agno.agent import Agent
from agno.compression.manager import CompressionManager
from agno.models.zhipu import Zhipu


def get_product_info(product_name: str) -> str:
    """
    Get detailed product information

    Args:
        product_name: The name of the product

    Returns:
        str: Detailed product information
    """
    products = {
        "laptop": """
            Product Name: Professional Laptop Pro 15
            Category: Electronics - Computers
            Manufacturer: TechCorp International
            Model Number: LP-PRO-15-2024
            Release Date: January 15, 2024
            
            Specifications:
            - Processor: Intel Core i9-13900H (14 cores, 20 threads, up to 5.4 GHz)
            - Memory: 32GB DDR5-5600MHz RAM (expandable to 64GB)
            - Storage: 1TB PCIe 4.0 NVMe SSD (2x M.2 slots available)
            - Display: 15.6-inch 4K OLED touchscreen (3840x2160, 400 nits, 100% DCI-P3)
            - Graphics: NVIDIA GeForce RTX 4070 8GB GDDR6
            - Battery: 90Wh lithium polymer, up to 12 hours typical usage
            - Weight: 2.1 kg (4.6 lbs)
            - Dimensions: 356mm x 234mm x 18.9mm
            
            Features:
            - Thunderbolt 4 ports (x3)
            - USB-A 3.2 Gen 2 (x2)
            - HDMI 2.1 output
            - SD card reader (UHS-II)
            - Wi-Fi 6E and Bluetooth 5.3
            - Backlit keyboard with per-key RGB
            - Windows Hello IR camera
            - Fingerprint reader integrated into power button
            
            Price: $2,499.99 USD
            Warranty: 3 years limited hardware warranty with optional extension
            Availability: In stock - ships within 2-3 business days
        """,
        "phone": """
            Product Name: SmartPhone X Pro Max
            Category: Electronics - Mobile Devices
            Manufacturer: MobileTech Corp
            Model Number: SPX-PM-256-BLK
            Release Date: March 10, 2024
            
            Specifications:
            - Display: 6.7-inch Super Retina XDR OLED (2796x1290, 120Hz ProMotion)
            - Processor: A17 Pro chip with 6-core CPU and 6-core GPU
            - Memory: 8GB RAM
            - Storage: 256GB internal (also available in 512GB and 1TB)
            - Camera System: Triple camera (48MP main, 12MP ultra-wide, 12MP telephoto 3x)
            - Front Camera: 12MP TrueDepth camera with Face ID
            - Battery: 4,422 mAh with fast charging (20W) and wireless charging (15W)
            - Connectivity: 5G, Wi-Fi 6E, Bluetooth 5.3, NFC, Ultra Wideband
            - Water Resistance: IP68 rating (6 meters for 30 minutes)
            - Operating System: iOS 17
            
            Features:
            - Ceramic Shield front cover
            - Surgical-grade stainless steel frame
            - Emergency SOS via satellite
            - Crash Detection technology
            - Advanced computational photography
            - Cinematic mode video recording in 4K
            - MagSafe wireless charging compatible
            
            Price: $1,199.99 USD
            Colors: Black, Silver, Gold, Deep Purple
            Warranty: 1 year limited warranty with optional AppleCare+
            Availability: In stock - free shipping
        """,
    }
    return products.get(product_name.lower(), f"Product '{product_name}' not found in database")


def get_user_orders(user_id: str) -> str:
    """
    Get user order history

    Args:
        user_id: The user ID to look up orders

    Returns:
        str: User order history
    """
    orders = {
        "user123": """
            User ID: user123
            Account Status: Premium Member since 2020
            Total Orders: 47
            Total Spent: $23,847.50
            
            Recent Orders:
            
            Order #10234 - Placed: 2024-01-15
            Status: Delivered
            Items:
            - Professional Laptop Pro 15 (x1) - $2,499.99
            - Laptop Carrying Case Premium (x1) - $79.99
            - Wireless Mouse Elite (x1) - $89.99
            Subtotal: $2,669.97
            Shipping: Free (Premium Member)
            Tax: $213.60
            Total: $2,883.57
            Delivery Date: 2024-01-18
            Tracking: Delivered to home address
            
            Order #10156 - Placed: 2023-12-20
            Status: Delivered
            Items:
            - SmartPhone X Pro Max 256GB (x1) - $1,199.99
            - Phone Case Clear (x1) - $29.99
            - Screen Protector Pack (x2) - $24.99
            Subtotal: $1,254.97
            Shipping: Free (Premium Member)
            Tax: $100.40
            Total: $1,355.37
            Delivery Date: 2023-12-23
            
            Order #9998 - Placed: 2023-11-05
            Status: Delivered
            Items:
            - Wireless Headphones Pro (x1) - $349.99
            - USB-C Cable 2m (x2) - $19.99
            Subtotal: $389.97
            Shipping: Free (Premium Member)
            Tax: $31.20
            Total: $421.17
            Delivery Date: 2023-11-08
        """,
        "user456": """
            User ID: user456
            Account Status: Standard Member since 2023
            Total Orders: 3
            Total Spent: $487.96
            
            Recent Orders:
            
            Order #10301 - Placed: 2024-01-20
            Status: Shipped
            Items:
            - Wireless Keyboard Compact (x1) - $129.99
            Subtotal: $129.99
            Shipping: $8.99
            Tax: $11.12
            Total: $150.10
            Expected Delivery: 2024-01-25
            Tracking: In transit - last scan Sacramento, CA
        """,
    }
    return orders.get(user_id, f"No orders found for user ID: {user_id}")


def test_tool_use():
    agent = Agent(
        model=Zhipu(id="glm-4.7"),
        tools=[get_product_info],
        instructions=[
            "You have access to a product database through tools.",
            "When asked about a product, always check the database first.",
            "Available products in the system: laptop, phone",
        ],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What are the specifications and price of the laptop?")
    # Verify tool usage
    assert any(msg.tool_calls for msg in response.messages)
    assert response.content is not None


def test_parallel_tool_calls():
    """Test calling multiple tools in parallel"""
    agent = Agent(
        model=Zhipu(id="glm-4.7"),
        tools=[get_product_info, get_user_orders],
        instructions="You must use the available tools to get information. Use both tools when needed.",
        markdown=True,
        telemetry=False,
    )

    response = agent.run("Get me the laptop product information and the order history for user123")

    # Verify tool usage
    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)
    assert len([call for call in tool_calls if call.get("type", "") == "function"]) >= 2
    assert response.content is not None


def test_tool_with_optional_parameters():
    """Test tool call with optional parameters"""

    def get_weather(city: Optional[str] = None):
        """
        Get the weather in a city

        Args:
            city: The city to get the weather for (default: Tokyo)
        """
        if city is None:
            return "Tokyo: 70°F, Cloudy"
        else:
            return f"{city}: 72°F, Sunny"

    agent = Agent(
        model=Zhipu(id="glm-4.7"),
        tools=[get_weather],
        instructions="You must use the get_weather tool to check weather information.",
        markdown=True,
        telemetry=False,
    )

    response = agent.run("Check the weather in Paris")

    # Verify tool usage
    assert any(msg.tool_calls for msg in response.messages)
    assert response.content is not None
    assert "72" in response.content or "Paris" in response.content


def test_tool_with_multiple_parameters():
    """Test tool call with multiple required parameters"""

    def calculate(operation: str, a: float, b: float):
        """
        Perform a calculation

        Args:
            operation: The operation to perform (add, subtract, multiply, divide)
            a: First number
            b: Second number
        """
        if operation == "add":
            return a + b
        elif operation == "subtract":
            return a - b
        elif operation == "multiply":
            return a * b
        elif operation == "divide":
            return a / b
        else:
            return "Unknown operation"

    agent = Agent(
        model=Zhipu(id="glm-4.7"),
        tools=[calculate],
        instructions="You must use the calculate tool to perform calculations. Never calculate directly.",
        markdown=True,
        telemetry=False,
    )

    response = agent.run("Use the calculator to multiply 15 by 23")

    # Verify tool usage
    assert any(msg.tool_calls for msg in response.messages)
    assert response.content is not None
    assert "345" in response.content  # 15 * 23 = 345


def test_compress_tool_results():
    """Test compress_tool_results parameter effect - shows compression reduces tool result size"""

    agent_no_compress = Agent(
        model=Zhipu(id="glm-4.7"),
        tools=[get_product_info, get_user_orders],
        instructions="You must use the available tools to get information. Use both tools when requested.",
        compress_tool_results=False,
        markdown=True,
        telemetry=False,
    )

    agent_compress = Agent(
        model=Zhipu(id="glm-4.7"),
        tools=[get_product_info, get_user_orders],
        instructions="You must use the available tools to get information. Use both tools when requested.",
        compress_tool_results=True,
        compression_manager=CompressionManager(compress_tool_results_limit=2),  # 降低阈值到 2
        markdown=True,
        telemetry=False,
    )

    query = "Get me the laptop product details and the order history for user123"

    response_no_compress = agent_no_compress.run(query)
    response_compress = agent_compress.run(query)

    # Get tool result message lengths
    tool_result_no_compress = sum(len(str(msg.content)) for msg in response_no_compress.messages if msg.role == "tool")
    tool_result_compress_actual = sum(
        len(str(msg.get_content(use_compressed_content=True)))
        for msg in response_compress.messages
        if msg.role == "tool"
    )

    # Both should work and return valid content
    assert response_no_compress.content is not None
    assert response_compress.content is not None
    assert any(msg.tool_calls for msg in response_no_compress.messages)
    assert any(msg.tool_calls for msg in response_compress.messages)

    # Compression should reduce tool result size
    print(f"\nTool result size without compression: {tool_result_no_compress} chars")
    print(f"Tool result size with compression (actual sent): {tool_result_compress_actual} chars")
    print(f"Compression ratio: {tool_result_compress_actual / tool_result_no_compress:.2%}")

    # Compressed version should be smaller (or equal if result already small)
    assert tool_result_compress_actual <= tool_result_no_compress

    # Both should contain relevant information
    assert "laptop" in response_no_compress.content.lower() or "professional" in response_no_compress.content.lower()
    assert "laptop" in response_compress.content.lower() or "professional" in response_compress.content.lower()
