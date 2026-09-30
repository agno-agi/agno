"""Stripe checkout + webhook auto-upgrade."""

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import settings
from constants import SEC_DISCLAIMER, UserTier
from db.auth import get_current_user
from db.models import Subscription, User
from db.session import get_db

stripe.api_key = settings.stripe_secret_key
router = APIRouter(prefix="/billing", tags=["Billing"])

PRICE_MAP = {
    UserTier.PRO: settings.stripe_price_pro,
    UserTier.ELITE: settings.stripe_price_elite,
}


class CheckoutRequest(BaseModel):
    tier: UserTier


def _apply_tier(user: User, sub: Subscription, tier: str, *, subscription_id: str | None = None, active: bool = True) -> None:
    if subscription_id:
        sub.stripe_subscription_id = subscription_id
    sub.active = active
    sub.tier = tier
    user.tier = tier


@router.post("/checkout")
def create_checkout(
    request: CheckoutRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if request.tier == UserTier.BEGINNER:
        raise HTTPException(status_code=400, detail="Beginner tier is free")

    price_id = PRICE_MAP.get(request.tier)
    if not price_id:
        raise HTTPException(status_code=500, detail="Stripe price not configured")

    if not user.stripe_customer_id:
        customer = stripe.Customer.create(email=user.email)
        user.stripe_customer_id = customer.id
        db.commit()

    metadata = {"user_id": str(user.id), "tier": request.tier.value}
    session = stripe.checkout.Session.create(
        customer=user.stripe_customer_id,
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url="https://strategyiq.io/billing/success",
        cancel_url="https://strategyiq.io/billing/cancel",
        metadata=metadata,
        # Copy tier onto the Subscription object so customer.subscription.updated
        # does not fall back to "pro" and downgrade Elite users.
        subscription_data={"metadata": metadata},
    )
    return {"checkout_url": session.url, "disclaimer": SEC_DISCLAIMER}


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig, settings.stripe_webhook_secret)
    except (ValueError, stripe.error.SignatureVerificationError) as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook") from exc

    if event["type"] == "checkout.session.completed":
        data = event["data"]["object"]
        customer_id = data.get("customer")
        user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
        if not user:
            return {"status": "ignored"}

        sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()
        if not sub:
            sub = Subscription(user_id=user.id)
            db.add(sub)

        tier = data.get("metadata", {}).get("tier", "pro")
        subscription_id = data.get("subscription")
        if isinstance(subscription_id, dict):
            subscription_id = subscription_id.get("id")
        _apply_tier(user, sub, tier, subscription_id=subscription_id, active=True)
        db.commit()

    elif event["type"] == "customer.subscription.updated":
        data = event["data"]["object"]
        customer_id = data.get("customer")
        user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
        if not user:
            return {"status": "ignored"}

        sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()
        if not sub:
            sub = Subscription(user_id=user.id)
            db.add(sub)

        # Prefer subscription metadata (set via subscription_data at checkout).
        tier = data.get("metadata", {}).get("tier") or sub.tier or "pro"
        _apply_tier(
            user,
            sub,
            tier,
            subscription_id=data.get("id"),
            active=data.get("status") == "active",
        )
        db.commit()

    elif event["type"] == "customer.subscription.deleted":
        sub_id = event["data"]["object"]["id"]
        sub = db.query(Subscription).filter(Subscription.stripe_subscription_id == sub_id).first()
        if sub:
            sub.active = False
            sub.tier = "beginner"
            user = db.query(User).filter(User.id == sub.user_id).first()
            if user:
                user.tier = "beginner"
            db.commit()

    return {"status": "ok"}


@router.get("/status")
def subscription_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    return {
        "tier": sub.tier if sub and sub.active else "beginner",
        "active": sub.active if sub else False,
        "disclaimer": SEC_DISCLAIMER,
    }
