export const SEC_DISCLAIMER = "Financial information only, not financial advice";
export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type UserTier = "beginner" | "pro" | "elite";

export interface TierInfo {
  name: UserTier;
  label: string;
  price: number;
  features: string[];
}

export const TIERS: TierInfo[] = [
  {
    name: "beginner",
    label: "Beginner",
    price: 0,
    features: ["3 queries/day", "Delayed market data", "Basic screener"],
  },
  {
    name: "pro",
    label: "Pro",
    price: 29,
    features: ["Unlimited queries", "Real-time data", "Trading signals", "Grok intelligence"],
  },
  {
    name: "elite",
    label: "Elite",
    price: 79,
    features: [
      "Everything in Pro",
      "Custom agents",
      "PORT analytics (Sharpe, VaR)",
      "Portfolio management",
    ],
  },
];

export function tierRank(tier: string | null | undefined): number {
  if (tier === "elite") return 2;
  if (tier === "pro") return 1;
  return 0;
}
