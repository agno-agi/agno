"""JWTIssuer: minting tokens that JWTValidator accepts (the two are symmetric)."""


import jwt
import pytest

from agno.os.middleware.jwt import JWTIssuer, JWTValidator

SECRET = "issuer-secret-at-least-256-bits-long-padding-xxxxxxxxxxxx"
OS_ID = "issuer-os"


def test_hs256_roundtrip_issuer_to_validator():
    issuer = JWTIssuer(SECRET, audience=OS_ID)
    validator = JWTValidator(verification_keys=[SECRET], algorithm="HS256")

    token = issuer.create_token("bob", scopes=["agents:*:read"])
    claims = validator.validate_token(token, expected_audience=OS_ID)

    assert claims["sub"] == "bob"
    assert claims["scopes"] == ["agents:*:read"]
    assert claims["aud"] == OS_ID
    assert claims["exp"] > claims["iat"]  # always stamped
    assert "jti" in claims  # unique id for audit by default


def test_algorithm_inferred_from_key():
    assert JWTIssuer(SECRET).algorithm == "HS256"
    assert JWTIssuer("-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----").algorithm == "RS256"


def test_roles_and_extra_claims_and_overrides():
    issuer = JWTIssuer(SECRET, audience=OS_ID, issuer="https://my-app")
    token = issuer.create_token(
        "alice",
        roles=["admin"],
        audience="other-os",
        expires_in=60,
        extra_claims={"email": "alice@co", "tenant": "t1"},
        jti=False,
    )
    claims = jwt.decode(token, SECRET, algorithms=["HS256"], audience="other-os")
    assert claims["roles"] == ["admin"]
    assert claims["iss"] == "https://my-app"
    assert claims["aud"] == "other-os"  # per-token override
    assert claims["email"] == "alice@co" and claims["tenant"] == "t1"
    assert "jti" not in claims
    assert claims["exp"] - claims["iat"] == 60


def test_issued_token_requires_expiry_satisfied_by_default():
    # the validator requires exp by default; the issuer always sets it, so this passes
    issuer = JWTIssuer(SECRET, audience=OS_ID)
    validator = JWTValidator(verification_keys=[SECRET], algorithm="HS256")
    assert validator.validate_token(issuer.create_token("u"), expected_audience=OS_ID)["sub"] == "u"


def test_expired_token_is_rejected():
    issuer = JWTIssuer(SECRET, audience=OS_ID)
    validator = JWTValidator(verification_keys=[SECRET], algorithm="HS256", leeway=0)
    token = issuer.create_token("u", expires_in=-10)  # already expired
    with pytest.raises(jwt.ExpiredSignatureError):
        validator.validate_token(token, expected_audience=OS_ID)
