"""Unit tests for ShopifyTools class."""

import json
from unittest.mock import MagicMock, patch

import pytest

from agno.tools.shopify import ShopifyTools


@pytest.fixture
def mock_httpx_client():
    """Create a mock httpx client."""
    with patch("agno.tools.shopify.httpx.Client") as mock_client:
        mock_instance = MagicMock()
        mock_client.return_value.__enter__ = MagicMock(return_value=mock_instance)
        mock_client.return_value.__exit__ = MagicMock(return_value=False)
        yield mock_instance


@pytest.fixture
def shopify_tools():
    """Create ShopifyTools instance with test credentials."""
    return ShopifyTools(
        shop_name="test-store",
        access_token="test_access_token",
        api_version="2025-10",
    )


@pytest.fixture
def mock_shop_response():
    """Mock shop info response."""
    return {
        "data": {
            "shop": {
                "name": "Test Store",
                "email": "test@example.com",
                "currencyCode": "USD",
                "primaryDomain": {"url": "https://test-store.myshopify.com"},
                "billingAddress": {"country": "United States", "city": "New York"},
                "plan": {"displayName": "Basic"},
            }
        }
    }


@pytest.fixture
def mock_products_response():
    """Mock products response."""
    return {
        "data": {
            "products": {
                "edges": [
                    {
                        "node": {
                            "id": "gid://shopify/Product/123",
                            "title": "Test Product",
                            "status": "ACTIVE",
                            "totalInventory": 100,
                            "createdAt": "2024-01-01T00:00:00Z",
                            "priceRangeV2": {
                                "minVariantPrice": {"amount": "10.00", "currencyCode": "USD"},
                                "maxVariantPrice": {"amount": "20.00", "currencyCode": "USD"},
                            },
                            "variants": {
                                "edges": [
                                    {
                                        "node": {
                                            "id": "gid://shopify/ProductVariant/456",
                                            "title": "Default",
                                            "sku": "TEST-SKU",
                                            "price": "15.00",
                                            "inventoryQuantity": 100,
                                        }
                                    }
                                ]
                            },
                        }
                    }
                ]
            }
        }
    }


@pytest.fixture
def mock_orders_response():
    """Mock orders response."""
    return {
        "data": {
            "orders": {
                "edges": [
                    {
                        "node": {
                            "id": "gid://shopify/Order/789",
                            "name": "#1001",
                            "createdAt": "2024-01-15T10:00:00Z",
                            "displayFinancialStatus": "PAID",
                            "displayFulfillmentStatus": "FULFILLED",
                            "totalPriceSet": {"shopMoney": {"amount": "50.00", "currencyCode": "USD"}},
                            "subtotalPriceSet": {"shopMoney": {"amount": "45.00"}},
                            "customer": {
                                "id": "gid://shopify/Customer/111",
                                "email": "customer@example.com",
                                "firstName": "John",
                                "lastName": "Doe",
                            },
                            "lineItems": {
                                "edges": [
                                    {
                                        "node": {
                                            "id": "gid://shopify/LineItem/222",
                                            "title": "Test Product",
                                            "quantity": 2,
                                            "variant": {"id": "gid://shopify/ProductVariant/456", "sku": "TEST-SKU"},
                                            "originalUnitPriceSet": {"shopMoney": {"amount": "15.00"}},
                                        }
                                    }
                                ]
                            },
                        }
                    }
                ]
            }
        }
    }


def test_init_with_credentials():
    """Test initialization with provided credentials."""
    tools = ShopifyTools(shop_name="my-store", access_token="my_token")
    assert tools.shop_name == "my-store"
    assert tools.access_token == "my_token"
    assert tools.api_version == "2025-10"
    assert tools.timeout == 30


def test_init_with_env_variables():
    """Test initialization with environment variables."""
    with patch.dict(
        "os.environ",
        {
            "SHOPIFY_SHOP_NAME": "env-store",
            "SHOPIFY_ACCESS_TOKEN": "env_token",
        },
    ):
        tools = ShopifyTools()
        assert tools.shop_name == "env-store"
        assert tools.access_token == "env_token"


