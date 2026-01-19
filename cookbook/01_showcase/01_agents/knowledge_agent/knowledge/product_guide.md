# Product Guide

## Overview

Acme Platform is our flagship product that helps businesses manage their operations efficiently. This guide covers the main features and how they work.

## Core Features

### Dashboard

The Dashboard is the central hub for monitoring your business:

- **Real-time Metrics**: View orders, revenue, and customer activity
- **Customizable Widgets**: Arrange cards to show what matters most
- **Time Range Filters**: View data for any date range
- **Export Reports**: Download data as CSV or PDF

To access: Login and you'll land on the Dashboard by default.

### User Management

Manage team members and their access:

#### Roles

| Role | Permissions |
|------|-------------|
| Admin | Full access to all features |
| Manager | Team management, reports |
| User | Basic operations |
| Viewer | Read-only access |

#### Adding Users

1. Go to Settings > Users
2. Click "Invite User"
3. Enter email address
4. Select role
5. User receives invitation email

#### Removing Users

1. Go to Settings > Users
2. Find the user
3. Click the three-dot menu
4. Select "Remove User"
5. Confirm removal

Note: Removing a user does not delete their historical data.

### Orders

The Orders module handles the complete order lifecycle:

#### Order States

```
Created -> Confirmed -> Processing -> Shipped -> Delivered
                     |
                     +-> Cancelled (from any state before Shipped)
```

#### Creating Orders

1. Go to Orders > New Order
2. Select customer or create new
3. Add products to order
4. Apply discounts if applicable
5. Choose shipping method
6. Confirm order

#### Order Search

Search orders by:
- Order ID
- Customer name or email
- Product name
- Date range
- Status

#### Bulk Actions

Select multiple orders to:
- Update status
- Export to CSV
- Print packing slips
- Assign to team member

### Products

Manage your product catalog:

#### Product Information

Each product includes:
- Name and description
- SKU (Stock Keeping Unit)
- Price and cost
- Inventory quantity
- Images (up to 10)
- Categories and tags
- Variants (size, color, etc.)

#### Inventory Management

- Set low-stock alerts
- Track inventory across locations
- View inventory history
- Sync with suppliers (Enterprise plan)

#### Product Categories

Organize products with:
- Hierarchical categories
- Tags for cross-category grouping
- Collection-based merchandising

### Customers

Build customer relationships:

#### Customer Profiles

View for each customer:
- Contact information
- Order history
- Total spend
- Notes and tags
- Communication history

#### Customer Segments

Create segments based on:
- Purchase behavior
- Geographic location
- Customer lifetime value
- Last order date

### Reports

Generate insights from your data:

#### Standard Reports

- Sales by period
- Top products
- Customer acquisition
- Inventory levels
- Team performance

#### Custom Reports

Build reports with:
- Drag-and-drop fields
- Custom filters
- Scheduled delivery
- Multiple export formats

### Integrations

Connect with other tools:

#### Available Integrations

| Category | Tools |
|----------|-------|
| Payments | Stripe, PayPal, Square |
| Shipping | FedEx, UPS, USPS |
| Accounting | QuickBooks, Xero |
| Marketing | Mailchimp, HubSpot |
| Support | Zendesk, Intercom |

#### Setting Up Integrations

1. Go to Settings > Integrations
2. Find the integration
3. Click "Connect"
4. Authorize access
5. Configure sync settings

## API Access

Access our REST API for custom integrations:

### Authentication

Use API keys for authentication:
```
Authorization: Bearer <your-api-key>
```

Generate keys at Settings > API Keys.

### Rate Limits

| Plan | Requests/minute |
|------|-----------------|
| Starter | 60 |
| Professional | 300 |
| Enterprise | 1000 |

### Endpoints

Base URL: `https://api.acmeplatform.example.com/v1`

| Endpoint | Methods | Description |
|----------|---------|-------------|
| /orders | GET, POST | Order management |
| /products | GET, POST, PUT, DELETE | Product catalog |
| /customers | GET, POST, PUT | Customer data |
| /reports | GET | Report generation |

### Webhooks

Receive real-time notifications:
- order.created
- order.updated
- order.shipped
- customer.created
- inventory.low

Configure webhooks at Settings > Webhooks.

## Plans and Pricing

### Starter Plan - $29/month
- Up to 100 orders/month
- 2 team members
- Basic reports
- Email support

### Professional Plan - $99/month
- Up to 1,000 orders/month
- 10 team members
- Advanced reports
- Phone support
- API access

### Enterprise Plan - Custom
- Unlimited orders
- Unlimited team members
- Custom reports
- Dedicated support
- Custom integrations
- SLA guarantee

## Support

### Self-Service Resources
- Help Center: https://help.acmeplatform.example.com
- Video Tutorials: https://learn.acmeplatform.example.com
- API Documentation: https://api.acmeplatform.example.com/docs

### Contact Support
- Email: support@acmeplatform.example.com
- Phone: 1-800-ACME-HELP (Professional and Enterprise)
- Chat: Available in-app (Professional and Enterprise)

### Support Hours
- Email: 24/7 response within 24 hours
- Phone: Monday-Friday, 9 AM - 6 PM EST
- Chat: Monday-Friday, 9 AM - 6 PM EST

## Frequently Asked Questions

### How do I reset my password?
Click "Forgot Password" on the login page and follow the email instructions.

### Can I import data from another system?
Yes, we support CSV imports for orders, products, and customers. Go to Settings > Import.

### How do I cancel my subscription?
Contact support or go to Settings > Billing > Cancel Subscription. Note: Annual plans cannot be refunded.

### Is my data secure?
Yes, we use industry-standard encryption (AES-256) and are SOC 2 Type II certified.

### Can I export my data?
Yes, go to Settings > Export to download all your data at any time.
