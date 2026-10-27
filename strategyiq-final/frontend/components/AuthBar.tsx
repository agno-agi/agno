"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { clearSession, getSession } from "@/lib/auth";

export function AuthBar() {
  const [tier, setTier] = useState<string | null>(null);

  useEffect(() => {
    setTier(getSession()?.tier ?? null);
  }, []);

  if (!tier) {
    return (
      <div className="flex items-center gap-3 text-sm">
        <Link href="/billing" className="text-terminal-muted hover:text-terminal-text">
          Pricing
        </Link>
        <Link href="/login" className="text-sm text-terminal-accent hover:underline">
          Sign In
        </Link>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="text-terminal-muted">Tier:</span>
      <span className="uppercase text-xs border border-terminal-accent text-terminal-accent px-2 py-0.5 rounded">
        {tier}
      </span>
      {tier === "beginner" && (
        <Link href="/billing?tier=pro" className="text-terminal-accent hover:underline text-xs">
          Upgrade
        </Link>
      )}
      {tier === "pro" && (
        <Link href="/billing?tier=elite" className="text-terminal-accent hover:underline text-xs">
          Go Elite
        </Link>
      )}
      {(tier === "elite" || tier === "pro") && (
        <Link href="/billing" className="text-terminal-muted hover:text-terminal-text text-xs">
          Billing
        </Link>
      )}
      <button
        onClick={async () => {
          await clearSession();
          setTier(null);
        }}
        className="text-terminal-muted hover:text-terminal-text text-xs"
      >
        Logout
      </button>
    </div>
  );
}