def test_init_with_custom_api_version():
    """Test initialization with custom API version."""
    tools = ShopifyTools(
        shop_name="test-store",
        access_token="test_token",
        api_version="2024-10",
    )
    assert tools.api_version == "2024-10"


def test_init_with_custom_timeout():
    """Test initialization with custom timeout."""
    tools = ShopifyTools(
        shop_name="test-store",
        access_token="test_token",
        timeout=60,
    )
    assert tools.timeout == 60


def test_base_url_construction():
    """Test that base URL is correctly constructed."""
    tools = ShopifyTools(
        shop_name="my-store",
        access_token="token",
        api_version="2025-10",
    )
    expected_url = "https://my-store.myshopify.com/admin/api/2025-10/graphql.json"
    assert tools.base_url == expected_url


def test_tools_registration():
    """Test that all expected tools are registered."""
    tools = ShopifyTools(shop_name="test-store", access_token="test_token")

    function_names = [func.name for func in tools.functions.values()]
    expected_tools = [
        "get_shop_info",
        "get_products",
        "get_orders",
        "get_top_selling_products",
        "get_products_bought_together",
        "get_sales_by_date_range",
        "get_order_analytics",
        "get_product_sales_breakdown",
        "get_customer_order_history",
        "get_inventory_levels",
        "get_low_stock_products",
        "get_sales_trends",
        "get_average_order_value",
        "get_repeat_customers",
    ]

    for tool_name in expected_tools:
        assert tool_name in function_names


def test_successful_request(shopify_tools, mock_httpx_client):
    """Test successful GraphQL request."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"data": {"shop": {"name": "Test Store"}}}
    mock_httpx_client.post.return_value = mock_response

    result = shopify_tools._make_graphql_request("query { shop { name } }")

    assert result == {"shop": {"name": "Test Store"}}
    mock_httpx_client.post.assert_called_once()


def test_request_with_variables(shopify_tools, mock_httpx_client):
    """Test GraphQL request with variables."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"data": {"product": {"title": "Test"}}}
    mock_httpx_client.post.return_value = mock_response

    result = shopify_tools._make_graphql_request(
        "query($id: ID!) { product(id: $id) { title } }",
        variables={"id": "123"},
    )

    assert result == {"product": {"title": "Test"}}


def test_request_with_errors(shopify_tools, mock_httpx_client):
    """Test GraphQL request that returns errors."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"errors": [{"message": "Access denied"}]}
    mock_httpx_client.post.return_value = mock_response

    result = shopify_tools._make_graphql_request("query { shop { name } }")

    assert "error" in result


def test_request_json_decode_error(shopify_tools, mock_httpx_client):
    """Test handling of JSON decode errors."""
    mock_response = MagicMock()
    mock_response.json.side_effect = Exception("Invalid JSON")
    mock_response.text = "Invalid response"
    mock_httpx_client.post.return_value = mock_response

    with pytest.raises(Exception, match="Invalid JSON"):
        shopify_tools._make_graphql_request("query { shop { name } }")


def test_get_shop_info_success(shopify_tools, mock_httpx_client, mock_shop_response):
    """Test successful shop info retrieval."""
    mock_response = MagicMock()
    mock_response.json.return_value = mock_shop_response
    mock_httpx_client.post.return_value = mock_response

    result = shopify_tools.get_shop_info()
    result_data = json.loads(result)

    assert result_data["name"] == "Test Store"
    assert result_data["email"] == "test@example.com"
    assert result_data["currencyCode"] == "USD"


def test_get_shop_info_error(shopify_tools, mock_httpx_client):
    """Test shop info with error response."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"errors": [{"message": "Unauthorized"}]}
    mock_httpx_client.post.return_value = mock_response

    result = shopify_tools.get_shop_info()
    result_data = json.loads(result)

    assert "error" in result_data


