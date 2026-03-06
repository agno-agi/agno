"""
Authentication utilities for Microsoft 365 Copilot Interface.

Handles validation of Microsoft Entra ID JWT tokens to ensure
requests are authenticated and authorized.
"""

import jwt
from typing import Any, Dict

from agno.utils.log import log_debug, log_error, log_warning


# JWT token validation configuration
# In production, use proper JWKS endpoint verification
# TODO: Implement JWKS-based signature verification
ENABLE_SIGNATURE_VERIFICATION = False


async def validate_m365_token(
    token: str,
    expected_tenant_id: str,
    expected_client_id: str,
) -> Dict[str, Any]:
    """
    Validate Microsoft Entra ID JWT token.

    This function validates that the JWT token from Microsoft Entra ID:
    - Has the correct issuer (contains the expected tenant ID)
    - Has the correct audience (matches expected client ID)
    - Is not expired
    - Has a valid structure

    Args:
        token: JWT token string from Authorization header
        expected_tenant_id: Expected Microsoft Entra ID tenant ID
        expected_client_id: Expected application (client) ID

    Returns:
        Dictionary containing validated token claims including:
        - upn: User Principal Name (email)
        - oid: Object ID (user ID)
        - tid: Tenant ID
        - aud: Audience
        - iss: Issuer
        - exp: Expiration time

    Raises:
        ValueError: If token is invalid, expired, or from wrong tenant/client

    Note:
        In production, ENABLE_SIGNATURE_VERIFICATION should be True
        and JWKS endpoint should be used for proper signature validation.

    Example:
        ```python
        try:
            claims = await validate_m365_token(
                token=request.headers["authorization"],
                expected_tenant_id="your-tenant-id",
                expected_client_id="your-client-id"
            )
            user_email = claims.get("upn")
        except ValueError as e:
            # Token invalid
            return {"error": str(e)}
        ```
    """
    try:
        # Decode JWT token
        # In production, use JWKS endpoint for proper signature verification
        decoded = jwt.decode(
            token,
            options={
                "verify_signature": ENABLE_SIGNATURE_VERIFICATION,
                "verify_aud": True,
                "verify_iss": True,
                "verify_exp": True,
            },
            audience=expected_client_id,
        )

        # Validate issuer contains tenant ID
        # Microsoft Entra ID issuer format: https://login.microsoftonline.com/{tenant_id}/v2.0
        issuer = decoded.get("iss", "")
        if expected_tenant_id not in issuer:
            log_warning(
                f"Token validation failed: tenant mismatch. "
                f"Expected '{expected_tenant_id}', got '{issuer}'"
            )
            raise ValueError(
                f"Invalid tenant. Expected {expected_tenant_id}, got {issuer}"
            )

        # Validate tenant ID in claims
        token_tenant_id = decoded.get("tid", "")
        if token_tenant_id != expected_tenant_id:
            log_warning(
                f"Token validation failed: tid claim mismatch. "
                f"Expected '{expected_tenant_id}', got '{token_tenant_id}'"
            )
            raise ValueError(
                f"Invalid tenant ID. Expected {expected_tenant_id}, got {token_tenant_id}"
            )

        # Log successful validation
        user_upn = decoded.get("upn", "unknown")
        log_debug(f"Token validated successfully for user: {user_upn}")

        return decoded

    except jwt.ExpiredSignatureError:
        log_error("Token validation failed: token has expired")
        raise ValueError("Token has expired")

    except jwt.InvalidAudienceError as e:
        log_error(f"Token validation failed: invalid audience - {e}")
        raise ValueError(f"Invalid audience. Expected {expected_client_id}")

    except jwt.InvalidIssuerError as e:
        log_error(f"Token validation failed: invalid issuer - {e}")
        raise ValueError(f"Invalid issuer. Expected tenant {expected_tenant_id}")

    except jwt.InvalidTokenError as e:
        log_error(f"Token validation failed: invalid token - {e}")
        raise ValueError(f"Invalid token: {str(e)}")


def extract_user_info(token_claims: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract user information from validated token claims.

    Args:
        token_claims: Validated JWT token claims

    Returns:
        Dictionary containing user information:
        - user_id: User's object ID
        - email: User's email (UPN)
        - tenant_id: User's tenant ID
        - name: User's display name (if available)

    Example:
        ```python
        claims = await validate_m365_token(...)
        user_info = extract_user_info(claims)
        # user_info = {
        #     "user_id": "...",
        #     "email": "user@example.com",
        #     "tenant_id": "...",
        #     "name": "John Doe"
        # }
        ```
    """
    return {
        "user_id": token_claims.get("oid", ""),
        "email": token_claims.get("upn", ""),
        "tenant_id": token_claims.get("tid", ""),
        "name": token_claims.get("name", ""),
    }


def validate_token_for_component(
    token_claims: Dict[str, Any],
    component_id: str,
    allowed_components: Optional[List[str]] = None,
) -> bool:
    """
    Validate that the token has permission to access the component.

    This is a placeholder for future authorization logic.
    Currently, all authenticated users can access all components.

    Args:
        token_claims: Validated JWT token claims
        component_id: ID of the component being accessed
        allowed_components: Optional list of components the user can access

    Returns:
        True if access is allowed, False otherwise

    Note:
        This is a placeholder. Implement proper authorization based on
        your security requirements (e.g., role-based access control).
    """
    # TODO: Implement proper authorization logic
    # For now, all authenticated users can access all components
    return True
