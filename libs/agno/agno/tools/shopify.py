"""
Shopify Toolkit for Agno SDK

A toolkit for analyzing sales data, product performance, and customer insights using the Shopify Admin GraphQL API.
Requires a valid Shopify access token with appropriate scopes.

Required scopes:
- read_orders (for order and sales data)
- read_products (for product information)
- read_customers (for customer insights)
- read_analytics (for analytics data)
"""

import json
from collections import Counter
from datetime import datetime, timedelta
from itertools import combinations
from os import getenv
from typing import Any, Dict, List, Optional

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_debug


class ShopifyTools(Toolkit):
    """
    Shopify toolkit for analyzing sales data and product performance.

    Args:
        shop_name: Your Shopify store name (e.g., 'my-store' from my-store.myshopify.com).
        access_token: Shopify Admin API access token with required scopes.
        api_version: Shopify API version (default: '2025-10').
        timeout: Request timeout in seconds.
    """

    def __init__(
        self,
        shop_name: Optional[str] = None,
        access_token: Optional[str] = None,
        api_version: str = "2025-10",
        timeout: int = 30,
        **kwargs,
    ):
        self.shop_name = shop_name or getenv("SHOPIFY_SHOP_NAME")
        self.access_token = access_token or getenv("SHOPIFY_ACCESS_TOKEN")
        self.api_version = api_version
        self.timeout = timeout
        self.base_url = f"https://{self.shop_name}.myshopify.com/admin/api/{self.api_version}/graphql.json"

        tools: List[Any] = [
            self.get_shop_info,
            self.get_products,
            self.get_orders,
            self.get_top_selling_products,
            self.get_products_bought_together,
            self.get_sales_by_date_range,
            self.get_order_analytics,
            self.get_product_sales_breakdown,
            self.get_customer_order_history,
            self.get_inventory_levels,
            self.get_low_stock_products,
            self.get_sales_trends,
            self.get_average_order_value,
            self.get_repeat_customers,
        ]

        super().__init__(name="shopify", tools=tools, **kwargs)

    def _make_graphql_request(self, query: str, variables: Optional[Dict] = None) -> Dict:
        """Make an authenticated GraphQL request to the Shopify Admin API."""
        headers = {
            "X-Shopify-Access-Token": self.access_token or "",
            "Content-Type": "application/json",
        }

        body: Dict[str, Any] = {"query": query}
        if variables:
            body["variables"] = variables

        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                self.base_url,
                headers=headers,
                json=body,
            )

            try:
                result = response.json()
                if "errors" in result:
                    return {"error": result["errors"]}
                return result.get("data", {})
            except json.JSONDecodeError:
                return {"error": f"Failed to parse response: {response.text}"}

    def get_shop_info(self) -> str:
        """Get basic information about the Shopify store.

        Returns:
            JSON string containing shop name, email, currency, and other details.
        """
        log_debug("Fetching Shopify shop info")

        query = """
        query {
            shop {
                name
                email
                currencyCode
                primaryDomain {
                    url
                }
                billingAddress {
                    country
                    city
                }
                plan {
                    displayName
                }
            }
        }
        """

        result = self._make_graphql_request(query)

        if "error" in result:
            return json.dumps(result, indent=2)

        return json.dumps(result.get("shop", {}), indent=2)

    def get_products(
        self,
        max_results: int = 50,
        status: Optional[str] = None,
    ) -> str:
        """Get products from the store.

        Args:
            max_results: Maximum number of products to return (default 50, max 250).
            status: Filter by status - 'ACTIVE', 'ARCHIVED', or 'DRAFT' (optional).

        Returns:
            JSON string containing list of products with id, title, status, variants, and pricing.
        """
        log_debug(f"Fetching products: max_results={max_results}, status={status}")

        query_filter = ""
        if status:
            query_filter = f', query: "status:{status}"'

        query = f"""
        query {{
            products(first: {min(max_results, 250)}{query_filter}) {{
                edges {{
                    node {{
                        id
                        title
                        status
                        totalInventory
                        createdAt
                        updatedAt
                        priceRangeV2 {{
                            minVariantPrice {{
                                amount
                                currencyCode
                            }}
                            maxVariantPrice {{
                                amount
                                currencyCode
                            }}
                        }}
                        variants(first: 10) {{
                            edges {{
                                node {{
                                    id
                                    title
                                    sku
                                    price
                                    inventoryQuantity
                                }}
                            }}
                        }}
                    }}
                }}
            }}
        }}
        """

        result = self._make_graphql_request(query)

        if "error" in result:
            return json.dumps(result, indent=2)

        products = []
        for edge in result.get("products", {}).get("edges", []):
            node = edge["node"]
            products.append(
                {
                    "id": node["id"],
                    "title": node["title"],
                    "status": node["status"],
                    "total_inventory": node.get("totalInventory"),
                    "created_at": node.get("createdAt"),
                    "price_range": {
                        "min": node.get("priceRangeV2", {}).get("minVariantPrice", {}).get("amount"),
                        "max": node.get("priceRangeV2", {}).get("maxVariantPrice", {}).get("amount"),
                        "currency": node.get("priceRangeV2", {}).get("minVariantPrice", {}).get("currencyCode"),
                    },
                    "variants": [
                        {
                            "id": v["node"]["id"],
                            "title": v["node"]["title"],
                            "sku": v["node"].get("sku"),
                            "price": v["node"]["price"],
                            "inventory": v["node"].get("inventoryQuantity"),
                        }
                        for v in node.get("variants", {}).get("edges", [])
                    ],
                }
            )

        return json.dumps(products, indent=2)

    def get_orders(
        self,
        max_results: int = 50,
        status: Optional[str] = None,
        created_after: Optional[str] = None,
        created_before: Optional[str] = None,
    ) -> str:
        """Get recent orders from the store.

        Args:
            max_results: Maximum number of orders to return (default 50, max 250).
            status: Filter by financial status - 'paid', 'pending', 'refunded' (optional).
            created_after: Only include orders created after this date (YYYY-MM-DD format, optional).
            created_before: Only include orders created before this date (YYYY-MM-DD format, optional).

        Returns:
            JSON string containing list of orders with id, total, customer, and line items.
        """
        log_debug(
            f"Fetching orders: max_results={max_results}, status={status}, created_after={created_after}, created_before={created_before}"
        )

        query_parts = []
        if created_after:
            query_parts.append(f"created_at:>={created_after}")
        if created_before:
            query_parts.append(f"created_at:<={created_before}")
        if status:
            query_parts.append(f"financial_status:{status}")

        query_filter = " AND ".join(query_parts) if query_parts else ""
        query_param = f', query: "{query_filter}"' if query_filter else ""

        query = f"""
        query {{
            orders(first: {min(max_results, 250)}{query_param}, sortKey: CREATED_AT, reverse: true) {{
                edges {{
                    node {{
                        id
                        name
                        createdAt
                        displayFinancialStatus
                        displayFulfillmentStatus
                        totalPriceSet {{
                            shopMoney {{
                                amount
                                currencyCode
                            }}
                        }}
                        subtotalPriceSet {{
                            shopMoney {{
                                amount
                            }}
                        }}
                        customer {{
                            id
                            email
                            firstName
                            lastName
                        }}
                        lineItems(first: 50) {{
                            edges {{
                                node {{
                                    id
                                    title
                                    quantity
                                    variant {{
                                        id
                                        sku
                                    }}
                                    originalUnitPriceSet {{
                                        shopMoney {{
                                            amount
                                        }}
                                    }}
                                }}
                            }}
                        }}
                    }}
                }}
            }}
        }}
        """

        result = self._make_graphql_request(query)

        if "error" in result:
            return json.dumps(result, indent=2)

        orders = []
        for edge in result.get("orders", {}).get("edges", []):
            node = edge["node"]
            customer = node.get("customer") or {}
            orders.append(
                {
                    "id": node["id"],
                    "name": node["name"],
                    "created_at": node["createdAt"],
                    "financial_status": node.get("displayFinancialStatus"),
                    "fulfillment_status": node.get("displayFulfillmentStatus"),
                    "total": node.get("totalPriceSet", {}).get("shopMoney", {}).get("amount"),
                    "subtotal": node.get("subtotalPriceSet", {}).get("shopMoney", {}).get("amount"),
                    "currency": node.get("totalPriceSet", {}).get("shopMoney", {}).get("currencyCode"),
                    "customer": {
                        "id": customer.get("id"),
                        "email": customer.get("email"),
                        "name": f"{customer.get('firstName', '')} {customer.get('lastName', '')}".strip(),
                    }
                    if customer
                    else None,
                    "line_items": [
                        {
                            "id": item["node"]["id"],
                            "title": item["node"]["title"],
                            "quantity": item["node"]["quantity"],
                            "unit_price": item["node"]
                            .get("originalUnitPriceSet", {})
                            .get("shopMoney", {})
                            .get("amount"),
                            "sku": item["node"].get("variant", {}).get("sku") if item["node"].get("variant") else None,
                        }
                        for item in node.get("lineItems", {}).get("edges", [])
                    ],
                }
            )

        return json.dumps(orders, indent=2)

    def get_top_selling_products(
        self,
        limit: int = 10,
        created_after: Optional[str] = None,
        created_before: Optional[str] = None,
    ) -> str:
        """Get the top selling products by quantity sold.

        Analyzes order data to find which products sell the most.

        Args:
            limit: Number of top products to return (default 10).
            created_after: Only include orders created after this date (YYYY-MM-DD format, optional).
            created_before: Only include orders created before this date (YYYY-MM-DD format, optional).

        Returns:
            JSON string containing ranked list of top products with sales data.
        """
        log_debug(
            f"Calculating top selling products: limit={limit}, created_after={created_after}, created_before={created_before}"
        )

        query_parts = ["financial_status:paid"]
        if created_after:
            query_parts.append(f"created_at:>={created_after}")
        if created_before:
            query_parts.append(f"created_at:<={created_before}")
        query_filter = " AND ".join(query_parts)

        query = f"""
        query {{
            orders(first: 250, query: "{query_filter}", sortKey: CREATED_AT) {{
                edges {{
                    node {{
                        lineItems(first: 100) {{
                            edges {{
                                node {{
                                    title
                                    quantity
                                    variant {{
                                        id
                                        product {{
                                            id
                                            title
                                        }}
                                    }}
                                    originalUnitPriceSet {{
                                        shopMoney {{
                                            amount
                                        }}
                                    }}
                                }}
                            }}
                        }}
                    }}
                }}
            }}
        }}
        """

        result = self._make_graphql_request(query)

        if "error" in result:
            return json.dumps(result, indent=2)

        # Aggregate sales by product
        product_sales: Dict[str, Dict[str, Any]] = {}

        for order_edge in result.get("orders", {}).get("edges", []):
            for item_edge in order_edge["node"].get("lineItems", {}).get("edges", []):
                item = item_edge["node"]
                variant = item.get("variant")
                if not variant or not variant.get("product"):
                    continue

                product_id = variant["product"]["id"]
                product_title = variant["product"]["title"]
                quantity = item["quantity"]
                unit_price = float(item.get("originalUnitPriceSet", {}).get("shopMoney", {}).get("amount", 0))

                if product_id not in product_sales:
                    product_sales[product_id] = {
                        "id": product_id,
                        "title": product_title,
                        "total_quantity": 0,
                        "total_revenue": 0.0,
                        "order_count": 0,
                    }

                product_sales[product_id]["total_quantity"] += quantity
                product_sales[product_id]["total_revenue"] += quantity * unit_price
                product_sales[product_id]["order_count"] += 1

        # Sort by quantity and limit
        sorted_products = sorted(product_sales.values(), key=lambda x: x["total_quantity"], reverse=True)[:limit]

        # Add ranking
        for i, product in enumerate(sorted_products):
            product["rank"] = i + 1
            product["total_revenue"] = round(product["total_revenue"], 2)

        return json.dumps(sorted_products, indent=2)

    def get_products_bought_together(
        self,
        min_occurrences: int = 2,
        limit: int = 20,
        created_after: Optional[str] = None,
        created_before: Optional[str] = None,
    ) -> str:
        """Find products that are frequently bought together.

        Analyzes orders to find product pairs that appear together most often.
        Useful for cross-selling and bundle recommendations.

        Args:
            min_occurrences: Minimum times a pair must appear together (default 2).
            limit: Number of product pairs to return (default 20).
            created_after: Only include orders created after this date (YYYY-MM-DD format, optional).
            created_before: Only include orders created before this date (YYYY-MM-DD format, optional).

        Returns:
            JSON string containing ranked list of product pairs with co-occurrence count.
        """
        log_debug(f"Finding products bought together: created_after={created_after}, created_before={created_before}")

        query_parts = ["financial_status:paid"]
        if created_after:
            query_parts.append(f"created_at:>={created_after}")
        if created_before:
            query_parts.append(f"created_at:<={created_before}")
        query_filter = " AND ".join(query_parts)

        query = f"""
        query {{
            orders(first: 250, query: "{query_filter}") {{
                edges {{
                    node {{
                        lineItems(first: 100) {{
                            edges {{
                                node {{
                                    variant {{
                                        product {{
                                            id
                                            title
                                        }}
                                    }}
                                }}
                            }}
                        }}
                    }}
                }}
            }}
        }}
        """

        result = self._make_graphql_request(query)

        if "error" in result:
            return json.dumps(result, indent=2)

        # Count co-occurrences
        pair_counter: Counter = Counter()
        product_info: Dict[str, str] = {}

        for order_edge in result.get("orders", {}).get("edges", []):
            products_in_order = []
            for item_edge in order_edge["node"].get("lineItems", {}).get("edges", []):
                variant = item_edge["node"].get("variant")
                if variant and variant.get("product"):
                    product_id = variant["product"]["id"]
                    product_title = variant["product"]["title"]
                    products_in_order.append(product_id)
                    product_info[product_id] = product_title

            # Get unique products in this order and count pairs
            unique_products = list(set(products_in_order))
            if len(unique_products) >= 2:
                for pair in combinations(sorted(unique_products), 2):
                    pair_counter[pair] += 1

        # Filter by minimum occurrences and sort
        frequent_pairs = [
            {
                "product_1": {
                    "id": pair[0],
                    "title": product_info.get(pair[0], "Unknown"),
                },
                "product_2": {
                    "id": pair[1],
                    "title": product_info.get(pair[1], "Unknown"),
                },
                "times_bought_together": count,
            }
            for pair, count in pair_counter.most_common(limit)
            if count >= min_occurrences
        ]

        return json.dumps(frequent_pairs, indent=2)

    def get_sales_by_date_range(
        self,
        start_date: str,
        end_date: str,
    ) -> str:
        """Get sales summary for a specific date range.

        Args:
            start_date: Start date in YYYY-MM-DD format.
            end_date: End date in YYYY-MM-DD format.

        Returns:
            JSON string containing total revenue, order count, and daily breakdown.
        """
        log_debug(f"Fetching sales for date range: {start_date} to {end_date}")

        query = f"""
        query {{
            orders(first: 250, query: "created_at:>={start_date} AND created_at:<={end_date} AND financial_status:paid", sortKey: CREATED_AT) {{
                edges {{
                    node {{
                        createdAt
                        totalPriceSet {{
                            shopMoney {{
                                amount
                                currencyCode
                            }}
                        }}
                        lineItems(first: 100) {{
                            edges {{
                                node {{
                                    quantity
                                }}
                            }}
                        }}
                    }}
                }}
            }}
        }}
        """

        result = self._make_graphql_request(query)

        if "error" in result:
            return json.dumps(result, indent=2)

        # Aggregate data
        total_revenue = 0.0
        total_orders = 0
        total_items = 0
        daily_breakdown: Dict[str, Dict[str, Any]] = {}
        currency = None

        for order_edge in result.get("orders", {}).get("edges", []):
            order = order_edge["node"]
            amount = float(order.get("totalPriceSet", {}).get("shopMoney", {}).get("amount", 0))
            currency = order.get("totalPriceSet", {}).get("shopMoney", {}).get("currencyCode")
            date = order["createdAt"][:10]  # Extract date part

            items_in_order = sum(item["node"]["quantity"] for item in order.get("lineItems", {}).get("edges", []))

            total_revenue += amount
            total_orders += 1
            total_items += items_in_order

            if date not in daily_breakdown:
                daily_breakdown[date] = {"date": date, "revenue": 0.0, "orders": 0, "items": 0}
            daily_breakdown[date]["revenue"] += amount
            daily_breakdown[date]["orders"] += 1
            daily_breakdown[date]["items"] += items_in_order

        # Sort daily breakdown by date
        sorted_daily = sorted(daily_breakdown.values(), key=lambda x: x["date"])
        for day in sorted_daily:
            day["revenue"] = round(day["revenue"], 2)

        summary = {
            "period": {"start": start_date, "end": end_date},
            "total_revenue": round(total_revenue, 2),
            "total_orders": total_orders,
            "total_items_sold": total_items,
            "average_order_value": round(total_revenue / total_orders, 2) if total_orders > 0 else 0,
            "currency": currency,
            "daily_breakdown": sorted_daily,
        }

        return json.dumps(summary, indent=2)

    def get_order_analytics(
        self,
        created_after: Optional[str] = None,
        created_before: Optional[str] = None,
    ) -> str:
        """Get comprehensive order analytics for a time period.

        Provides metrics like total orders, revenue, average order value,
        fulfillment rates, and more.

        Args:
            created_after: Only include orders created after this date (YYYY-MM-DD format, optional).
            created_before: Only include orders created before this date (YYYY-MM-DD format, optional).

        Returns:
            JSON string containing various order metrics and statistics.
        """
        log_debug(f"Generating order analytics: created_after={created_after}, created_before={created_before}")

        query_parts = []
        if created_after:
            query_parts.append(f"created_at:>={created_after}")
        if created_before:
            query_parts.append(f"created_at:<={created_before}")
        query_filter = " AND ".join(query_parts) if query_parts else ""
        query_param = f', query: "{query_filter}"' if query_filter else ""

        query = f"""
        query {{
            orders(first: 250{query_param}, sortKey: CREATED_AT) {{
                edges {{
                    node {{
                        displayFinancialStatus
                        displayFulfillmentStatus
                        totalPriceSet {{
                            shopMoney {{
                                amount
                                currencyCode
                            }}
                        }}
                        subtotalPriceSet {{
                            shopMoney {{
                                amount
                            }}
                        }}
                        totalShippingPriceSet {{
                            shopMoney {{
                                amount
                            }}
                        }}
                        totalTaxSet {{
                            shopMoney {{
                                amount
                            }}
                        }}
                        lineItems(first: 100) {{
                            edges {{
                                node {{
                                    quantity
                                }}
                            }}
                        }}
                    }}
                }}
            }}
        }}
        """

        result = self._make_graphql_request(query)

        if "error" in result:
            return json.dumps(result, indent=2)

        orders = result.get("orders", {}).get("edges", [])

        if not orders:
            return json.dumps({"message": "No orders found in the specified period"}, indent=2)

        # Calculate metrics
        total_orders = len(orders)
        total_revenue = 0.0
        total_subtotal = 0.0
        total_shipping = 0.0
        total_tax = 0.0
        total_items = 0
        currency = None

        financial_status_counts: Counter = Counter()
        fulfillment_status_counts: Counter = Counter()
        order_values: List[float] = []

        for order_edge in orders:
            order = order_edge["node"]

            amount = float(order.get("totalPriceSet", {}).get("shopMoney", {}).get("amount", 0))
            currency = order.get("totalPriceSet", {}).get("shopMoney", {}).get("currencyCode")

            total_revenue += amount
            total_subtotal += float(order.get("subtotalPriceSet", {}).get("shopMoney", {}).get("amount", 0))
            total_shipping += float(order.get("totalShippingPriceSet", {}).get("shopMoney", {}).get("amount", 0))
            total_tax += float(order.get("totalTaxSet", {}).get("shopMoney", {}).get("amount", 0))

            order_values.append(amount)

            items = sum(item["node"]["quantity"] for item in order.get("lineItems", {}).get("edges", []))
            total_items += items

            financial_status_counts[order.get("displayFinancialStatus", "UNKNOWN")] += 1
            fulfillment_status_counts[order.get("displayFulfillmentStatus", "UNKNOWN")] += 1

        avg_order_value = total_revenue / total_orders if total_orders > 0 else 0
        avg_items_per_order = total_items / total_orders if total_orders > 0 else 0

        analytics = {
            "period": {
                "created_after": created_after,
                "created_before": created_before,
            },
            "total_orders": total_orders,
            "total_revenue": round(total_revenue, 2),
            "total_subtotal": round(total_subtotal, 2),
            "total_shipping": round(total_shipping, 2),
            "total_tax": round(total_tax, 2),
            "currency": currency,
            "average_order_value": round(avg_order_value, 2),
            "total_items_sold": total_items,
            "average_items_per_order": round(avg_items_per_order, 2),
            "min_order_value": round(min(order_values), 2) if order_values else 0,
            "max_order_value": round(max(order_values), 2) if order_values else 0,
            "financial_status_breakdown": dict(financial_status_counts),
            "fulfillment_status_breakdown": dict(fulfillment_status_counts),
        }

        return json.dumps(analytics, indent=2)

    def get_product_sales_breakdown(
        self,
        product_id: str,
        created_after: Optional[str] = None,
        created_before: Optional[str] = None,
    ) -> str:
        """Get detailed sales breakdown for a specific product.

        Args:
            product_id: The Shopify product ID (gid://shopify/Product/xxx or just the number).
            created_after: Only include orders created after this date (YYYY-MM-DD format, optional).
            created_before: Only include orders created before this date (YYYY-MM-DD format, optional).

        Returns:
            JSON string containing product sales data including quantity, revenue, and variant breakdown.
        """
        log_debug(f"Fetching sales breakdown for product: {product_id}")

        # Normalize product ID
        if not product_id.startswith("gid://"):
            product_id = f"gid://shopify/Product/{product_id}"

        query_parts = ["financial_status:paid"]
        if created_after:
            query_parts.append(f"created_at:>={created_after}")
        if created_before:
            query_parts.append(f"created_at:<={created_before}")
        query_filter = " AND ".join(query_parts)

        query = f"""
        query {{
            orders(first: 250, query: "{query_filter}") {{
                edges {{
                    node {{
                        createdAt
                        lineItems(first: 100) {{
                            edges {{
                                node {{
                                    title
                                    quantity
                                    variant {{
                                        id
                                        title
                                        sku
                                        product {{
                                            id
                                            title
                                        }}
                                    }}
                                    originalUnitPriceSet {{
                                        shopMoney {{
                                            amount
                                            currencyCode
                                        }}
                                    }}
                                }}
                            }}
                        }}
                    }}
                }}
            }}
        }}
        """

        result = self._make_graphql_request(query)

        if "error" in result:
            return json.dumps(result, indent=2)

        # Filter for specific product and aggregate
        product_title = None
        total_quantity = 0
        total_revenue = 0.0
        order_count = 0
        currency = None
        variant_breakdown: Dict[str, Dict[str, Any]] = {}
        daily_sales: Dict[str, Dict[str, Any]] = {}

        for order_edge in result.get("orders", {}).get("edges", []):
            order = order_edge["node"]
            order_date = order["createdAt"][:10]
            found_in_order = False

            for item_edge in order.get("lineItems", {}).get("edges", []):
                item = item_edge["node"]
                variant = item.get("variant")
                if not variant or not variant.get("product"):
                    continue

                if variant["product"]["id"] == product_id:
                    product_title = variant["product"]["title"]
                    quantity = item["quantity"]
                    unit_price = float(item.get("originalUnitPriceSet", {}).get("shopMoney", {}).get("amount", 0))
                    currency = item.get("originalUnitPriceSet", {}).get("shopMoney", {}).get("currencyCode")
                    variant_id = variant["id"]
                    variant_title = variant.get("title", "Default")

                    total_quantity += quantity
                    total_revenue += quantity * unit_price
                    found_in_order = True

                    # Variant breakdown
                    if variant_id not in variant_breakdown:
                        variant_breakdown[variant_id] = {
                            "variant_id": variant_id,
                            "variant_title": variant_title,
                            "sku": variant.get("sku"),
                            "quantity": 0,
                            "revenue": 0.0,
                        }
                    variant_breakdown[variant_id]["quantity"] += quantity
                    variant_breakdown[variant_id]["revenue"] += quantity * unit_price

                    # Daily breakdown
                    if order_date not in daily_sales:
                        daily_sales[order_date] = {"date": order_date, "quantity": 0, "revenue": 0.0}
                    daily_sales[order_date]["quantity"] += quantity
                    daily_sales[order_date]["revenue"] += quantity * unit_price

            if found_in_order:
                order_count += 1

        if product_title is None:
            return json.dumps({"error": "Product not found in any orders during this period"}, indent=2)

        # Format variants and daily data
        for v in variant_breakdown.values():
            v["revenue"] = round(v["revenue"], 2)

        sorted_daily = sorted(daily_sales.values(), key=lambda x: x["date"])
        for d in sorted_daily:
            d["revenue"] = round(d["revenue"], 2)

        breakdown = {
            "product_id": product_id,
            "product_title": product_title,
            "period": {
                "created_after": created_after,
                "created_before": created_before,
            },
            "total_quantity_sold": total_quantity,
            "total_revenue": round(total_revenue, 2),
            "order_count": order_count,
            "currency": currency,
            "average_units_per_order": round(total_quantity / order_count, 2) if order_count > 0 else 0,
            "variant_breakdown": list(variant_breakdown.values()),
            "daily_sales": sorted_daily,
        }

        return json.dumps(breakdown, indent=2)

    def get_customer_order_history(
        self,
        customer_email: str,
        max_orders: int = 50,
    ) -> str:
        """Get order history for a specific customer.

        Args:
            customer_email: The customer's email address.
            max_orders: Maximum number of orders to return (default 50).

        Returns:
            JSON string containing customer info and their order history.
        """
        log_debug(f"Fetching order history for customer: {customer_email}")

        query = f"""
        query {{
            orders(first: {min(max_orders, 250)}, query: "email:{customer_email}", sortKey: CREATED_AT, reverse: true) {{
                edges {{
                    node {{
                        id
                        name
                        createdAt
                        displayFinancialStatus
                        displayFulfillmentStatus
                        totalPriceSet {{
                            shopMoney {{
                                amount
                                currencyCode
                            }}
                        }}
                        customer {{
                            id
                            firstName
                            lastName
                            numberOfOrders
                            amountSpent {{
                                amount
                                currencyCode
                            }}
                        }}
                        lineItems(first: 20) {{
                            edges {{
                                node {{
                                    title
                                    quantity
                                }}
                            }}
                        }}
                    }}
                }}
            }}
        }}
        """

        result = self._make_graphql_request(query)

        if "error" in result:
            return json.dumps(result, indent=2)

        orders = result.get("orders", {}).get("edges", [])

        if not orders:
            return json.dumps({"message": f"No orders found for {customer_email}"}, indent=2)

        # Get customer info from first order
        first_customer = orders[0]["node"].get("customer", {}) if orders else {}

        customer_info = {
            "email": customer_email,
            "id": first_customer.get("id"),
            "name": f"{first_customer.get('firstName', '')} {first_customer.get('lastName', '')}".strip(),
            "total_orders": first_customer.get("numberOfOrders"),
            "total_spent": first_customer.get("amountSpent", {}).get("amount"),
            "currency": first_customer.get("amountSpent", {}).get("currencyCode"),
        }

        order_list = []
        for order_edge in orders:
            order = order_edge["node"]
            order_list.append(
                {
                    "id": order["id"],
                    "name": order["name"],
                    "created_at": order["createdAt"],
                    "financial_status": order.get("displayFinancialStatus"),
                    "fulfillment_status": order.get("displayFulfillmentStatus"),
                    "total": order.get("totalPriceSet", {}).get("shopMoney", {}).get("amount"),
                    "items": [
                        {"title": item["node"]["title"], "quantity": item["node"]["quantity"]}
                        for item in order.get("lineItems", {}).get("edges", [])
                    ],
                }
            )

        response = {
            "customer": customer_info,
            "orders": order_list,
        }

        return json.dumps(response, indent=2)

    def get_inventory_levels(
        self,
        max_results: int = 100,
    ) -> str:
        """Get current inventory levels for all products.

        Args:
            max_results: Maximum number of products to return (default 100).

        Returns:
            JSON string containing products with their inventory quantities.
        """
        log_debug(f"Fetching inventory levels: max_results={max_results}")

        query = f"""
        query {{
            products(first: {min(max_results, 250)}, query: "status:ACTIVE") {{
                edges {{
                    node {{
                        id
                        title
                        totalInventory
                        tracksInventory
                        variants(first: 50) {{
                            edges {{
                                node {{
                                    id
                                    title
                                    sku
                                    inventoryQuantity
                                    inventoryPolicy
                                }}
                            }}
                        }}
                    }}
                }}
            }}
        }}
        """

        result = self._make_graphql_request(query)

        if "error" in result:
            return json.dumps(result, indent=2)

        products = []
        for edge in result.get("products", {}).get("edges", []):
            node = edge["node"]
            products.append(
                {
                    "id": node["id"],
                    "title": node["title"],
                    "total_inventory": node.get("totalInventory"),
                    "tracks_inventory": node.get("tracksInventory"),
                    "variants": [
                        {
                            "id": v["node"]["id"],
                            "title": v["node"]["title"],
                            "sku": v["node"].get("sku"),
                            "inventory_quantity": v["node"].get("inventoryQuantity"),
                            "inventory_policy": v["node"].get("inventoryPolicy"),
                        }
                        for v in node.get("variants", {}).get("edges", [])
                    ],
                }
            )

        return json.dumps(products, indent=2)

    def get_low_stock_products(
        self,
        threshold: int = 10,
        max_results: int = 50,
    ) -> str:
        """Get products that are running low on stock.

        Args:
            threshold: Inventory level below which a product is considered low stock (default 10).
            max_results: Maximum number of products to return (default 50).

        Returns:
            JSON string containing low stock products sorted by inventory level.
        """
        log_debug(f"Finding low stock products: threshold={threshold}")

        query = """
        query {{
            products(first: 250, query: "status:ACTIVE") {{
                edges {{
                    node {{
                        id
                        title
                        totalInventory
                        variants(first: 50) {{
                            edges {{
                                node {{
                                    id
                                    title
                                    sku
                                    inventoryQuantity
                                }}
                            }}
                        }}
                    }}
                }}
            }}
        }}
        """

        result = self._make_graphql_request(query)

        if "error" in result:
            return json.dumps(result, indent=2)

        low_stock = []
        for edge in result.get("products", {}).get("edges", []):
            node = edge["node"]
            total_inv = node.get("totalInventory", 0)

            if total_inv is not None and total_inv <= threshold:
                low_stock_variants = [
                    {
                        "id": v["node"]["id"],
                        "title": v["node"]["title"],
                        "sku": v["node"].get("sku"),
                        "inventory_quantity": v["node"].get("inventoryQuantity"),
                    }
                    for v in node.get("variants", {}).get("edges", [])
                    if v["node"].get("inventoryQuantity") is not None and v["node"]["inventoryQuantity"] <= threshold
                ]

                if low_stock_variants:
                    low_stock.append(
                        {
                            "id": node["id"],
                            "title": node["title"],
                            "total_inventory": total_inv,
                            "low_stock_variants": low_stock_variants,
                        }
                    )

        # Sort by total inventory (lowest first)
        low_stock.sort(key=lambda x: x["total_inventory"])

        return json.dumps(low_stock[:max_results], indent=2)

    def get_sales_trends(
        self,
        created_after: Optional[str] = None,
        created_before: Optional[str] = None,
        compare_previous_period: bool = True,
    ) -> str:
        """Get sales trends comparing current period to previous period.

        Args:
            created_after: Start date for analysis period (YYYY-MM-DD format, optional).
            created_before: End date for analysis period (YYYY-MM-DD format, optional).
            compare_previous_period: Whether to compare with previous period of same length (default True).

        Returns:
            JSON string containing current period metrics and comparison with previous period.
        """
        log_debug(f"Calculating sales trends: created_after={created_after}, created_before={created_before}")

        # Use provided dates or default to last 30 days
        now = datetime.now()
        if created_before:
            current_end_dt = datetime.strptime(created_before, "%Y-%m-%d")
        else:
            current_end_dt = now
        current_end = current_end_dt.strftime("%Y-%m-%d")

        if created_after:
            current_start_dt = datetime.strptime(created_after, "%Y-%m-%d")
        else:
            current_start_dt = current_end_dt - timedelta(days=30)
        current_start = current_start_dt.strftime("%Y-%m-%d")

        # Calculate previous period of same length
        period_days = (current_end_dt - current_start_dt).days
        previous_end_dt = current_start_dt - timedelta(days=1)
        previous_start_dt = previous_end_dt - timedelta(days=period_days)
        previous_start = previous_start_dt.strftime("%Y-%m-%d")
        previous_end = previous_end_dt.strftime("%Y-%m-%d")

        def fetch_period_data(start: str, end: str) -> Dict[str, Any]:
            query = f"""
            query {{
                orders(first: 250, query: "created_at:>={start} AND created_at:<{end} AND financial_status:paid") {{
                    edges {{
                        node {{
                            totalPriceSet {{
                                shopMoney {{
                                    amount
                                    currencyCode
                                }}
                            }}
                            lineItems(first: 100) {{
                                edges {{
                                    node {{
                                        quantity
                                    }}
                                }}
                            }}
                        }}
                    }}
                }}
            }}
            """
            result = self._make_graphql_request(query)
            if "error" in result:
                return {"error": result["error"]}

            orders = result.get("orders", {}).get("edges", [])
            total_revenue = sum(
                float(o["node"].get("totalPriceSet", {}).get("shopMoney", {}).get("amount", 0)) for o in orders
            )
            total_items = sum(
                sum(item["node"]["quantity"] for item in o["node"].get("lineItems", {}).get("edges", []))
                for o in orders
            )
            currency = (
                orders[0]["node"].get("totalPriceSet", {}).get("shopMoney", {}).get("currencyCode") if orders else None
            )

            return {
                "total_orders": len(orders),
                "total_revenue": round(total_revenue, 2),
                "total_items_sold": total_items,
                "average_order_value": round(total_revenue / len(orders), 2) if orders else 0,
                "currency": currency,
            }

        current_data = fetch_period_data(current_start, current_end)
        if "error" in current_data:
            return json.dumps(current_data, indent=2)

        result = {
            "current_period": {
                "start": current_start,
                "end": current_end,
                **current_data,
            }
        }

        if compare_previous_period:
            previous_data = fetch_period_data(previous_start, previous_end)
            if "error" not in previous_data:
                result["previous_period"] = {
                    "start": previous_start,
                    "end": previous_end,
                    **previous_data,
                }

                # Calculate changes
                if previous_data["total_revenue"] > 0:
                    revenue_change = (
                        (current_data["total_revenue"] - previous_data["total_revenue"])
                        / previous_data["total_revenue"]
                    ) * 100
                else:
                    revenue_change = 100 if current_data["total_revenue"] > 0 else 0

                if previous_data["total_orders"] > 0:
                    orders_change = (
                        (current_data["total_orders"] - previous_data["total_orders"]) / previous_data["total_orders"]
                    ) * 100
                else:
                    orders_change = 100 if current_data["total_orders"] > 0 else 0

                result["comparison"] = {
                    "revenue_change_percent": round(revenue_change, 2),
                    "orders_change_percent": round(orders_change, 2),
                    "revenue_trend": "up" if revenue_change > 0 else ("down" if revenue_change < 0 else "flat"),
                    "orders_trend": "up" if orders_change > 0 else ("down" if orders_change < 0 else "flat"),
                }

        return json.dumps(result, indent=2)

    def get_average_order_value(
        self,
        group_by: str = "day",
        created_after: Optional[str] = None,
        created_before: Optional[str] = None,
    ) -> str:
        """Get average order value over time.

        Args:
            group_by: How to group data - 'day', 'week', or 'month' (default 'day').
            created_after: Only include orders created after this date (YYYY-MM-DD format, optional).
            created_before: Only include orders created before this date (YYYY-MM-DD format, optional).

        Returns:
            JSON string containing average order value trends.
        """
        log_debug(
            f"Calculating AOV: group_by={group_by}, created_after={created_after}, created_before={created_before}"
        )

        query_parts = ["financial_status:paid"]
        if created_after:
            query_parts.append(f"created_at:>={created_after}")
        if created_before:
            query_parts.append(f"created_at:<={created_before}")
        query_filter = " AND ".join(query_parts)

        query = f"""
        query {{
            orders(first: 250, query: "{query_filter}", sortKey: CREATED_AT) {{
                edges {{
                    node {{
                        createdAt
                        totalPriceSet {{
                            shopMoney {{
                                amount
                                currencyCode
                            }}
                        }}
                    }}
                }}
            }}
        }}
        """

        result = self._make_graphql_request(query)

        if "error" in result:
            return json.dumps(result, indent=2)

        orders = result.get("orders", {}).get("edges", [])

        if not orders:
            return json.dumps({"message": "No orders found in the specified period"}, indent=2)

        # Group orders
        grouped: Dict[str, List[float]] = {}
        currency = None

        for order_edge in orders:
            order = order_edge["node"]
            created_at = order["createdAt"][:10]
            amount = float(order.get("totalPriceSet", {}).get("shopMoney", {}).get("amount", 0))
            currency = order.get("totalPriceSet", {}).get("shopMoney", {}).get("currencyCode")

            if group_by == "week":
                # Get ISO week
                date_obj = datetime.strptime(created_at, "%Y-%m-%d")
                key = f"{date_obj.isocalendar()[0]}-W{date_obj.isocalendar()[1]:02d}"
            elif group_by == "month":
                key = created_at[:7]  # YYYY-MM
            else:
                key = created_at

            if key not in grouped:
                grouped[key] = []
            grouped[key].append(amount)

        # Calculate averages
        aov_data = [
            {
                "period": key,
                "order_count": len(values),
                "total_revenue": round(sum(values), 2),
                "average_order_value": round(sum(values) / len(values), 2),
            }
            for key, values in sorted(grouped.items())
        ]

        overall_avg = sum(o["total_revenue"] for o in aov_data) / sum(o["order_count"] for o in aov_data)  # type: ignore

        response = {
            "period": {
                "created_after": created_after,
                "created_before": created_before,
            },
            "group_by": group_by,
            "overall_average_order_value": round(overall_avg, 2),
            "currency": currency,
            "breakdown": aov_data,
        }

        return json.dumps(response, indent=2)

    def get_repeat_customers(
        self,
        min_orders: int = 2,
        limit: int = 50,
        created_after: Optional[str] = None,
        created_before: Optional[str] = None,
    ) -> str:
        """Find customers who have made multiple purchases.

        Args:
            min_orders: Minimum number of orders to qualify as repeat customer (default 2).
            limit: Maximum number of customers to return (default 50).
            created_after: Only include orders created after this date (YYYY-MM-DD format, optional).
            created_before: Only include orders created before this date (YYYY-MM-DD format, optional).

        Returns:
            JSON string containing repeat customers with their order counts and total spend.
        """
        log_debug(
            f"Finding repeat customers: min_orders={min_orders}, created_after={created_after}, created_before={created_before}"
        )

        query_parts = ["financial_status:paid"]
        if created_after:
            query_parts.append(f"created_at:>={created_after}")
        if created_before:
            query_parts.append(f"created_at:<={created_before}")
        query_filter = " AND ".join(query_parts)

        query = f"""
        query {{
            orders(first: 250, query: "{query_filter}") {{
                edges {{
                    node {{
                        customer {{
                            id
                            email
                            firstName
                            lastName
                            numberOfOrders
                            amountSpent {{
                                amount
                                currencyCode
                            }}
                        }}
                        totalPriceSet {{
                            shopMoney {{
                                amount
                            }}
                        }}
                    }}
                }}
            }}
        }}
        """

        result = self._make_graphql_request(query)

        if "error" in result:
            return json.dumps(result, indent=2)

        # Aggregate by customer
        customer_data: Dict[str, Dict[str, Any]] = {}

        for order_edge in result.get("orders", {}).get("edges", []):
            customer = order_edge["node"].get("customer")
            if not customer or not customer.get("id"):
                continue

            customer_id = customer["id"]
            order_amount = float(order_edge["node"].get("totalPriceSet", {}).get("shopMoney", {}).get("amount", 0))

            if customer_id not in customer_data:
                customer_data[customer_id] = {
                    "id": customer_id,
                    "email": customer.get("email"),
                    "name": f"{customer.get('firstName', '')} {customer.get('lastName', '')}".strip(),
                    "total_orders_all_time": customer.get("numberOfOrders"),
                    "total_spent_all_time": customer.get("amountSpent", {}).get("amount"),
                    "currency": customer.get("amountSpent", {}).get("currencyCode"),
                    "orders_in_period": 0,
                    "spent_in_period": 0.0,
                }

            customer_data[customer_id]["orders_in_period"] += 1
            customer_data[customer_id]["spent_in_period"] += order_amount

        # Filter repeat customers and sort
        repeat_customers = [
            {**c, "spent_in_period": round(c["spent_in_period"], 2)}
            for c in customer_data.values()
            if c["orders_in_period"] >= min_orders
        ]

        repeat_customers.sort(key=lambda x: x["orders_in_period"], reverse=True)

        response = {
            "period": {
                "created_after": created_after,
                "created_before": created_before,
            },
            "min_orders_threshold": min_orders,
            "repeat_customer_count": len(repeat_customers),
            "customers": repeat_customers[:limit],
        }

        return json.dumps(response, indent=2)
