import { API_URL } from "./constants";
import { getSession } from "./auth";

export type PaidTier = "pro" | "elite";

export interface CheckoutResult {
  checkout_url: string;
  disclaimer?: string;
}

export interface SubscriptionStatus {
  tier: string;
  active: boolean;
  disclaimer?: string;
}

function formatDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) =>
        typeof item === "object" && item && "msg" in item ? String((item as { msg: unknown }).msg) : String(item)
      )
      .join("; ");
  }
  return "Billing request failed";
}

export async function startCheckout(tier: PaidTier): Promise<CheckoutResult> {
  const session = getSession();
  if (!session?.token) {
    throw new Error("Sign in required to upgrade");
  }

  const res = await fetch("/api/billing/checkout", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${session.token}`,
    },
    body: JSON.stringify({ tier }),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(formatDetail(data.detail || data.error) || "Checkout failed");
  }
  if (!data.checkout_url) {
    throw new Error("Stripe checkout URL missing — check STRIPE_* configuration");
  }
  return data as CheckoutResult;
}

export async function fetchSubscriptionStatus(): Promise<SubscriptionStatus> {
  const session = getSession();
  if (!session?.token) {
    return { tier: "beginner", active: false };
  }

  const res = await fetch(`${API_URL}/billing/status`, {
    headers: { Authorization: `Bearer ${session.token}` },
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(formatDetail(data.detail || data.error) || "Status failed");
  }
  return {
    tier: data.tier || session.tier || "beginner",
    active: Boolean(data.active),
    disclaimer: data.disclaimer,
  };
}
