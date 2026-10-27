"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getSession, saveSession } from "@/lib/auth";
import { fetchSubscriptionStatus } from "@/lib/billing";
import { SEC_DISCLAIMER } from "@/lib/constants";

export default function BillingSuccessPage() {
  const [tier, setTier] = useState<string>("…");
  const [message, setMessage] = useState("Confirming your subscription…");

  useEffect(() => {
    const session = getSession();
    if (!session?.token) {
      setMessage("Signed out — log in to see your updated tier.");
      setTier("unknown");
      return;
    }

    let cancelled = false;
    const refresh = async () => {
      try {
        const status = await fetchSubscriptionStatus();
        if (cancelled) return;
        setTier(status.tier);
        await saveSession(session.token, status.tier);
        setMessage(
          status.active
            ? "Stripe checkout completed. Your tier is active."
            : "Payment received. Tier activation can take a few seconds after the webhook."
        );
      } catch {
        if (cancelled) return;
        setTier(session.tier);
        setMessage("Checkout completed. Refresh the terminal if your tier has not updated yet.");
      }
    };
    void refresh();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="panel w-full max-w-md space-y-4 text-center">
        <h1 className="text-terminal-accent text-xl font-bold">Upgrade successful</h1>
        <p className="text-sm text-terminal-muted">{message}</p>
        <p className="text-sm">
          Tier: <span className="uppercase text-terminal-accent">{tier}</span>
        </p>
        <div className="flex gap-3 justify-center text-sm">
          <Link href="/" className="bg-terminal-accent text-terminal-bg px-4 py-2 rounded font-semibold">
            Open terminal
          </Link>
          <Link href="/billing" className="border border-terminal-border px-4 py-2 rounded text-terminal-muted">
            Billing
          </Link>
        </div>
        <p className="text-xs text-terminal-muted">{SEC_DISCLAIMER}</p>
      </div>
    </div>
  );
}