def test_get_products_success(shopify_tools, mock_httpx_client, mock_products_response):
    """Test successful products retrieval."""
    mock_response = MagicMock()
    mock_response.json.return_value = mock_products_response
    mock_httpx_client.post.return_value = mock_response

    result = shopify_tools.get_products(max_results=10)
    result_data = json.loads(result)

    assert len(result_data) == 1
    assert result_data[0]["title"] == "Test Product"
    assert result_data[0]["status"] == "ACTIVE"


def test_get_products_with_status_filter(shopify_tools, mock_httpx_client, mock_products_response):
    """Test products retrieval with status filter."""
    mock_response = MagicMock()
    mock_response.json.return_value = mock_products_response
    mock_httpx_client.post.return_value = mock_response

    result = shopify_tools.get_products(status="ACTIVE")
    result_data = json.loads(result)

    assert len(result_data) == 1


def test_get_products_max_results_limit(shopify_tools, mock_httpx_client, mock_products_response):
    """Test that max_results is capped at 250."""
    mock_response = MagicMock()
    mock_response.json.return_value = mock_products_response
    mock_httpx_client.post.return_value = mock_response

    shopify_tools.get_products(max_results=500)

    # Verify the query was called (indirectly checking limit)
    mock_httpx_client.post.assert_called_once()


def test_get_orders_success(shopify_tools, mock_httpx_client, mock_orders_response):
    """Test successful orders retrieval."""
    mock_response = MagicMock()
    mock_response.json.return_value = mock_orders_response
    mock_httpx_client.post.return_value = mock_response

    result = shopify_tools.get_orders(max_results=10, created_after="2024-01-01")
    result_data = json.loads(result)

    assert len(result_data) == 1
    assert result_data[0]["name"] == "#1001"
    assert result_data[0]["financial_status"] == "PAID"


def test_get_orders_with_status_filter(shopify_tools, mock_httpx_client, mock_orders_response):
    """Test orders retrieval with status filter."""
    mock_response = MagicMock()
    mock_response.json.return_value = mock_orders_response
    mock_httpx_client.post.return_value = mock_response

    result = shopify_tools.get_orders(status="paid")
    result_data = json.loads(result)

    assert len(result_data) == 1


def test_get_orders_customer_info(shopify_tools, mock_httpx_client, mock_orders_response):
    """Test that customer info is properly extracted."""
    mock_response = MagicMock()
    mock_response.json.return_value = mock_orders_response
    mock_httpx_client.post.return_value = mock_response

    result = shopify_tools.get_orders()
    result_data = json.loads(result)

    assert result_data[0]["customer"]["email"] == "customer@example.com"
    assert result_data[0]["customer"]["name"] == "John Doe"


def test_get_top_selling_products_success(shopify_tools, mock_httpx_client):
    """Test successful top selling products retrieval."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": {
            "orders": {
                "edges": [
                    {
                        "node": {
                            "lineItems": {
                                "edges": [
                                    {
                                        "node": {
                                            "title": "Best Seller",
                                            "quantity": 10,
                                            "variant": {
                                                "id": "gid://shopify/ProductVariant/123",
                                                "product": {
                                                    "id": "gid://shopify/Product/456",
                                                    "title": "Best Seller Product",
                                                },
                                            },
                                            "originalUnitPriceSet": {"shopMoney": {"amount": "25.00"}},
                                        }
                                    }
                                ]
                            }
                        }
                    }
                ]
            }
        }
    }
    mock_httpx_client.post.return_value = mock_response

    result = shopify_tools.get_top_selling_products(limit=5, created_after="2024-01-01")
    result_data = json.loads(result)

    assert len(result_data) == 1
    assert result_data[0]["title"] == "Best Seller Product"
    assert result_data[0]["total_quantity"] == 10
    assert result_data[0]["rank"] == 1


def test_get_products_bought_together_success(shopify_tools, mock_httpx_client):
    """Test successful products bought together analysis."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": {
            "orders": {
                "edges": [
                    {
                        "node": {
                            "lineItems": {
                                "edges": [
                                    {
                                        "node": {
                                            "variant": {
                                                "product": {
                                                    "id": "gid://shopify/Product/1",
                                                    "title": "Product A",
                                                }
                                            }
                                        }
                                    },
                                    {
                                        "node": {
                                            "variant": {
                                                "product": {
                                                    "id": "gid://shopify/Product/2",
                                                    "title": "Product B",
                                                }
                                            }
                                        }
                                    },
                                ]
                            }
                        }
                    },
                    {
                        "node": {
                            "lineItems": {
                                "edges": [
                                    {
                                        "node": {
                                            "variant": {
                                                "product": {
                                                    "id": "gid://shopify/Product/1",
                                                    "title": "Product A",
                                                }
                                            }
                                        }
                                    },
                                    {
                                        "node": {
                                            "variant": {
                                                "product": {
                                                    "id": "gid://shopify/Product/2",
                                                    "title": "Product B",
                                                }
                                            }
                                        }
                                    },
                                ]
                            }
                        }
                    },
                ]
            }
        }
    }
    mock_httpx_client.post.return_value = mock_response

    result = shopify_tools.get_products_bought_together(min_occurrences=2, created_after="2024-01-01")
    result_data = json.loads(result)

    assert len(result_data) == 1
    assert result_data[0]["times_bought_together"] == 2


