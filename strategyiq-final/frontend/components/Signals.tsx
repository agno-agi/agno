"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getSession } from "@/lib/auth";
import { tierRank } from "@/lib/constants";

const SIGNALS = [
  { symbol: "NVDA", signal: "BUY", strength: 82, reason: "Momentum breakout above 200DMA" },
  { symbol: "TSLA", signal: "SELL", strength: 67, reason: "RSI overbought + volume divergence" },
  { symbol: "AAPL", signal: "HOLD", strength: 54, reason: "Range-bound, awaiting earnings" },
  { symbol: "BTC", signal: "BUY", strength: 71, reason: "ETF inflow trend + halving cycle" },
];

export function Signals() {
  const [tier, setTier] = useState<string>("beginner");

  useEffect(() => {
    setTier(getSession()?.tier || "beginner");
  }, []);

  if (tierRank(tier) < 1) {
    return (
      <div className="panel space-y-2">
        <h2 className="text-terminal-accent font-semibold">Pro Signals</h2>
        <p className="text-sm text-terminal-muted">
          Trading signals are available on Pro and Elite plans.
        </p>
        <Link
          href="/billing?tier=pro"
          className="inline-block text-sm text-terminal-accent hover:underline"
        >
          Upgrade to Pro
        </Link>
      </div>
    );
  }

  return (
    <div className="panel">
      <h2 className="text-terminal-accent font-semibold mb-3">Pro Signals</h2>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-terminal-muted border-b border-terminal-border">
            <th className="text-left py-1">Symbol</th>
            <th className="text-left py-1">Signal</th>
            <th className="text-right py-1">Strength</th>
            <th className="text-left py-1 pl-4">Reason</th>
          </tr>
        </thead>
        <tbody>
          {SIGNALS.map((s) => (
            <tr key={s.symbol} className="border-b border-terminal-border/40">
              <td className="py-2">{s.symbol}</td>
              <td
                className={
                  s.signal === "BUY"
                    ? "text-terminal-green"
                    : s.signal === "SELL"
                      ? "text-terminal-red"
                      : ""
                }
              >
                {s.signal}
              </td>
              <td className="text-right">{s.strength}</td>
              <td className="pl-4 text-terminal-muted">{s.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
