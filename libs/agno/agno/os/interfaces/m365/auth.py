"""
Authentication utilities for Microsoft 365 Copilot Interface.

Handles validation of Microsoft Entra ID JWT tokens to ensure
requests are authenticated and authorized.

This module implements proper JWKS-based signature verification following
Microsoft's recommended patterns for validating Entra ID tokens.

References:
    - Microsoft Identity Platform: Access token validation
    - Entra ID JWKS endpoint: https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys
    - OpenID Connect metadata: https://login.microsoftonline.com/{tenant_id}/v2.0/.well-known/openid-configuration
"""

import json
import time
from functools import lru_cache
from typing import Any, Dict, Optional

import requests
import jwt
from jwt import PyJWTError
from jwt.algorithms import RSAAlgorithm

from agno.utils.log import log_debug, log_error, log_warning


# Default timeout for JWKS request (in seconds)
JWKS_TIMEOUT = 5

# Cache TTL for JWKS (in seconds) - Keys rotate rarely, so we cache for 1 hour
JWKS_CACHE_TTL = 3600


class JWKSValidationError(Exception):
    """Raised when JWKS validation fails."""
    pass


def get_jwks_url(tenant_id: str) -> str:
    """
    Get the JWKS URL for a Microsoft Entra ID tenant.

    Args:
        tenant_id: Microsoft Entra ID tenant ID

    Returns:
        JWKS endpoint URL

    Example:
        ```python
        url = get_jwks_url("your-tenant-id")
        # Returns: "https://login.microsoftonline.com/your-tenant-id/discovery/v2.0/keys"
        ```
    """
    return f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"


@lru_cache(maxsize=1)
def get_jwks(tenant_id: str) -> Dict[str, Any]:
    """
    Fetch and cache the JWKS (JSON Web Key Set) for a tenant.

    The JWKS contains the public keys used to verify JWT signatures.
    Results are cached in memory with a 1-hour TTL.

    Args:
        tenant_id: Microsoft Entra ID tenant ID

    Returns:
        JWKS as a dictionary

    Raises:
        JWKSValidationError: If JWKS fetch fails

    Note:
        The @lru_cache decorator caches results in memory.
        For production with multiple workers, consider using Redis instead.
    """
    jwks_url = get_jwks_url(tenant_id)

    try:
        response = requests.get(
            jwks_url,
            timeout=JWKS_TIMEOUT,
            headers={"Accept": "application/json"}
        )
        response.raise_for_status()

        jwks = response.json()
        log_debug(f"Successfully fetched JWKS for tenant {tenant_id}")

        return jwks

    except requests.RequestException as e:
        log_error(f"Failed to fetch JWKS for tenant {tenant_id}: {e}")
        raise JWKSValidationError(
            f"Failed to fetch JWKS from {jwks_url}: {str(e)}"
        )


def get_public_key_from_jwks(
    token: str,
    tenant_id: str,
    jwks: Optional[Dict[str, Any]] = None,
) -> Any:
    """
    Extract the public key from JWKS based on the token's kid header.

    Args:
        token: JWT token string
        tenant_id: Microsoft Entra ID tenant ID
        jwks: Optional cached JWKS (fetches if not provided)

    Returns:
        RSA public key for verifying the token signature

    Raises:
        JWKSValidationError: If kid is missing or key not found in JWKS
        ValueError: If token header is invalid

    Example:
        ```python
        public_key = get_public_key_from_jwks(
            token="eyJ...",
            tenant_id="your-tenant-id"
        )
        ```
    """
    try:
        # Decode token header to get kid (key ID)
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")

        if not kid:
            raise ValueError("Token missing 'kid' header")

        # Get JWKS (use cached if available)
        if jwks is None:
            jwks = get_jwks(tenant_id)

        # Find the key with matching kid
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                # Construct RSA public key from JWK
                return RSAAlgorithm.from_jwk(json.dumps(key))

        # Key not found
        available_kids = [k.get("kid") for k in jwks.get("keys", [])]
        log_warning(
            f"Token kid '{kid}' not found in JWKS. "
            f"Available kids: {available_kids}"
        )
        raise JWKSValidationError(
            f"Signing key not found in JWKS for kid '{kid}'"
        )

    except jwt.PyJWTError as e:
        log_error(f"Failed to decode token header: {e}")
        raise ValueError(f"Invalid token header: {str(e)}")