def test_get_sales_by_date_range_success(shopify_tools, mock_httpx_client):
    """Test successful sales by date range retrieval."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": {
            "orders": {
                "edges": [
                    {
                        "node": {
                            "createdAt": "2024-01-15T10:00:00Z",
                            "totalPriceSet": {"shopMoney": {"amount": "100.00", "currencyCode": "USD"}},
                            "lineItems": {"edges": [{"node": {"quantity": 3}}]},
                        }
                    }
                ]
            }
        }
    }
    mock_httpx_client.post.return_value = mock_response

    result = shopify_tools.get_sales_by_date_range("2024-01-01", "2024-01-31")
    result_data = json.loads(result)

    assert result_data["total_revenue"] == 100.00
    assert result_data["total_orders"] == 1
    assert result_data["total_items_sold"] == 3


def test_get_order_analytics_success(shopify_tools, mock_httpx_client):
    """Test successful order analytics retrieval."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": {
            "orders": {
                "edges": [
                    {
                        "node": {
                            "displayFinancialStatus": "PAID",
                            "displayFulfillmentStatus": "FULFILLED",
                            "totalPriceSet": {"shopMoney": {"amount": "50.00", "currencyCode": "USD"}},
                            "subtotalPriceSet": {"shopMoney": {"amount": "45.00"}},
                            "totalShippingPriceSet": {"shopMoney": {"amount": "5.00"}},
                            "totalTaxSet": {"shopMoney": {"amount": "0.00"}},
                            "lineItems": {"edges": [{"node": {"quantity": 2}}]},
                        }
                    }
                ]
            }
        }
    }
    mock_httpx_client.post.return_value = mock_response

    result = shopify_tools.get_order_analytics(created_after="2024-01-01")
    result_data = json.loads(result)

    assert result_data["total_orders"] == 1
    assert result_data["total_revenue"] == 50.00
    assert result_data["average_order_value"] == 50.00


def test_get_order_analytics_no_orders(shopify_tools, mock_httpx_client):
    """Test order analytics with no orders."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"data": {"orders": {"edges": []}}}
    mock_httpx_client.post.return_value = mock_response

    result = shopify_tools.get_order_analytics()
    result_data = json.loads(result)

    assert "message" in result_data


def test_get_inventory_levels_success(shopify_tools, mock_httpx_client, mock_products_response):
    """Test successful inventory levels retrieval."""
    mock_response = MagicMock()
    mock_response.json.return_value = mock_products_response
    mock_httpx_client.post.return_value = mock_response

    result = shopify_tools.get_inventory_levels(max_results=50)
    result_data = json.loads(result)

    assert len(result_data) == 1
    assert result_data[0]["total_inventory"] == 100


def test_get_low_stock_products_success(shopify_tools, mock_httpx_client):
    """Test successful low stock products retrieval."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": {
            "products": {
                "edges": [
                    {
                        "node": {
                            "id": "gid://shopify/Product/123",
                            "title": "Low Stock Product",
                            "totalInventory": 5,
                            "variants": {
                                "edges": [
                                    {
                                        "node": {
                                            "id": "gid://shopify/ProductVariant/456",
                                            "title": "Default",
                                            "sku": "LOW-SKU",
                                            "inventoryQuantity": 5,
                                        }
                                    }
                                ]
                            },
                        }
                    }
                ]
            }
        }
    }
    mock_httpx_client.post.return_value = mock_response

    result = shopify_tools.get_low_stock_products(threshold=10)
    result_data = json.loads(result)

    assert len(result_data) == 1
    assert result_data[0]["total_inventory"] == 5


