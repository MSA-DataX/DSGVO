import { NextResponse } from "next/server";
import { authHeaderFromCookie, backendUrl, readAuthCookie } from "@/lib/serverAuth";

export const runtime = "nodejs";

export async function GET() {
  // Shortcut: no cookie → no need to hit backend. Saves a round-trip on
  // every page load for anonymous visitors.
  if (!readAuthCookie()) {
    return NextResponse.json({ error: "Unauthenticated" }, { status: 401 });
  }
  const upstream = await fetch(`${backendUrl()}/auth/me`, {
    headers: { ...authHeaderFromCookie() },
  });
  const text = await upstream.text();
  return new NextResponse(text, {
    status: upstream.status,
    headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
  });
}
