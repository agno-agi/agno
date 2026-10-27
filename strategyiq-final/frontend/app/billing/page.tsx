"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useEffect, useState } from "react";
import { getSession } from "@/lib/auth";
import { fetchSubscriptionStatus, startCheckout, type PaidTier } from "@/lib/billing";
import { SEC_DISCLAIMER, TIERS, tierRank } from "@/lib/constants";

function BillingContent() {
  const searchParams = useSearchParams();
  const preferred = (searchParams.get("tier") || "").toLowerCase();
  const [currentTier, setCurrentTier] = useState<string>("beginner");
  const [loadingTier, setLoadingTier] = useState<PaidTier | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [signedIn, setSignedIn] = useState(false);

  useEffect(() => {
    const session = getSession();
    setSignedIn(Boolean(session?.token));
    setCurrentTier(session?.tier || "beginner");
    if (!session?.token) return;

    fetchSubscriptionStatus()
      .then((status) => setCurrentTier(status.tier))
      .catch(() => {
        // Fall back to session tier when status endpoint is unreachable.
      });
  }, []);

  const upgrade = async (tier: PaidTier) => {
    setError(null);
    setLoadingTier(tier);
    try {
      const { checkout_url } = await startCheckout(tier);
      window.location.href = checkout_url;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Checkout failed");
      setLoadingTier(null);
    }
  };

  const onSubmit = (event: FormEvent, tier: PaidTier) => {
    event.preventDefault();
    void upgrade(tier);
  };

  return (
    <div className="min-h-screen p-6 max-w-5xl mx-auto space-y-6">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-terminal-accent">Billing</h1>
          <p className="text-sm text-terminal-muted mt-1">
            Upgrade via Stripe Checkout. Current tier:{" "}
            <span className="uppercase text-terminal-accent">{currentTier}</span>
          </p>
        </div>
        <Link href="/" className="text-sm text-terminal-muted hover:text-terminal-text">
          Back to terminal
        </Link>
      </header>

      {!signedIn && (
        <div className="panel text-sm">
          <p className="text-terminal-muted">
            Sign in to start checkout.{" "}
            <Link href="/login" className="text-terminal-accent hover:underline">
              Go to login
            </Link>
          </p>
        </div>
      )}

      {error && <p className="text-terminal-red text-sm">{error}</p>}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {TIERS.map((tier) => {
          const isCurrent = tier.name === currentTier;
          const isPaid = tier.name === "pro" || tier.name === "elite";
          const highlighted = preferred === tier.name || (preferred !== "elite" && tier.name === "pro");
          const canUpgrade = isPaid && signedIn && tierRank(tier.name) > tierRank(currentTier);

          return (
            <div
              key={tier.name}
              className={`panel ${highlighted || isCurrent ? "border-terminal-accent" : ""}`}
            >
              <h3 className="text-lg font-semibold text-terminal-accent">{tier.label}</h3>
              <p className="text-3xl font-bold my-3">
                {tier.price === 0 ? "Free" : `$${tier.price}`}
                {tier.price > 0 && <span className="text-sm text-terminal-muted">/mo</span>}
              </p>
              <ul className="text-sm text-terminal-muted space-y-1 mb-4">
                {tier.features.map((feature) => (
                  <li key={feature}>- {feature}</li>
                ))}
              </ul>

              {isCurrent ? (
                <span className="text-xs text-terminal-accent uppercase">Current plan</span>
              ) : canUpgrade ? (
                <form onSubmit={(event) => onSubmit(event, tier.name as PaidTier)}>
                  <button
                    type="submit"
                    disabled={loadingTier !== null}
                    className="w-full bg-terminal-accent text-terminal-bg py-2 rounded text-sm font-semibold disabled:opacity-60"
                  >
                    {loadingTier === tier.name ? "Redirecting..." : `Upgrade to ${tier.label}`}
                  </button>
                </form>
              ) : !signedIn && isPaid ? (
                <Link
                  href="/login"
                  className="block text-center w-full border border-terminal-accent text-terminal-accent py-2 rounded text-sm"
                >
                  Sign in to upgrade
                </Link>
              ) : (
                <span className="text-xs text-terminal-muted">Included or unavailable</span>
              )}
            </div>
          );
        })}
      </div>

      <p className="text-xs text-terminal-muted">{SEC_DISCLAIMER}</p>
    </div>
  );
}

export default function BillingPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen p-6 text-sm text-terminal-muted">Loading billing...</div>
      }
    >
      <BillingContent />
    </Suspense>
  );
}