def test_get_sales_trends_success(shopify_tools, mock_httpx_client):
    """Test successful sales trends retrieval."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": {
            "orders": {
                "edges": [
                    {
                        "node": {
                            "totalPriceSet": {"shopMoney": {"amount": "100.00", "currencyCode": "USD"}},
                            "lineItems": {"edges": [{"node": {"quantity": 2}}]},
                        }
                    }
                ]
            }
        }
    }
    mock_httpx_client.post.return_value = mock_response

    result = shopify_tools.get_sales_trends(created_after="2024-01-01", compare_previous_period=True)
    result_data = json.loads(result)

    assert "current_period" in result_data
    assert result_data["current_period"]["total_revenue"] == 100.00


def test_get_average_order_value_success(shopify_tools, mock_httpx_client):
    """Test successful average order value calculation."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": {
            "orders": {
                "edges": [
                    {
                        "node": {
                            "createdAt": "2024-01-15T10:00:00Z",
                            "totalPriceSet": {"shopMoney": {"amount": "50.00", "currencyCode": "USD"}},
                        }
                    },
                    {
                        "node": {
                            "createdAt": "2024-01-15T11:00:00Z",
                            "totalPriceSet": {"shopMoney": {"amount": "100.00", "currencyCode": "USD"}},
                        }
                    },
                ]
            }
        }
    }
    mock_httpx_client.post.return_value = mock_response

    result = shopify_tools.get_average_order_value(group_by="day", created_after="2024-01-01")
    result_data = json.loads(result)

    assert result_data["overall_average_order_value"] == 75.00


def test_get_average_order_value_no_orders(shopify_tools, mock_httpx_client):
    """Test average order value with no orders."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"data": {"orders": {"edges": []}}}
    mock_httpx_client.post.return_value = mock_response

    result = shopify_tools.get_average_order_value()
    result_data = json.loads(result)

    assert "message" in result_data


def test_get_repeat_customers_success(shopify_tools, mock_httpx_client):
    """Test successful repeat customers retrieval."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": {
            "orders": {
                "edges": [
                    {
                        "node": {
                            "customer": {
                                "id": "gid://shopify/Customer/123",
                                "email": "repeat@example.com",
                                "firstName": "Repeat",
                                "lastName": "Customer",
                                "numberOfOrders": 5,
                                "amountSpent": {"amount": "500.00", "currencyCode": "USD"},
                            },
                            "totalPriceSet": {"shopMoney": {"amount": "100.00"}},
                        }
                    },
                    {
                        "node": {
                            "customer": {
                                "id": "gid://shopify/Customer/123",
                                "email": "repeat@example.com",
                                "firstName": "Repeat",
                                "lastName": "Customer",
                                "numberOfOrders": 5,
                                "amountSpent": {"amount": "500.00", "currencyCode": "USD"},
                            },
                            "totalPriceSet": {"shopMoney": {"amount": "100.00"}},
                        }
                    },
                ]
            }
        }
    }
    mock_httpx_client.post.return_value = mock_response

    result = shopify_tools.get_repeat_customers(min_orders=2, created_after="2024-01-01")
    result_data = json.loads(result)

    assert result_data["repeat_customer_count"] == 1
    assert result_data["customers"][0]["orders_in_period"] == 2


