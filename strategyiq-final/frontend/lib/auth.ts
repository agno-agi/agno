import { API_URL, SEC_DISCLAIMER } from "./constants";

const TOKEN_KEY = "strategyiq_token";
const TIER_KEY = "strategyiq_tier";

export interface AuthSession {
  token: string;
  tier: string;
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
  return "Request failed";
}

export function getSession(): AuthSession | null {
  if (typeof window === "undefined") return null;
  const token = localStorage.getItem(TOKEN_KEY);
  const tier = localStorage.getItem(TIER_KEY);
  if (!token) return null;
  return { token, tier: tier || "beginner" };
}

async function syncHttpOnlyCookie(token: string | null): Promise<void> {
  try {
    if (token) {
      await fetch("/api/auth/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      });
    } else {
      await fetch("/api/auth/session", { method: "DELETE" });
    }
  } catch {
    // Cookie sync is best-effort; Bearer token in localStorage still works for API calls.
  }
}

export async function saveSession(token: string, tier: string): Promise<void> {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(TIER_KEY, tier);
  localStorage.setItem("token", token);
  localStorage.setItem("tier", tier);
  await syncHttpOnlyCookie(token);
}

export async function clearSession(): Promise<void> {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(TIER_KEY);
  localStorage.removeItem("token");
  localStorage.removeItem("tier");
  await syncHttpOnlyCookie(null);
}

export async function register(email: string, password: string): Promise<AuthSession> {
  const res = await fetch(`${API_URL}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(formatDetail(data.detail) || "Registration failed");
  await saveSession(data.access_token, data.tier);
  return { token: data.access_token, tier: data.tier };
}

export async function login(email: string, password: string): Promise<AuthSession> {
  const res = await fetch(`${API_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(formatDetail(data.detail) || "Login failed");
  await saveSession(data.access_token, data.tier);
  return { token: data.access_token, tier: data.tier };
}

export { SEC_DISCLAIMER };
