import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { jwtVerify } from "jose";
import { getJwtSecretKey, isJwtConfigured, JWT_MISCONFIGURED_MESSAGE } from "@/lib/jwt";

const PUBLIC_PATHS = new Set(["/login"]);

async function verifyToken(token: string) {
  const secret = getJwtSecretKey();
  if (!secret) {
    throw new Error(JWT_MISCONFIGURED_MESSAGE);
  }
  return jwtVerify(token, secret);
}

export async function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;

  // Always allow login + Next internals.
  if (PUBLIC_PATHS.has(pathname) || pathname.startsWith("/_next") || pathname.startsWith("/favicon")) {
    return NextResponse.next();
  }

  const token =
    req.headers.get("authorization")?.replace("Bearer ", "") ||
    req.cookies.get("token")?.value;

  const isApi =
    pathname.startsWith("/api/chat") ||
    pathname.startsWith("/api/billing");

  // Protect the terminal home (/), dashboard, and authenticated API proxies.
  const isProtected =
    pathname === "/" ||
    pathname.startsWith("/dashboard") ||
    isApi;

  if (!isProtected) {
    return NextResponse.next();
  }

  if (!isJwtConfigured()) {
    if (isApi) {
      return NextResponse.json({ error: JWT_MISCONFIGURED_MESSAGE }, { status: 503 });
    }
    return NextResponse.redirect(new URL("/login?error=jwt_config", req.url));
  }

  if (!token) {
    if (isApi) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.redirect(new URL("/login", req.url));
  }

  try {
    await verifyToken(token);
    return NextResponse.next();
  } catch {
    if (isApi) {
      return NextResponse.json({ error: "Token expired" }, { status: 401 });
    }
    const res = NextResponse.redirect(new URL("/login?error=expired", req.url));
    res.cookies.set("token", "", { path: "/", maxAge: 0 });
    return res;
  }
}

export const config = {
  matcher: ["/", "/dashboard/:path*", "/api/chat/:path*", "/api/billing/:path*"],
};
