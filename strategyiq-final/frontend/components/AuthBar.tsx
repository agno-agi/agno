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
      <Link href="/login" className="text-sm text-terminal-accent hover:underline">
        Sign In
      </Link>
    );
  }

  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="text-terminal-muted">Tier:</span>
      <span className="uppercase text-xs border border-terminal-accent text-terminal-accent px-2 py-0.5 rounded">
        {tier}
      </span>
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