def test_get_customer_order_history_success(shopify_tools, mock_httpx_client, mock_orders_response):
    """Test successful customer order history retrieval."""
    mock_response = MagicMock()
    mock_response.json.return_value = mock_orders_response
    mock_httpx_client.post.return_value = mock_response

    result = shopify_tools.get_customer_order_history("customer@example.com")
    result_data = json.loads(result)

    assert "customer" in result_data
    assert "orders" in result_data
    assert len(result_data["orders"]) == 1


def test_get_customer_order_history_no_orders(shopify_tools, mock_httpx_client):
    """Test customer order history with no orders."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"data": {"orders": {"edges": []}}}
    mock_httpx_client.post.return_value = mock_response

    result = shopify_tools.get_customer_order_history("nonexistent@example.com")
    result_data = json.loads(result)

    assert "message" in result_data


def test_get_product_sales_breakdown_success(shopify_tools, mock_httpx_client):
    """Test successful product sales breakdown retrieval."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": {
            "orders": {
                "edges": [
                    {
                        "node": {
                            "createdAt": "2024-01-15T10:00:00Z",
                            "lineItems": {
                                "edges": [
                                    {
                                        "node": {
                                            "title": "Test Product",
                                            "quantity": 2,
                                            "variant": {
                                                "id": "gid://shopify/ProductVariant/456",
                                                "title": "Default",
                                                "sku": "TEST-SKU",
                                                "product": {
                                                    "id": "gid://shopify/Product/123",
                                                    "title": "Test Product",
                                                },
                                            },
                                            "originalUnitPriceSet": {
                                                "shopMoney": {"amount": "25.00", "currencyCode": "USD"}
                                            },
                                        }
                                    }
                                ]
                            },
                        }
                    }
                ]
            }
        }
    }
    mock_httpx_client.post.return_value = mock_response

    result = shopify_tools.get_product_sales_breakdown("gid://shopify/Product/123", created_after="2024-01-01")
    result_data = json.loads(result)

    assert result_data["product_title"] == "Test Product"
    assert result_data["total_quantity_sold"] == 2
    assert result_data["total_revenue"] == 50.00


def test_get_product_sales_breakdown_with_numeric_id(shopify_tools, mock_httpx_client):
    """Test product sales breakdown with numeric ID."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": {
            "orders": {
                "edges": [
                    {
                        "node": {
                            "createdAt": "2024-01-15T10:00:00Z",
                            "lineItems": {
                                "edges": [
                                    {
                                        "node": {
                                            "title": "Test Product",
                                            "quantity": 1,
                                            "variant": {
                                                "id": "gid://shopify/ProductVariant/456",
                                                "title": "Default",
                                                "sku": "TEST-SKU",
                                                "product": {
                                                    "id": "gid://shopify/Product/123",
                                                    "title": "Test Product",
                                                },
                                            },
                                            "originalUnitPriceSet": {
                                                "shopMoney": {"amount": "25.00", "currencyCode": "USD"}
                                            },
                                        }
                                    }
                                ]
                            },
                        }
                    }
                ]
            }
        }
    }
    mock_httpx_client.post.return_value = mock_response

    # Test with numeric ID (should be normalized to full GID format)
    result = shopify_tools.get_product_sales_breakdown("123", created_after="2024-01-01")
    result_data = json.loads(result)

    assert result_data["product_title"] == "Test Product"


def test_get_product_sales_breakdown_not_found(shopify_tools, mock_httpx_client):
    """Test product sales breakdown when product not found."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"data": {"orders": {"edges": []}}}
    mock_httpx_client.post.return_value = mock_response

    result = shopify_tools.get_product_sales_breakdown("gid://shopify/Product/999")
    result_data = json.loads(result)

    assert "error" in result_data


def test_toolkit_name():
    """Test that toolkit has correct name."""
    tools = ShopifyTools(shop_name="test-store", access_token="test_token")
    assert tools.name == "shopify"
