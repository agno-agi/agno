"use client";

import Link from "next/link";
import { useState } from "react";
import { SEC_DISCLAIMER } from "@/lib/constants";
import { getSession } from "@/lib/auth";

function formatApiError(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => (typeof item === "object" && item && "msg" in item ? String(item.msg) : String(item))).join("; ");
  }
  return "Request failed";
}

export function AIAgent() {
  const [input, setInput] = useState("");
  const [response, setResponse] = useState<string | null>(null);
  const [upgradeRequired, setUpgradeRequired] = useState(false);
  const [loading, setLoading] = useState(false);

  const send = async () => {
    if (!input.trim()) return;
    setLoading(true);
    setResponse(null);
    setUpgradeRequired(false);
    try {
      const session = getSession();
      if (!session?.token) {
        setResponse("Sign in required to use the AI agent.");
        return;
      }

      const res = await fetch("/api/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${session.token}`,
        },
        body: JSON.stringify({
          messages: [{ role: "user", content: input }],
          stream: false,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        if (res.status === 429 || data.upgrade_required) {
          setUpgradeRequired(true);
        }
        setResponse(formatApiError(data.detail || data.error || data.message));
        return;
      }
      setResponse(data.response || data.detail || "No response");
    } catch {
      setResponse("Chat unavailable — check auth and API configuration.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="panel space-y-2">
      <h2 className="text-terminal-accent font-semibold">AI Agent</h2>
      <textarea
        className="w-full bg-terminal-bg border border-terminal-border rounded p-2 text-sm h-20"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        placeholder="Ask about markets, filings, signals..."
      />
      <button
        onClick={send}
        disabled={loading}
        className="bg-terminal-accent text-terminal-bg px-3 py-1 rounded text-sm font-semibold w-full"
      >
        {loading ? "Thinking..." : "Send"}
      </button>
      {response && <p className="text-sm whitespace-pre-wrap">{response}</p>}
      {upgradeRequired && (
        <Link href="/billing?tier=pro" className="text-sm text-terminal-accent hover:underline">
          Upgrade to Pro for more queries
        </Link>
      )}
      <p className="text-xs text-terminal-muted">{SEC_DISCLAIMER}</p>
    </div>
  );
}
