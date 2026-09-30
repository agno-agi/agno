import { NextResponse } from "next/server";

const COOKIE_NAME = "token";
const MAX_AGE = 60 * 60 * 24; // 24h

function cookieOptions(secure: boolean) {
  return {
    httpOnly: true,
    secure,
    sameSite: "lax" as const,
    path: "/",
    maxAge: MAX_AGE,
  };
}

/** Set HttpOnly auth cookie after login/register (JS cannot set HttpOnly). */
export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const token = typeof body.token === "string" ? body.token.trim() : "";
  if (!token) {
    return NextResponse.json({ error: "token required" }, { status: 400 });
  }

  const secure = process.env.NODE_ENV === "production";
  const res = NextResponse.json({ ok: true });
  res.cookies.set(COOKIE_NAME, token, cookieOptions(secure));
  return res;
}

/** Clear auth cookie on logout. */
export async function DELETE() {
  const res = NextResponse.json({ ok: true });
  res.cookies.set(COOKIE_NAME, "", {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });
  return res;
}
