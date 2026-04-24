/**
 * Server-side helpers for reading/writing the auth cookie.
 *
 * Token is stored as an httpOnly cookie (not localStorage) so client JS
 * can never read it. XSS on the dashboard cannot exfiltrate the token.
 * Every /api/* route reads the cookie here and forwards it to the
 * FastAPI backend as `Authorization: Bearer <token>`.
 */

import { NextResponse } from "next/server";
import { cookies } from "next/headers";

export const AUTH_COOKIE = "msadatax_auth";

/** Token stashed by the most recent /auth/signup or /auth/login. */
export function readAuthCookie(): string | null {
  return cookies().get(AUTH_COOKIE)?.value ?? null;
}

/** The Authorization header ready to forward to FastAPI, or undefined. */
export function authHeaderFromCookie(): Record<string, string> {
  const t = readAuthCookie();
  return t ? { authorization: `Bearer ${t}` } : {};
}

/** Write the cookie onto an outgoing NextResponse. */
export function setAuthCookie(res: NextResponse, token: string): NextResponse {
  res.cookies.set({
    name: AUTH_COOKIE,
    value: token,
    httpOnly: true,
    sameSite: "lax",
    // Secure in production (behind HTTPS); relaxed for `npm run dev` on http.
    secure: process.env.NODE_ENV === "production",
    path: "/",
    // Match the backend JWT TTL (7d default). Cookie expiry and token
    // expiry drift independently — whichever fires first kicks the user
    // back to /login, which is fine.
    maxAge: 60 * 60 * 24 * 7,
  });
  return res;
}

export function clearAuthCookie(res: NextResponse): NextResponse {
  res.cookies.set({
    name: AUTH_COOKIE,
    value: "",
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 0,
  });
  return res;
}

export function backendUrl(): string {
  return process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
}