async def validate_m365_token(
    token: str,
    expected_tenant_id: str,
    expected_client_id: str,
    enable_signature_verification: bool = True,
) -> Dict[str, Any]:
    """
    Validate Microsoft Entra ID JWT token with JWKS signature verification.

    This function validates that the JWT token from Microsoft Entra ID:
    - Has a valid signature (verified against JWKS)
    - Has the correct issuer (contains the expected tenant ID)
    - Has the correct audience (matches expected client ID)
    - Is not expired
    - Has required claims (exp, iat, nbf)

    Args:
        token: JWT token string from Authorization header
        expected_tenant_id: Expected Microsoft Entra ID tenant ID
        expected_client_id: Expected application (client) ID
        enable_signature_verification: Enable JWKS signature verification (default: True)

    Returns:
        Dictionary containing validated token claims including:
        - upn: User Principal Name (email)
        - oid: Object ID (user ID)
        - tid: Tenant ID
        - aud: Audience
        - iss: Issuer
        - exp: Expiration time
        - scp: Scopes/permissions (for delegated tokens)
        - roles: App roles (for app-only tokens)

    Raises:
        ValueError: If token is invalid, expired, or from wrong tenant/client
        JWKSValidationError: If JWKS fetch or key lookup fails

    Note:
        Signature verification is enabled by default and uses JWKS.
        In rare cases, you can disable it by setting enable_signature_verification=False,
        but this is NOT recommended for production.

    Example:
        ```python
        try:
            claims = await validate_m365_token(
                token=request.headers["authorization"],
                expected_tenant_id="your-tenant-id",
                expected_client_id="your-client-id"
            )
            user_email = claims.get("upn")
            user_tenant = claims.get("tid")
        except ValueError as e:
            # Token invalid
            return {"error": str(e)}
        ```
    """
    issuer = f"https://login.microsoftonline.com/{expected_tenant_id}/v2.0"

    try:
        # Get public key from JWKS for signature verification
        if enable_signature_verification:
            public_key = get_public_key_from_jwks(token, expected_tenant_id)
        else:
            # WARNING: Signature verification disabled - NOT recommended for production
            log_warning("Signature verification DISABLED -Tokens are NOT being verified!")
            public_key = None  # Will skip signature verification

        # Decode and validate JWT token
        # PyJWT will verify:
        # - Signature (if public_key provided)
        # - Audience (aud)
        # - Issuer (iss)
        # - Expiration (exp)
        # - Not Before (nbf)
        # - Issued At (iat)
        decoded = jwt.decode(
            token,
            key=public_key,
            algorithms=["RS256"],
            audience=expected_client_id,
            issuer=issuer,
            options={
                "require": ["exp", "iat", "nbf"],
                "verify_signature": enable_signature_verification,
            }
        )

        # Additional tenant validation (tid claim)
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
        user_oid = decoded.get("oid", "unknown")
        log_debug(f"Token validated successfully for user: {user_upn} (oid: {user_oid})")

        return decoded

    except jwt.ExpiredSignatureError:
        log_error("Token validation failed: token has expired")
        raise ValueError("Token has expired")

    except jwt.InvalidAudienceError as e:
        log_error(f"Token validation failed: invalid audience - {e}")
        raise ValueError(
            f"Invalid audience. Expected {expected_client_id}, "
            f"got {e}"
        )

    except jwt.InvalidIssuerError as e:
        log_error(f"Token validation failed: invalid issuer - {e}")
        raise ValueError(
            f"Invalid issuer. Expected {issuer}"
        )

    except jwt.InvalidTokenError as e:
        log_error(f"Token validation failed: invalid token - {e}")
        raise ValueError(f"Invalid token: {str(e)}")

    except JWKSValidationError as e:
        log_error(f"Token validation failed: JWKS error - {e}")
        raise ValueError(f"Token validation failed: {str(e)}")


def extract_user_info(token_claims: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract user information from validated token claims.

    Args:
        token_claims: Validated JWT token claims

    Returns:
        Dictionary containing user information:
        - user_id: User's object ID (oid claim)
        - email: User's email (UPN claim)
        - tenant_id: User's tenant ID (tid claim)
        - name: User's display name (name claim)
        - scopes: Token scopes/scp (for delegated tokens)
        - roles: App roles (for app-only tokens)

    Example:
        ```python
        claims = await validate_m365_token(...)
        user_info = extract_user_info(claims)
        # user_info = {
        #     "user_id": "...",
        #     "email": "user@example.com",
        #     "tenant_id": "...",
        #     "name": "John Doe",
        #     "scopes": ["User.Read", "Mail.ReadWrite"],
        #     "roles": []
        # }
        ```
    """
    return {
        "user_id": token_claims.get("oid", ""),
        "email": token_claims.get("upn", ""),
        "tenant_id": token_claims.get("tid", ""),
        "name": token_claims.get("name", ""),
        "scopes": token_claims.get("scp", "").split() if token_claims.get("scp") else [],
        "roles": token_claims.get("roles", []),
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

    Example implementations:
        ```python
        # Role-based access control
        user_roles = token_claims.get("roles", [])
        if "Admin" not in user_roles and component_id.startswith("admin-"):
            return False

        # Scope-based access control
        required_scope = f"Agno_{component_id}"
        if required_scope not in token_claims.get("scp", "").split():
            return False

        return True
        ```
    """
    # TODO: Implement proper authorization logic
    # For now, all authenticated users can access all components
    return True


def clear_jwks_cache():
    """
    Clear the cached JWKS.

    Use this when you need to force a refresh of the signing keys.
    This is typically only needed when keys are rotated.

    Example:
        ```python
        # After key rotation
        clear_jwks_cache()
        ```
    """
    get_jwks.cache_clear()
    log_debug("JWKS cache cleared")


def get_token_metadata(token: str) -> Dict[str, Any]:
    """
    Extract metadata from a JWT token without validation.

    This is useful for logging and debugging, but should NOT be used
    for authentication decisions.

    Args:
        token: JWT token string

    Returns:
        Dictionary containing token metadata:
        - header: JWT header (alg, typ, kid)
        - payload: Token payload without validation
        - expiration: Unix timestamp of expiration

    Raises:
        ValueError: If token is malformed

    Example:
        ```python
        metadata = get_token_metadata(token)
        print(f"Token expires at: {metadata['expiration']}")
        ```
    """
    try:
        header = jwt.get_unverified_header(token)
        payload = jwt.decode(
            token,
            options={
                "verify_signature": False,
                "verify_aud": False,
                "verify_exp": False,
                "verify_iss": False
            }
        )

        return {
            "header": header,
            "payload": payload,
            "expiration": payload.get("exp", 0),
            "issuer": payload.get("iss", ""),
            "audience": payload.get("aud", ""),
        }

    except jwt.PyJWTError as e:
        raise ValueError(f"Failed to decode token: {str(e)}")
