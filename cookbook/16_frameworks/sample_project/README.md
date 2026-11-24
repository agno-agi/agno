# Shipping review fixture

This directory is input for the coding harness, not an application to install.
Read `shipping.py` and `orders.json`. Shipping costs eight dollars for `small`
and zero for both `boundary` and `large`. The boundary order makes the inclusive
free-shipping threshold visible.

The first exercises inspect these files without editing them. No database,
network service or third-party Python dependency is needed by this fixture.
Harness authentication and model calls are still required.
