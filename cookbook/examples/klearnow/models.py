from pydantic import BaseModel, Field


class LineItem(BaseModel):
    part_number: str = Field(description="The part number of the product")
    coo: str = Field(description="The country of origin of the product")
    description: str = Field(description="The description of the product. May contain numbers")
    price: float = Field(description="The price of the product. Product value per unit")
    country_of_melting: str = Field(description="The country of melting of the product")
    country_of_poor: str = Field(description="The country of poor of the product")
    weight: float = Field(description="The weight of the product in kilograms")
    value: float = Field(description="The value of the product per unit")
    page_number: int = Field(description="The page number of the product")
    document_name: str = Field(description="The name of the document")

class LineItems(BaseModel):
    line_items: list[LineItem] = Field(description="The line items of the order")
